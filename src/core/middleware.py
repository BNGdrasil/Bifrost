# --------------------------------------------------------------------------
# Middleware for the API Gateway service
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import time
from typing import Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = structlog.get_logger()


class LoggingMiddleware(BaseHTTPMiddleware):
    """Logging middleware for request/response logging"""

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()

        # Log request
        logger.info(
            "Request started",
            method=request.method,
            url=str(request.url),
            client_ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )

        # Process request
        response = await call_next(request)

        # Calculate duration
        duration = time.time() - start_time

        # Log response
        logger.info(
            "Request completed",
            method=request.method,
            url=str(request.url),
            status_code=response.status_code,
            duration=duration,
        )

        return response  # type: ignore


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware"""

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.rate_limits: dict[str, list[float]] = {}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Simple in-memory rate limiting (in production, use Redis)
        client_ip = request.client.host if request.client else "unknown"

        # Check rate limit
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

        return await call_next(request)  # type: ignore

    def _check_rate_limit(self, client_ip: str) -> bool:
        """Simple rate limit check (60 requests per minute)"""
        current_time = time.time()
        minute_ago = current_time - 60

        # Clean old entries
        if client_ip in self.rate_limits:
            self.rate_limits[client_ip] = [
                timestamp
                for timestamp in self.rate_limits[client_ip]
                if timestamp > minute_ago
            ]
        else:
            self.rate_limits[client_ip] = []

        # Check limit
        if len(self.rate_limits[client_ip]) >= 60:
            return False

        # Add current request
        self.rate_limits[client_ip].append(current_time)
        return True
