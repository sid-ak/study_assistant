"""Behavior of the adapter under the free plan's limits: 429 waits, its User-Agent, and caching.

Waiting is checked through an injected ``sleep`` that records each wait instead of pausing, so the
tests run instantly and assert the exact delays.
"""

from pathlib import Path

import httpx
import pytest

from api.generate import (
    ChatMessage,
    FileResponseCache,
    GenerationError,
    OpenAICompatibleGenerator,
    RateLimitError,
    parse_duration,
)

BASE_URL = "https://llm.example/v1"
MESSAGES = [ChatMessage("user", "Which flag enables AddressSanitizer?")]
OK = httpx.Response(200, json={"choices": [{"message": {"content": "--config=asan"}}]})


class Endpoint:
    """A mock endpoint replying with queued responses, and a recorder of the adapter's waits."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        """Reply to successive requests with ``responses``."""
        self.responses = responses
        self.requests: list[httpx.Request] = []
        self.waits: list[float] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Record ``request`` and return the next queued response."""
        self.requests.append(request)
        return self.responses.pop(0)

    def sleep(self, seconds: float) -> None:
        """Record a wait instead of pausing."""
        self.waits.append(seconds)


def generator_for(
    endpoint: Endpoint, cache: FileResponseCache | None = None, max_wait_seconds: float = 90.0
) -> OpenAICompatibleGenerator:
    """A generator that sends to ``endpoint`` and waits through ``endpoint.sleep``."""
    return OpenAICompatibleGenerator(
        base_url=BASE_URL,
        model="test-model",
        api_key="sk-test",
        http_client=httpx.Client(transport=httpx.MockTransport(endpoint.handle)),
        sleep=endpoint.sleep,
        cache=cache,
        max_wait_seconds=max_wait_seconds,
    )


def too_many_requests(headers: dict[str, str]) -> httpx.Response:
    """An HTTP 429 reply carrying ``headers``."""
    return httpx.Response(429, headers=headers, text="rate limited")


def test_every_request_carries_the_clients_own_user_agent() -> None:
    """The adapter names itself, since some providers reject default library User-Agents."""
    endpoint = Endpoint([OK])

    generator_for(endpoint).generate(MESSAGES)

    assert endpoint.requests[0].headers["User-Agent"].startswith("study-assistant/")


@pytest.mark.parametrize(
    ("headers", "expected_wait"),
    [
        ({"retry-after": "2"}, 2.0),
        ({"x-ratelimit-remaining-tokens": "0", "x-ratelimit-reset-tokens": "3.412s"}, 3.412),
        (
            {
                "x-ratelimit-remaining-requests": "0",
                "x-ratelimit-reset-requests": "1m26.4s",
                "x-ratelimit-reset-tokens": "1s",
            },
            86.4,
        ),
        ({"x-ratelimit-remaining-requests": "12", "x-ratelimit-reset-tokens": "7.5s"}, 7.5),
    ],
    ids=["retry-after", "token budget", "request budget", "tokens with requests left"],
)
def test_a_429_waits_for_the_reset_the_headers_give_and_retries(
    headers: dict[str, str], expected_wait: float
) -> None:
    """The wait comes from the reply's headers, and the retried request's reply is returned."""
    endpoint = Endpoint([too_many_requests(headers), OK])

    reply = generator_for(endpoint).generate(MESSAGES)

    assert reply == "--config=asan"
    assert endpoint.waits == [expected_wait]
    assert len(endpoint.requests) == 2


def test_a_429_without_reset_headers_backs_off_exponentially() -> None:
    """With no hint in the headers, waits double: 1, 2, then 4 seconds."""
    endpoint = Endpoint([too_many_requests({}), too_many_requests({}), too_many_requests({}), OK])

    assert generator_for(endpoint).generate(MESSAGES) == "--config=asan"
    assert endpoint.waits == [1.0, 2.0, 4.0]


def test_a_wait_longer_than_the_limit_fails_at_once() -> None:
    """A budget that resets in hours raises ``RateLimitError`` instead of sleeping for hours."""
    endpoint = Endpoint(
        [
            too_many_requests(
                {"x-ratelimit-remaining-requests": "0", "x-ratelimit-reset-requests": "5h2m"}
            )
        ]
    )

    with pytest.raises(RateLimitError, match="5h2m|18120"):
        generator_for(endpoint, max_wait_seconds=90.0).generate(MESSAGES)
    assert endpoint.waits == []


def test_repeated_429s_give_up_after_the_retry_limit() -> None:
    """After four retries the adapter stops and raises ``RateLimitError``."""
    replies = []
    for _ in range(5):
        replies.append(too_many_requests({"retry-after": "1"}))
    endpoint = Endpoint(replies)

    with pytest.raises(RateLimitError):
        generator_for(endpoint).generate(MESSAGES)
    assert len(endpoint.requests) == 5
    assert endpoint.waits == [1.0, 1.0, 1.0, 1.0]


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("3.412s", 3.412),
        ("1m26.4s", 86.4),
        ("120ms", 0.12),
        ("2h0m0s", 7200.0),
        ("5h2m", 18120.0),
        ("45", 45.0),
        ("", None),
        ("soon", None),
    ],
)
def test_parse_duration_reads_reset_header_values(text: str, seconds: float | None) -> None:
    """Durations like ``1m26.4s`` and bare seconds parse to seconds; anything else is ``None``."""
    assert parse_duration(text) == (pytest.approx(seconds) if seconds is not None else None)


def test_an_identical_request_is_answered_from_the_cache(tmp_path: Path) -> None:
    """The same model, messages, and schema a second time make no request."""
    endpoint = Endpoint([OK])
    generator = generator_for(endpoint, cache=FileResponseCache(tmp_path))

    first = generator.generate(MESSAGES)
    second = generator.generate(MESSAGES)

    assert first == second == "--config=asan"
    assert len(endpoint.requests) == 1


def test_the_cache_survives_a_new_process(tmp_path: Path) -> None:
    """Replies are stored on disk, so a rerun with nothing changed makes no request."""
    generator_for(Endpoint([OK]), cache=FileResponseCache(tmp_path)).generate(MESSAGES)
    rerun = Endpoint([])

    reply = generator_for(rerun, cache=FileResponseCache(tmp_path)).generate(MESSAGES)

    assert reply == "--config=asan"
    assert rerun.requests == []


def test_a_different_request_is_not_answered_from_the_cache(tmp_path: Path) -> None:
    """Changed messages, such as different retrieved context, need a new request."""
    other = httpx.Response(200, json={"choices": [{"message": {"content": "-fsanitize=address"}}]})
    endpoint = Endpoint([OK, other])
    generator = generator_for(endpoint, cache=FileResponseCache(tmp_path))

    generator.generate(MESSAGES)
    reply = generator.generate([ChatMessage("user", "Which compiler flag enables ASan?")])

    assert reply == "-fsanitize=address"
    assert len(endpoint.requests) == 2


def test_a_failed_request_is_not_cached(tmp_path: Path) -> None:
    """Only replies are cached, so an error is retried by the next run."""
    endpoint = Endpoint([httpx.Response(500, text="down"), OK])
    generator = generator_for(endpoint, cache=FileResponseCache(tmp_path))

    with pytest.raises(GenerationError):
        generator.generate(MESSAGES)
    assert generator.generate(MESSAGES) == "--config=asan"
    assert len(endpoint.requests) == 2
