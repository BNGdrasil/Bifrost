# --------------------------------------------------------------------------
# Admin API endpoints for service management
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
from typing import List

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.permissions import require_admin, require_role
from src.crud.service import (
    create_service,
    delete_service,
    get_service_by_id,
    get_service_by_name,
    get_service_stats,
    get_services,
    update_service,
    update_service_health,
)
from src.models.service import Service as ServiceModel
from src.schemas.service import (
    ServiceCreate,
    ServiceHealthStatus,
    ServiceRead,
    ServiceStats,
    ServiceUpdate,
)
from src.services.services import ServiceRegistry

router = APIRouter()
logger = structlog.get_logger()


def get_service_registry(request: Request) -> ServiceRegistry:
    """Get ServiceRegistry from app state"""
    if not hasattr(request.app.state, "service_registry"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service registry not initialized",
        )
    registry: ServiceRegistry = request.app.state.service_registry
    return registry


async def reload_registry_background(registry: ServiceRegistry) -> None:
    """Background task to reload service registry"""
    try:
        await registry.reload()
        logger.info("Service registry reloaded successfully")
    except Exception as e:
        logger.error("Failed to reload service registry", error=str(e))


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
    services = get_services(db, skip=skip, limit=limit, active_only=active_only)
    return [ServiceRead.model_validate(service) for service in services]


@router.get("/services/stats", response_model=ServiceStats)
@require_admin
async def get_services_stats(
    request: Request,
    db: Session = Depends(get_db),
) -> ServiceStats:
    """Get service statistics (Admin only)."""
    return get_service_stats(db)


@router.get("/services/{service_id}", response_model=ServiceRead)
@require_admin
async def get_service(
    service_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> ServiceRead:
    """Get service details by ID (Admin only)."""
    service = get_service_by_id(db, service_id)
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
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ServiceRead:
    """
    Create a new service (Admin only).

    Service will be automatically added to the gateway's service registry.
    """
    # Check if service with same name exists
    existing_service = get_service_by_name(db, service_data.name)
    if existing_service:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Service with name '{service_data.name}' already exists",
        )

    service = create_service(db, service_data)

    # Reload service registry to include new service
    registry = get_service_registry(request)
    background_tasks.add_task(reload_registry_background, registry)

    logger.info("Service created", service_id=service.id, service_name=service.name)

    return ServiceRead.model_validate(service)


@router.put("/services/{service_id}", response_model=ServiceRead)
@require_admin
async def update_existing_service(
    service_id: int,
    service_data: ServiceUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ServiceRead:
    """
    Update a service (Admin only).

    Service registry will be automatically reloaded.
    """
    service = update_service(db, service_id, service_data)
    if not service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service with ID {service_id} not found",
        )

    # Reload service registry to apply changes
    registry = get_service_registry(request)
    background_tasks.add_task(reload_registry_background, registry)

    logger.info("Service updated", service_id=service.id, service_name=service.name)

    return ServiceRead.model_validate(service)


@router.delete("/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_admin
async def delete_existing_service(
    service_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Delete a service (Admin only).

    This will remove the service from the database and service registry.
    """
    # Get service info before deletion for logging
    service = get_service_by_id(db, service_id)
    if not service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service with ID {service_id} not found",
        )

    service_name = service.name

    success = delete_service(db, service_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service with ID {service_id} not found",
        )

    # Reload service registry to remove service
    registry = get_service_registry(request)
    background_tasks.add_task(reload_registry_background, registry)

    logger.info("Service deleted", service_id=service_id, service_name=service_name)

    return {"message": f"Service {service_id} deleted"}


@router.get("/services/{service_id}/health", response_model=ServiceHealthStatus)
@require_admin
async def check_service_health(
    service_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> ServiceHealthStatus:
    """
    Check health status of a service (Admin only).

    This endpoint retrieves the last known health status from the database.
    For real-time health check, use the health check background task.
    """
    service = get_service_by_id(db, service_id)
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
async def reload_service_registry(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Reload service registry from database (Admin only).

    This will refresh the in-memory service registry with latest data from database.
    """
    registry = get_service_registry(request)

    # Trigger service registry reload as background task
    background_tasks.add_task(reload_registry_background, registry)

    logger.info("Service registry reload triggered")

    return {
        "message": "Service registry reload triggered",
        "status": "processing",
        "note": "Registry will be reloaded in the background",
    }


async def perform_health_checks_background(registry: ServiceRegistry) -> None:
    """Background task to perform health checks on all services"""
    try:
        service_names = list(registry.services.keys())
        logger.info("Starting health checks", service_count=len(service_names))

        results = {}
        for service_name in service_names:
            try:
                is_healthy = await registry.health_check(service_name)
                results[service_name] = "healthy" if is_healthy else "unhealthy"
            except Exception as e:
                logger.error(
                    "Health check failed for service",
                    service_name=service_name,
                    error=str(e),
                )
                results[service_name] = "error"

        logger.info("Health checks completed", results=results)
    except Exception as e:
        logger.error("Failed to perform health checks", error=str(e))


@router.post("/services/health-check-all", status_code=status.HTTP_202_ACCEPTED)
@require_admin
async def health_check_all_services(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Trigger health check for all services (Admin only).

    This will check the health status of all registered services and update
    the database with the results. The operation runs in the background.
    """
    registry = get_service_registry(request)

    # Trigger health checks as background task
    background_tasks.add_task(perform_health_checks_background, registry)

    logger.info("Health check for all services triggered")

    return {
        "message": "Health check for all services triggered",
        "status": "processing",
        "service_count": len(registry.services),
        "note": "Health checks will be performed in the background",
    }
