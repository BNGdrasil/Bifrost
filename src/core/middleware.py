# --------------------------------------------------------------------------
# Middleware for the API Gateway service
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import time
import uuid
from collections import deque
from typing import Callable, Deque, Dict

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from src.core.config import settings
from src.core.metrics import GATEWAY_SERVICE, record_request

logger = structlog.get_logger()

# How often idle client entries are swept out of the rate limit table.
RATE_LIMIT_SWEEP_INTERVAL_SECONDS = 60.0
RATE_LIMIT_WINDOW_SECONDS = 60.0


def client_identity(request: Request) -> str:
    """Resolve the client identity used for rate limiting.

    Nginx terminates TLS in front of the gateway and sets X-Forwarded-For, so
    the first entry is the original visitor. Direct exposure of the gateway
    port must be prevented at the network layer and by running uvicorn with
    --proxy-headers --forwarded-allow-ips.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


class LoggingMiddleware(BaseHTTPMiddleware):
    """Logging middleware for request/response logging"""

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()

        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id

        logger.info(
            "Request started",
            method=request.method,
            url=str(request.url),
            client_ip=client_identity(request),
            user_agent=request.headers.get("user-agent"),
            request_id=request_id,
        )

        response: Response = await call_next(request)

        duration = time.time() - start_time
        response.headers["x-request-id"] = request_id
        response.headers["x-process-time"] = f"{duration:.6f}"

        logger.info(
            "Request completed",
            method=request.method,
            url=str(request.url),
            status_code=response.status_code,
            duration=duration,
            request_id=request_id,
        )

        return response


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record Prometheus counters and latency for every handled request.

    The proxy route stores the resolved upstream name in the request scope so
    that proxied traffic is labelled per service without using the raw path.
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception:
            duration = time.perf_counter() - start_time
            record_request(request.method, self._service_label(request), 500, duration)
            raise

        duration = time.perf_counter() - start_time
        record_request(
            request.method,
            self._service_label(request),
            response.status_code,
            duration,
        )
        return response

    @staticmethod
    def _service_label(request: Request) -> str:
        scope_state = request.scope.get("state") or {}
        label = scope_state.get("proxy_service")
        return str(label) if label else GATEWAY_SERVICE


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed window in-process rate limiting keyed by client identity.

    Liveness, readiness and metrics endpoints are exempt so that monitoring is
    never throttled. Idle client entries are swept periodically so that the
    table does not grow without bound.
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.rate_limits: Dict[str, Deque[float]] = {}
        self._last_sweep = time.monotonic()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in set(settings.RATE_LIMIT_EXEMPT_PATHS):
            return await call_next(request)  # type: ignore[no-any-return]

        client_ip = client_identity(request)

        if not self._check_rate_limit(client_ip):
            logger.warning(
                "Rate limit exceeded",
                client_ip=client_ip,
                method=request.method,
                url=str(request.url),
            )
            return Response(
                content="Rate limit exceeded", status_code=429, media_type="text/plain"
            )

        return await call_next(request)  # type: ignore[no-any-return]

    def _sweep(self, now: float) -> None:
        """Remove client entries that have no timestamps inside the window."""
        if now - self._last_sweep < RATE_LIMIT_SWEEP_INTERVAL_SECONDS:
            return
        self._last_sweep = now
        cutoff = now - RATE_LIMIT_WINDOW_SECONDS
        stale = [
            key
            for key, timestamps in self.rate_limits.items()
            if not timestamps or timestamps[-1] <= cutoff
        ]
        for key in stale:
            del self.rate_limits[key]

    def _check_rate_limit(self, client_ip: str) -> bool:
        """Allow the request when the configured per-minute budget is free."""
        current_time = time.monotonic()
        self._sweep(current_time)

        cutoff = current_time - RATE_LIMIT_WINDOW_SECONDS
        timestamps = self.rate_limits.setdefault(client_ip, deque())
        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()

        if len(timestamps) >= settings.RATE_LIMIT_PER_MINUTE:
            return False

        timestamps.append(current_time)
        return True
