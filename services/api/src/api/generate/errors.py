"""Errors raised by generators."""


class GenerationError(Exception):
    """The model could not produce a reply: an error status, an unreadable reply, or no text."""


class RateLimitError(GenerationError):
    """The endpoint kept refusing requests over its rate limits, or would reset too late."""
