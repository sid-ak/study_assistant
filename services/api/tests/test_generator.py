"""Behavior of ``OpenAICompatibleGenerator`` against a mocked chat-completions endpoint.

``httpx.MockTransport`` answers every request in-process, so these tests check exactly what the
adapter sends and how it reads replies, without a network connection or an API key.
"""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from api_fakes import ScriptedGenerator
from pydantic import SecretStr

from api.config import ApiSettings
from api.generate import (
    ChatMessage,
    GenerationError,
    GeneratorProtocol,
    OpenAICompatibleGenerator,
    ResponseSchema,
)

BASE_URL = "https://llm.example/v1"
SECRET = "sk-test-not-a-real-key"
MESSAGES = [ChatMessage("system", "Answer briefly."), ChatMessage("user", "Which flag?")]
SCHEMA = ResponseSchema(
    name="cited_answer",
    schema={
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    },
)


def completion(content: str) -> dict[str, Any]:
    """A chat-completions reply whose first choice says ``content``."""
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class Recorder:
    """A mock endpoint that records each request and replies with queued responses."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        """Reply to successive requests with ``responses``, in order."""
        self.responses = responses
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Record ``request`` and return the next queued response."""
        self.requests.append(request)
        return self.responses.pop(0)

    def body(self, index: int = 0) -> dict[str, Any]:
        """The JSON body of the ``index``-th request."""
        parsed: dict[str, Any] = json.loads(self.requests[index].content)
        return parsed


def generator_for(recorder: Recorder, api_key: str | None = SECRET) -> OpenAICompatibleGenerator:
    """A generator whose HTTP client sends every request to ``recorder``."""
    client = httpx.Client(transport=httpx.MockTransport(recorder.handle))
    return OpenAICompatibleGenerator(
        base_url=BASE_URL, model="test-model", api_key=api_key, http_client=client
    )


def test_generate_posts_a_chat_completion_and_returns_the_reply() -> None:
    """The request carries the model, the messages, and the key; the reply text comes back."""
    recorder = Recorder([httpx.Response(200, json=completion("--config=asan"))])

    reply = generator_for(recorder).generate(MESSAGES)

    assert reply == "--config=asan"
    [request] = recorder.requests
    assert request.method == "POST"
    assert str(request.url) == BASE_URL + "/chat/completions"
    assert request.headers["Authorization"] == "Bearer " + SECRET
    body = recorder.body()
    assert body["model"] == "test-model"
    assert body["messages"] == [
        {"role": "system", "content": "Answer briefly."},
        {"role": "user", "content": "Which flag?"},
    ]
    assert body["temperature"] == 0
    assert "response_format" not in body


def test_generate_with_a_schema_asks_for_strict_structured_output() -> None:
    """A response schema is sent as a strict ``json_schema`` response format."""
    recorder = Recorder([httpx.Response(200, json=completion('{"answer": "x"}'))])

    generator_for(recorder).generate(MESSAGES, response_schema=SCHEMA)

    assert recorder.body()["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "cited_answer", "strict": True, "schema": SCHEMA.schema},
    }


def test_generate_without_a_key_sends_no_authorization_header() -> None:
    """A local runtime needs no key, so none is sent."""
    recorder = Recorder([httpx.Response(200, json=completion("ok"))])

    generator_for(recorder, api_key=None).generate(MESSAGES)

    assert "Authorization" not in recorder.requests[0].headers


@pytest.mark.parametrize("status", [400, 401, 500])
def test_generate_raises_on_an_error_status_without_leaking_the_key(status: int) -> None:
    """An error reply raises ``GenerationError`` naming the status, never the API key."""
    recorder = Recorder([httpx.Response(status, text="bad request for " + SECRET)])

    with pytest.raises(GenerationError) as raised:
        generator_for(recorder).generate(MESSAGES)

    assert str(status) in str(raised.value)
    assert SECRET not in str(raised.value)


@pytest.mark.parametrize(
    "payload",
    [{}, {"choices": []}, {"choices": [{"message": {"content": None}}]}],
    ids=["no choices", "empty choices", "no content"],
)
def test_generate_raises_on_a_reply_without_text(payload: dict[str, Any]) -> None:
    """A reply with no message text raises ``GenerationError`` instead of returning nothing."""
    recorder = Recorder([httpx.Response(200, json=payload)])

    with pytest.raises(GenerationError):
        generator_for(recorder).generate(MESSAGES)


def test_from_settings_reads_the_generation_settings() -> None:
    """The adapter takes its endpoint, model, and key from ``GENERATION_*`` settings."""
    settings = ApiSettings(
        generation_base_url=BASE_URL + "/",
        generation_model="qwen/qwen3.8-27b",
        generation_api_key=SecretStr(SECRET),
    )

    generator = OpenAICompatibleGenerator.from_settings(settings)

    assert generator.model == "qwen/qwen3.8-27b"
    assert generator.base_url == BASE_URL


def test_settings_default_to_the_free_hosted_endpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without overrides, generation targets Groq's endpoint and the default model."""
    # A folder with no .env file, and no GENERATION_* variables, leaves only the defaults.
    monkeypatch.chdir(tmp_path)
    for name in ["GENERATION_BASE_URL", "GENERATION_MODEL"]:
        monkeypatch.delenv(name, raising=False)

    settings = ApiSettings()

    assert settings.generation_base_url == "https://api.groq.com/openai/v1"
    assert settings.generation_model == "qwen/qwen3.8-27b"


def test_the_adapter_and_the_fake_satisfy_the_protocol() -> None:
    """Both generators fit ``GeneratorProtocol``, so the graph accepts either."""
    real: GeneratorProtocol = generator_for(Recorder([]))
    fake: GeneratorProtocol = ScriptedGenerator(["ok"])
    assert isinstance(real, GeneratorProtocol)
    assert isinstance(fake, GeneratorProtocol)


@pytest.mark.parametrize(
    "error",
    [httpx.ConnectError("connection refused"), httpx.ReadTimeout("timed out")],
    ids=["unreachable", "timeout"],
)
def test_an_unreachable_endpoint_raises_generation_error(error: httpx.TransportError) -> None:
    """A connection failure or timeout is a ``GenerationError``, reported in one line."""

    def fail(request: httpx.Request) -> httpx.Response:
        """Fail the request the way the network would."""
        raise error

    client = httpx.Client(transport=httpx.MockTransport(fail))
    generator = OpenAICompatibleGenerator(
        base_url=BASE_URL, model="test-model", api_key=SECRET, http_client=client
    )

    with pytest.raises(GenerationError, match="llm.example"):
        generator.generate(MESSAGES)
