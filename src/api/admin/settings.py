# --------------------------------------------------------------------------
# Admin Settings API - System settings and real statistics
#
# @author bnbong bbbong9@gmail.com
#
# Only values the gateway can actually compute are returned. Everything that
# would require a store Bifrost does not have is reported as null instead of a
# fabricated number.
# --------------------------------------------------------------------------
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from src import __version__
from src.core.config import settings as app_settings
from src.core.database import get_db
from src.core.permissions import require_admin, require_super_admin
from src.crud.service import get_service_stats
from src.services.services import ServiceRegistry

router = APIRouter()


class SettingsResponse(BaseModel):
    """Effective runtime settings of the gateway process."""

    settings: Dict[str, Any]


def _registry(request: Request) -> Optional[ServiceRegistry]:
    return getattr(request.app.state, "service_registry", None)


@router.get("/", response_model=SettingsResponse)
@require_admin
async def get_settings(request: Request) -> SettingsResponse:
    """Return the effective settings of the running gateway (admin only).

    These values are read from the process configuration. They are not
    editable at runtime.
    """
    return SettingsResponse(
        settings={
            "environment": app_settings.ENVIRONMENT,
            "version": __version__,
            "debug": app_settings.DEBUG,
            "log_level": app_settings.LOG_LEVEL,
            "rate_limit_per_minute": app_settings.RATE_LIMIT_PER_MINUTE,
            "rate_limit_exempt_paths": list(app_settings.RATE_LIMIT_EXEMPT_PATHS),
            "max_request_body_bytes": app_settings.MAX_REQUEST_BODY_BYTES,
            "proxy_timeout_seconds": app_settings.PROXY_TIMEOUT_SECONDS,
            "cors_origins": app_settings.all_cors_origins,
            "metrics_enabled": app_settings.ENABLE_METRICS,
            "editable_at_runtime": False,
        }
    )


@router.put("/")
@require_super_admin
async def update_settings(request: Request, settings: Dict[str, Any]) -> Dict[str, Any]:
    """Not implemented. Settings are supplied by the deployment environment."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "Runtime settings updates are not implemented. Change the "
            "deployment environment variables and restart the gateway."
        ),
    )


@router.get("/stats/overview")
@require_admin
async def get_stats_overview(
    request: Request,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Return statistics the gateway can actually compute (admin only).

    Fields that would require data Bifrost does not own are null.
    """
    stats = await run_in_threadpool(get_service_stats, db)
    registry = _registry(request)

    return {
        "services": {
            "total": stats.total_services,
            "active": stats.active_services,
            "healthy": stats.healthy_services,
            "unhealthy": stats.unhealthy_services,
            "unknown": stats.unknown_services,
        },
        "registry": {
            "ready": bool(getattr(registry, "ready", False)),
            "loaded_services": len(registry.services) if registry else 0,
            "last_error": getattr(registry, "last_error", None),
        },
        "app": {
            "version": __version__,
            "environment": app_settings.ENVIRONMENT,
        },
        "users": None,
        "api_requests": None,
        "system": None,
    }
