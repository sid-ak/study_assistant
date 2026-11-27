"""Reading how long to wait from a rate-limited reply's headers."""

import re
from collections.abc import Mapping

# One number and its unit. "ms" is listed before "m" so "120ms" is not read as 120 minutes.
DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
UNIT_SECONDS = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}


def parse_duration(text: str) -> float | None:
    """Seconds in a duration such as ``1m26.4s``, ``3.412s``, ``120ms``, or a bare ``45``.

    Units are ``h``, ``m``, ``s``, and ``ms``; a bare number is seconds. Returns ``None`` for
    anything else, including an empty string.
    """
    text = text.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    seconds = 0.0
    position = 0
    for match in DURATION_PART.finditer(text):
        if match.start() != position:
            # Unreadable characters between two parts, such as "1m and 2s".
            return None
        seconds += float(match.group(1)) * UNIT_SECONDS[match.group(2)]
        position = match.end()
    if position == 0 or position != len(text):
        return None
    return seconds


def wait_from_headers(headers: Mapping[str, str]) -> float | None:
    """Seconds to wait before retrying a rate-limited request, or ``None`` if headers do not say.

    ``retry-after`` wins. Otherwise the reset of whichever budget ran out: the request budget when
    ``x-ratelimit-remaining-requests`` is 0, and the token budget in every other case.
    """
    retry_after = headers.get("retry-after")
    if retry_after is not None:
        wait = parse_duration(retry_after)
        if wait is not None:
            return wait
    if headers.get("x-ratelimit-remaining-requests") == "0":
        reset = headers.get("x-ratelimit-reset-requests")
    else:
        # Requests are left, so the request was refused for its tokens.
        reset = headers.get("x-ratelimit-reset-tokens")
    if reset is None:
        return None
    return parse_duration(reset)
