"""Request-scoped context.

Binds one correlation ID per request so every log line, job, and audit event produced while
handling it can be joined (specification §17.5).
"""

import re
import time
from uuid import uuid4

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"

# An inbound request ID is untrusted input (specification §15.4). Accepting arbitrary text
# would let a caller forge or bloat log records, so anything that is not a short, plain
# token is discarded in favour of a generated one.
_SAFE_REQUEST_ID = re.compile(r"\A[A-Za-z0-9._-]{1,128}\Z")

log = structlog.get_logger(__name__)


def accept_or_generate_request_id(supplied: str | None) -> str:
    if supplied is not None and _SAFE_REQUEST_ID.match(supplied):
        return supplied
    return str(uuid4())


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind the correlation ID, log one structured line per request, echo the ID back."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        correlation_id = accept_or_generate_request_id(request.headers.get(REQUEST_ID_HEADER))

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception(
                "request.failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )
            raise

        log.info(
            "request.completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        response.headers[REQUEST_ID_HEADER] = correlation_id
        return response
