"""Sanitized error detail for HTTP responses (CodeQL py/stack-trace-exposure).

The console is a maintainer-only dashboard, so an exception string in a response
is a mild leak — but it is still a leak of internal detail to an HTTP client, and
the fix costs nothing. Full exception with traceback goes to the server log; the
response gets a short single-line summary that is still enough to diagnose from.
"""

from __future__ import annotations

import logging

MAX_DETAIL_CHARS = 200


def safe_detail(exc: BaseException, *, logger: logging.Logger, context: str) -> str:
    """Log `exc` in full (with traceback) and return a short, response-safe summary."""
    logger.exception("%s", context)
    message = " ".join(str(exc).split())
    if len(message) > MAX_DETAIL_CHARS:
        message = message[: MAX_DETAIL_CHARS - 1].rstrip() + "\u2026"
    name = type(exc).__name__
    return f"{name}: {message}" if message else name
