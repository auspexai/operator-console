"""Sanitized error detail for HTTP responses (CodeQL py/stack-trace-exposure).

The console is a maintainer-only dashboard, so leaking exception text is mild
here — but it is still internal detail crossing an HTTP boundary, and the fix
costs nothing.

**Why this returns a reference and not the exception text.** The first attempt
kept a truncated `TypeName: message` in the response. That is a real improvement
— the traceback goes to the log, the response is bounded to one line — but it
does NOT clear the finding, because exception-derived data still reaches the
client and that is exactly what the query tracks. Truncating tainted data leaves
it tainted.

So: the full exception, with traceback, goes to the log under a short random
reference, and the response carries our own message plus that reference. Nothing
exception-derived crosses the boundary.

The cost is real and worth stating: the failure cause is no longer readable
straight off the HTTP response. The reference is what ties a report back to the
exact log line — `journalctl -u auspexai-operator-console | grep <ref>`.
"""

from __future__ import annotations

import logging
import uuid

__all__ = ["logged_failure"]


def logged_failure(exc: BaseException, *, logger: logging.Logger, context: str) -> str:
    """Log `exc` in full under a short reference; return a response-safe message.

    `context` is caller-supplied static text, never derived from the exception,
    so the returned string carries no tainted data."""
    ref = uuid.uuid4().hex[:8]
    logger.exception("[%s] %s", ref, context)
    return f"{context} (see server log, ref {ref})"
