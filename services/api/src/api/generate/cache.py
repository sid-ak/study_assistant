"""Caching model replies, so a rerun with nothing changed makes no request."""

import hashlib
import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ResponseCacheProtocol(Protocol):
    """Stores replies under a key that identifies the whole request."""

    def get(self, key: str) -> str | None:
        """The reply stored under ``key``, or ``None``."""
        ...

    def put(self, key: str, reply: str) -> None:
        """Store ``reply`` under ``key``."""
        ...


def cache_key(body: dict[str, Any]) -> str:
    """A key for a request body: the SHA-256 of its JSON with sorted keys.

    The body holds the model, every message (the prompt, the question, and the retrieved context),
    and the response schema, so a change to any of them gives a different key.
    """
    # sort_keys: the same body always serializes to the same text, whatever order it was built in.
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class FileResponseCache:
    """A ``ResponseCacheProtocol`` that keeps one JSON file per reply in a folder."""

    def __init__(self, folder: Path) -> None:
        """Store replies under ``folder``, created on the first write."""
        self.folder = folder

    def path_for(self, key: str) -> Path:
        """The file that holds the reply for ``key``."""
        return self.folder / f"{key}.json"

    def get(self, key: str) -> str | None:
        """The reply stored under ``key``, or ``None``."""
        path = self.path_for(key)
        if not path.is_file():
            return None
        stored = json.loads(path.read_text(encoding="utf-8"))
        reply = stored.get("reply")
        if not isinstance(reply, str):
            return None
        return reply

    def put(self, key: str, reply: str) -> None:
        """Store ``reply`` under ``key``."""
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path_for(key).write_text(json.dumps({"reply": reply}), encoding="utf-8")
