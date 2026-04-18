"""Correlation-ID middleware for the MCP server.

Mirrors the Python API pattern: honor inbound X-Request-Id / traceparent,
mint them if absent, echo on response so grep-by-id works across services.
"""
from __future__ import annotations

import logging
import re
import secrets
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("shipsmart_mcp.requests")

_TRACEPARENT_RE = re.compile(r"^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")


def _new_traceparent() -> str:
    return f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # noqa: ANN001
        request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
        traceparent = request.headers.get("traceparent")
        if not traceparent or not _TRACEPARENT_RE.match(traceparent):
            traceparent = _new_traceparent()

        request.state.request_id = request_id
        request.state.traceparent = traceparent

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        logger.info(
            "%s %s → %d (%.1fms) [%s]",
            request.method, request.url.path, response.status_code,
            duration_ms, request_id,
        )
        response.headers["X-Request-Id"] = request_id
        response.headers["traceparent"] = traceparent
        return response
