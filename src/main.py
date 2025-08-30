# --------------------------------------------------------------------------
# Bifrost API Gateway
# Main entry point for the API Gateway service
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
import uvicorn
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from prometheus_client import REGISTRY, Counter, Histogram
from prometheus_client.openmetrics.exposition import generate_latest

from src import __version__
from src.api.api import router as api_router
from src.core.config import settings
from src.core.middleware import LoggingMiddleware, RateLimitMiddleware
from src.services.services import ServiceRegistry

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Prometheus metrics
REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"]
)
REQUEST_LATENCY = Histogram("http_request_duration_seconds", "HTTP request latency")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager"""
    # Startup
    logger.info("Starting Bifrost API Gateway")

    # Initialize service registry
    app.state.service_registry = ServiceRegistry()
    await app.state.service_registry.initialize()

    logger.info("Bifrost API Gateway started successfully")

    yield

    # Shutdown
    logger.info("Shutting down Bifrost API Gateway")
    if hasattr(app.state, "service_registry"):
        await app.state.service_registry.cleanup()


def create_app() -> FastAPI:
    """Create and configure FastAPI application"""
    app = FastAPI(
        title="Bifrost API Gateway",
        description="API Gateway for bnbong backend",
        version=__version__,
        docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
        redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
        lifespan=lifespan,
    )

    # Add middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(RateLimitMiddleware)

    # Add routes
    app.include_router(api_router, prefix="/api/v1")

    # Health check endpoint
    @app.get("/health")
    async def health_check() -> dict:
        return {"status": "healthy", "service": "bifrost"}

    # Metrics endpoint
    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(REGISTRY), media_type="text/plain")

    # Root endpoint
    @app.get("/")
    async def root() -> dict:
        return {
            "message": "Welcome to Bifrost API Gateway",
            "version": __version__,
            "docs": "/docs" if settings.ENVIRONMENT != "production" else None,
        }

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.ENVIRONMENT == "development",
        log_level=settings.LOG_LEVEL.lower(),
    )
