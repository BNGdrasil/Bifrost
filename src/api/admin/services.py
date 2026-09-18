# --------------------------------------------------------------------------
# Admin API endpoints for service management
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
from typing import Any, Dict, List

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from src.core.database import get_db
from src.core.permissions import require_admin
from src.crud.service import (
    create_service,
    delete_service,
    get_service_by_id,
    get_service_by_name,
    get_service_stats,
    get_services,
)
from src.crud.service import update_service as crud_update_service
from src.schemas.service import (
    ServiceCreate,
    ServiceHealthStatus,
    ServiceRead,
    ServiceStats,
    ServiceUpdate,
)
from src.services.services import RegistryLoadError, ServiceRegistry

router = APIRouter()
logger = structlog.get_logger()


def get_service_registry(request: Request) -> ServiceRegistry:
    """Get ServiceRegistry from app state"""
    registry = getattr(request.app.state, "service_registry", None)
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service registry not initialized",
        )
    return registry  # type: ignore[no-any-return]


async def reload_registry(request: Request, db: Session) -> None:
    """Reload the registry inline so the caller sees the routing table change.

    The request session is returned to the pool first: the reload opens its
    own session, and holding both at once would need two connections per
    admin write.

    A failure is logged and leaves the registry degraded. The database change
    itself already succeeded, so it is not rolled back here.
    """
    registry = get_service_registry(request)
    await run_in_threadpool(db.close)
    try:
        await registry.reload()
    except RegistryLoadError as exc:
        logger.error("Service registry reload failed", error=str(exc))


@router.get("/services", response_model=List[ServiceRead])
@require_admin
async def list_services(
    request: Request,
    skip: int = 0,
    limit: int = 100,
    active_only: bool = False,
    db: Session = Depends(get_db),
) -> List[ServiceRead]:
    """
    List all registered services (Admin only).

    - **skip**: Number of services to skip (pagination)
    - **limit**: Maximum number of services to return
    - **active_only**: Return only active services
    """
    services = await run_in_threadpool(
        get_services, db, skip=skip, limit=limit, active_only=active_only
    )
    return [ServiceRead.model_validate(service) for service in services]


@router.get("/services/stats", response_model=ServiceStats)
@require_admin
async def get_services_stats(
    request: Request,
    db: Session = Depends(get_db),
) -> ServiceStats:
    """Get service statistics (Admin only)."""
    return await run_in_threadpool(get_service_stats, db)


@router.get("/services/{service_id}", response_model=ServiceRead)
@require_admin
async def get_service(
    service_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> ServiceRead:
    """Get service details by ID (Admin only)."""
    service = await run_in_threadpool(get_service_by_id, db, service_id)
    if not service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service with ID {service_id} not found",
        )
    return ServiceRead.model_validate(service)


@router.post(
    "/services", response_model=ServiceRead, status_code=status.HTTP_201_CREATED
)
@require_admin
async def create_new_service(
    service_data: ServiceCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> ServiceRead:
    """
    Create a new service (Admin only).

    This is the only supported way to change the routing table. The gateway
    registry is reloaded from the database before the response is returned.
    """
    existing_service = await run_in_threadpool(
        get_service_by_name, db, service_data.name
    )
    if existing_service:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Service with name '{service_data.name}' already exists",
        )

    service = await run_in_threadpool(create_service, db, service_data)
    result = ServiceRead.model_validate(service)

    await reload_registry(request, db)

    logger.info("Service created", service_id=result.id, service_name=result.name)
    return result


@router.put("/services/{service_id}", response_model=ServiceRead)
@require_admin
async def update_existing_service(
    service_id: int,
    service_data: ServiceUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> ServiceRead:
    """
    Update a service (Admin only).

    The gateway registry is reloaded before the response is returned.
    """
    service = await run_in_threadpool(crud_update_service, db, service_id, service_data)
    if not service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service with ID {service_id} not found",
        )
    result = ServiceRead.model_validate(service)

    await reload_registry(request, db)

    logger.info("Service updated", service_id=result.id, service_name=result.name)
    return result


@router.delete("/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_admin
async def delete_existing_service(
    service_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> None:
    """
    Delete a service (Admin only).

    This removes the service from the database and from the gateway registry.
    """
    service = await run_in_threadpool(get_service_by_id, db, service_id)
    if not service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service with ID {service_id} not found",
        )

    service_name = service.name

    success = await run_in_threadpool(delete_service, db, service_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service with ID {service_id} not found",
        )

    await reload_registry(request, db)

    logger.info("Service deleted", service_id=service_id, service_name=service_name)
    return None


@router.get("/services/{service_id}/health", response_model=ServiceHealthStatus)
@require_admin
async def check_service_health(
    service_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> ServiceHealthStatus:
    """
    Read the last recorded health status of a service (Admin only).

    Use the health-check-all endpoint to trigger live probes.
    """
    service = await run_in_threadpool(get_service_by_id, db, service_id)
    if not service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service with ID {service_id} not found",
        )

    service_id_val: int = service.id  # type: ignore[assignment]
    service_name_val: str = service.name  # type: ignore[assignment]
    health_status_val: str = service.health_status  # type: ignore[assignment]
    is_active_val: bool = service.is_active  # type: ignore[assignment]

    return ServiceHealthStatus(
        service_id=service_id_val,
        service_name=service_name_val,
        health_status=health_status_val,
        last_health_check=service.last_health_check,  # type: ignore[arg-type]
        is_active=is_active_val,
    )


@router.post("/services/reload", status_code=status.HTTP_200_OK)
@require_admin
async def reload_service_registry(request: Request) -> Dict[str, Any]:
    """
    Reload the service registry from the database (Admin only).

    The reload runs inline, so a failure is reported as 503 instead of being
    swallowed by a background task.
    """
    registry = get_service_registry(request)
    try:
        await registry.reload()
    except RegistryLoadError as exc:
        logger.error("Service registry reload failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service registry reload failed: {exc}",
        )

    return {
        "message": "Service registry reloaded",
        "status": "ok",
        "service_count": len(registry.services),
    }


@router.post("/services/health-check-all", status_code=status.HTTP_200_OK)
@require_admin
async def health_check_all_services(request: Request) -> Dict[str, Any]:
    """
    Probe every registered service and persist the result (Admin only).
    """
    registry = get_service_registry(request)

    results: Dict[str, str] = {}
    for service_name in registry.services:
        try:
            is_healthy = await registry.health_check(service_name)
            results[service_name] = "healthy" if is_healthy else "unhealthy"
        except Exception as exc:  # noqa: BLE001 - one service must not stop all
            logger.error(
                "Health check failed for service",
                service_name=service_name,
                error=str(exc),
            )
            results[service_name] = "error"

    logger.info("Health checks completed", results=results)

    return {
        "message": "Health check completed",
        "service_count": len(results),
        "results": results,
    }
