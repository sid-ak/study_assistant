"""``OpenAICompatibleGenerator``: a ``Generator`` over the OpenAI-compatible chat API."""

import time
from collections.abc import Callable
from typing import Any

import httpx

from api.config import ApiSettings
from api.generate.cache import FileResponseCache, ResponseCacheProtocol, cache_key
from api.generate.errors import GenerationError, RateLimitError
from api.generate.protocol import ChatMessage, ResponseSchema
from api.generate.rate_limit import wait_from_headers

# How long one request may take before it fails. Replies normally arrive in about a second.
REQUEST_TIMEOUT_SECONDS = 60.0
# The longest single wait for a rate limit to reset. A per-minute budget resets well within it; a
# daily budget does not, and waiting hours would look like a hang.
DEFAULT_MAX_WAIT_SECONDS = 90.0
# Rate-limited retries before giving up.
MAX_RETRIES = 4
# How the client names itself in every request.
USER_AGENT = "study-assistant/0.0.0"


class OpenAICompatibleGenerator:
    """Sends chat-completion requests to any endpoint that speaks the OpenAI-compatible protocol.

    The protocol is implemented by hosted providers and local runtimes alike, so the endpoint and
    model are settings rather than code. Replies are requested at temperature 0, so the same
    request gives the same reply as far as the model allows.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None,
        http_client: httpx.Client | None = None,
        cache: ResponseCacheProtocol | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS,
    ) -> None:
        """Send requests to ``base_url`` for ``model``.

        ``http_client`` replaces the default client, ``cache`` answers repeated requests without
        sending them, ``sleep`` performs the waits between retries (tests pass a recorder), and
        ``max_wait_seconds`` is the longest single wait before giving up with ``RateLimitError``.
        """
        self.base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        if http_client is None:
            http_client = httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
        self.http_client = http_client
        self.cache = cache
        self.sleep = sleep
        self.max_wait_seconds = max_wait_seconds

    @classmethod
    def from_settings(cls, settings: ApiSettings) -> "OpenAICompatibleGenerator":
        """A generator for the configured endpoint, model, and key."""
        api_key = None
        if settings.generation_api_key is not None:
            api_key = settings.generation_api_key.get_secret_value()
        cache = None
        if settings.generation_cache_dir is not None:
            cache = FileResponseCache(settings.generation_cache_dir)
        return cls(
            base_url=settings.generation_base_url,
            model=settings.generation_model,
            api_key=api_key,
            cache=cache,
        )

    @property
    def model(self) -> str:
        """The model that produces the replies."""
        return self._model

    def generate(
        self, messages: list[ChatMessage], *, response_schema: ResponseSchema | None = None
    ) -> str:
        """Return the reply to ``messages``, from the cache when this exact request was answered.

        Otherwise send one chat-completion request, waiting and retrying while the endpoint
        answers HTTP 429, and cache the reply.
        """
        body = request_body(self._model, messages, response_schema)
        key = cache_key(body)
        if self.cache is not None:
            cached = self.cache.get(key)
            if cached is not None:
                return cached
        reply = reply_text(self.send(body))
        if self.cache is not None:
            self.cache.put(key, reply)
        return reply

    def send(self, body: dict[str, Any]) -> httpx.Response:
        """Post ``body`` and return the successful response, waiting out rate limits.

        Raises ``RateLimitError`` after ``MAX_RETRIES`` rate-limited retries, or at once when the
        limit resets later than ``max_wait_seconds``, and ``GenerationError`` on any other error.
        """
        # Some providers' firewalls reject default library User-Agents, so the client names itself.
        headers = {"User-Agent": USER_AGENT}
        if self._api_key is not None:
            headers["Authorization"] = "Bearer " + self._api_key
        retries = 0
        while True:
            try:
                response = self.http_client.post(
                    self.base_url + "/chat/completions", json=body, headers=headers
                )
            except httpx.TransportError as error:
                # Connection refused, a failed DNS lookup, or the request timing out.
                raise GenerationError(f"Could not reach {self.base_url}: {error}") from error
            if response.status_code != 429:
                break
            if retries == MAX_RETRIES:
                raise RateLimitError(
                    f"{self.base_url} is still rate limiting after {MAX_RETRIES} retries."
                )
            wait = wait_from_headers(response.headers)
            if wait is None:
                # No hint from the endpoint: wait 1, 2, 4, then 8 seconds.
                wait = 2.0**retries
            if wait > self.max_wait_seconds:
                raise RateLimitError(
                    f"{self.base_url}'s rate limit resets in {wait:.0f} s, "
                    f"longer than the {self.max_wait_seconds:.0f} s this client waits."
                )
            self.sleep(wait)
            retries += 1
        if response.status_code != 200:
            # The status alone: an error body can echo request details, including the key.
            raise GenerationError(
                f"{self.base_url} answered HTTP {response.status_code} for model {self._model!r}."
            )
        return response


def request_body(
    model: str, messages: list[ChatMessage], response_schema: ResponseSchema | None
) -> dict[str, Any]:
    """The JSON body of a chat-completion request."""
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": message.role, "content": message.content} for message in messages],
        # 0 asks for the most likely reply every time, so reruns and cached replies agree.
        "temperature": 0,
    }
    if response_schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            # strict: the reply must match the schema exactly, not merely be valid JSON.
            "json_schema": {
                "name": response_schema.name,
                "strict": True,
                "schema": response_schema.schema,
            },
        }
    return body


def reply_text(response: httpx.Response) -> str:
    """The text of the first choice in a chat-completion reply, or ``GenerationError``."""
    try:
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise GenerationError("The reply did not contain a message.") from error
    if not isinstance(content, str):
        raise GenerationError("The reply's message has no text.")
    return content
