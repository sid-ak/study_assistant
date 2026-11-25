"""Probe an OpenAI-compatible endpoint for what the MVP generator needs.

Reads GENERATION_BASE_URL, GENERATION_API_KEY and GENERATION_MODEL from the
environment, then checks three things against the live API:

1. A plain chat completion works, and which rate-limit headers come back.
2. Strict JSON-schema structured output returns an answer plus cited ids.
3. A tool call is produced when a `search` tool is offered.

Only the Python standard library is used, so nothing needs installing.

Run from the repository root with the settings loaded from .env:

    set -a; source .env; set +a; python3 scripts/probes/probe_generation.py

Results from 2026-11-25 are recorded in docs/decisions/0011-free-hosted-generation.md.
"""

import json
import os
import time
import urllib.error
import urllib.request

BASE_URL = os.environ["GENERATION_BASE_URL"].rstrip("/")
API_KEY = os.environ["GENERATION_API_KEY"]
MODEL = os.environ["GENERATION_MODEL"]

CONTEXT = (
    "[chunk-1] CMake: set CMAKE_BUILD_TYPE=Release for optimized builds.\n"
    "[chunk-2] Bazel: --config=asan enables AddressSanitizer.\n"
)
QUESTION = "Which flag enables AddressSanitizer in Bazel?"


def post_chat(body: dict) -> tuple[dict, dict, float]:
    """Send one chat-completions request; return the JSON, the headers, and seconds taken."""
    request = urllib.request.Request(
        BASE_URL + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + API_KEY,
            "Content-Type": "application/json",
            # Cloudflare in front of some providers rejects urllib's default
            # "Python-urllib" User-Agent with error 1010, so send a plain client name.
            "User-Agent": "generation-probe/1.0",
        },
        method="POST",
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read())
            headers = dict(response.headers)
    except urllib.error.HTTPError as error:
        print("HTTP", error.code, error.read().decode("utf-8")[:500])
        raise
    seconds = time.perf_counter() - start
    return payload, headers, seconds


def check_plain_chat() -> None:
    """Check a plain completion and print any rate-limit headers."""
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
    }
    payload, headers, seconds = post_chat(body)
    print("1. plain chat:", repr(payload["choices"][0]["message"]["content"]))
    print("   seconds:", round(seconds, 2), "usage:", payload.get("usage"))
    for name, value in headers.items():
        if "ratelimit" in name.lower():
            print("   header", name, "=", value)


def check_structured_output() -> None:
    """Check strict JSON-schema output with an answer and the cited chunk ids."""
    schema = {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "cited_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["answer", "cited_ids"],
        "additionalProperties": False,
    }
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "Answer only from the context and cite chunk ids."},
            {"role": "user", "content": CONTEXT + "\nQuestion: " + QUESTION},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "cited_answer", "strict": True, "schema": schema},
        },
    }
    payload, _headers, seconds = post_chat(body)
    text = payload["choices"][0]["message"]["content"]
    parsed = json.loads(text)
    print("2. structured output:", parsed)
    print("   seconds:", round(seconds, 2))


def check_tool_call() -> None:
    """Check that the model calls a `search` tool when one is offered."""
    search_tool = {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search the release-engineering corpus and return ranked chunks.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": QUESTION}],
        "tools": [search_tool],
        "tool_choice": "auto",
    }
    payload, _headers, seconds = post_chat(body)
    message = payload["choices"][0]["message"]
    print("3. tool calls:", json.dumps(message.get("tool_calls"), indent=2))
    print("   seconds:", round(seconds, 2))


if __name__ == "__main__":
    print("endpoint:", BASE_URL, "model:", MODEL)
    check_plain_chat()
    check_structured_output()
    check_tool_call()
