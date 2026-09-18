# --------------------------------------------------------------------------
# Bifrost API Gateway
# Main entry point for the API Gateway service
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict

import structlog
import uvicorn
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest
from starlette.concurrency import run_in_threadpool

from src import __version__
from src.api.admin import admin_router
from src.api.api import router as api_router
from src.core.config import settings
from src.core.database import check_database_connection
from src.core.middleware import (
    LoggingMiddleware,
    MetricsMiddleware,
    RateLimitMiddleware,
)
from src.services.services import ServiceProxy, ServiceRegistry, create_http_client

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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager.

    One HTTP client is created for the whole process and shared by the proxy
    and the registry health checks, so connection pooling is preserved and no
    client is leaked per request.
    """
    logger.info("Starting Bifrost API Gateway")

    if "*" in settings.ALLOWED_HOSTS:
        logger.warning(
            "Host header checking is disabled",
            allowed_hosts=settings.ALLOWED_HOSTS,
            environment=settings.ENVIRONMENT,
            hint="Set ALLOWED_HOSTS to the host names this gateway serves",
        )
    if settings.FORWARDED_ALLOW_IPS.strip() == "*":
        logger.warning(
            "Forwarded headers are trusted from any address",
            environment=settings.ENVIRONMENT,
            hint="Set FORWARDED_ALLOW_IPS to the reverse proxy addresses",
        )

    http_client = create_http_client()
    app.state.http_client = http_client

    registry = ServiceRegistry(http_client=http_client)
    app.state.service_registry = registry
    app.state.service_proxy = ServiceProxy(registry, http_client)

    await registry.initialize()

    logger.info(
        "Bifrost API Gateway started",
        registry_ready=registry.ready,
        service_count=len(registry.services),
    )

    yield

    logger.info("Shutting down Bifrost API Gateway")
    if hasattr(app.state, "service_registry"):
        await app.state.service_registry.cleanup()
    await http_client.aclose()


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

    # Middleware. add_middleware puts the newest layer on the outside, so the
    # calls below run bottom up: CORS, then logging, then metrics, then the
    # host check, then the rate limiter closest to the routes. Logging and
    # metrics therefore also observe the responses the rate limiter rejects.
    app.add_middleware(RateLimitMiddleware)

    if settings.ENVIRONMENT != "test":
        # ALLOWED_HOSTS is guaranteed non-empty by the settings validator, so
        # the host check can never be skipped by an omitted value.
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)

    app.add_middleware(MetricsMiddleware)
    app.add_middleware(LoggingMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add routes
    app.include_router(api_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/admin/api")

    @app.get("/health")
    async def health_check() -> Dict[str, Any]:
        """Liveness probe. Always succeeds while the process can serve."""
        return {"status": "healthy", "service": "bifrost"}

    @app.get("/ready")
    async def readiness_check() -> Response:
        """Readiness probe covering the database and the service registry."""
        database_ok = True
        database_error = None
        try:
            await run_in_threadpool(check_database_connection)
        except Exception as exc:  # noqa: BLE001 - reported as not ready
            database_ok = False
            database_error = str(exc)

        registry = getattr(app.state, "service_registry", None)
        registry_ready = bool(getattr(registry, "ready", False))
        registry_error = getattr(registry, "last_error", None)

        payload: Dict[str, Any] = {
            "status": "ready" if database_ok and registry_ready else "not_ready",
            "database": "ok" if database_ok else "error",
            "registry": "ok" if registry_ready else "degraded",
            "service_count": len(registry.services) if registry is not None else 0,
        }
        if database_error:
            payload["database_error"] = database_error
        if registry_error:
            payload["registry_error"] = registry_error

        status_code = 200 if database_ok and registry_ready else 503
        return JSONResponse(content=payload, status_code=status_code)

    @app.get("/metrics")
    async def metrics() -> Response:
        """Prometheus exposition endpoint."""
        return Response(
            generate_latest(REGISTRY),
            headers={"content-type": CONTENT_TYPE_LATEST},
        )

    @app.get("/")
    async def root() -> Dict[str, Any]:
        return {
            "message": "Welcome to Bifrost API Gateway",
            "version": __version__,
            "docs": "/docs" if settings.ENVIRONMENT != "production" else None,
        }

    return app


app = create_app()


def main() -> None:
    """Console entry point.

    The service registry is an in-process snapshot, so exactly one worker is
    supported. Run more replicas behind the reverse proxy instead of raising
    the worker count.
    """
    reload = settings.ENVIRONMENT == "development"
    uvicorn.run(
        "src.main:app" if reload else app,
        host=settings.HOST,
        port=settings.PORT,
        workers=1,
        reload=reload,
        log_level=settings.LOG_LEVEL.lower(),
        proxy_headers=True,
        forwarded_allow_ips=settings.FORWARDED_ALLOW_IPS,
    )


if __name__ == "__main__":
    main()
