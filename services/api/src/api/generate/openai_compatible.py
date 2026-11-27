"""``OpenAICompatibleGenerator``: a ``Generator`` over the OpenAI-compatible chat API."""

from typing import Any

import httpx

from api.config import ApiSettings
from api.generate.errors import GenerationError
from api.generate.protocol import ChatMessage, ResponseSchema

# How long one request may take before it fails. Replies normally arrive in about a second.
REQUEST_TIMEOUT_SECONDS = 60.0


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
    ) -> None:
        """Send requests to ``base_url`` for ``model``; ``http_client`` replaces the default one."""
        self.base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        if http_client is None:
            http_client = httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
        self.http_client = http_client

    @classmethod
    def from_settings(cls, settings: ApiSettings) -> "OpenAICompatibleGenerator":
        """A generator for the configured endpoint, model, and key."""
        api_key = None
        if settings.generation_api_key is not None:
            api_key = settings.generation_api_key.get_secret_value()
        return cls(
            base_url=settings.generation_base_url,
            model=settings.generation_model,
            api_key=api_key,
        )

    @property
    def model(self) -> str:
        """The model that produces the replies."""
        return self._model

    def generate(
        self, messages: list[ChatMessage], *, response_schema: ResponseSchema | None = None
    ) -> str:
        """Send one chat-completion request and return the reply's text."""
        body = request_body(self._model, messages, response_schema)
        headers = {}
        if self._api_key is not None:
            headers["Authorization"] = "Bearer " + self._api_key
        response = self.http_client.post(
            self.base_url + "/chat/completions", json=body, headers=headers
        )
        if response.status_code != 200:
            # The status alone: an error body can echo request details, including the key.
            raise GenerationError(
                f"{self.base_url} answered HTTP {response.status_code} for model {self._model!r}."
            )
        return reply_text(response)


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
