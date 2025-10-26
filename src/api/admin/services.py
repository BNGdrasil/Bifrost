# --------------------------------------------------------------------------
# Admin Services API - Service monitoring and management
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
from fastapi import APIRouter, Request
from pydantic import BaseModel

from src.core.permissions import require_admin

router = APIRouter()


class ServiceStatus(BaseModel):
    """Service status model."""

    name: str
    url: str
    status: str
    health: str


class ServiceListResponse(BaseModel):
    """Response model for service list."""

    total: int
    services: list[ServiceStatus]


@router.get("/", response_model=ServiceListResponse)
@require_admin
async def list_services(request: Request) -> ServiceListResponse:
    """List all registered services (admin only).

    Args:
        request: FastAPI Request object

    Returns:
        ServiceListResponse: List of services
    """
    # TODO: Get actual services from service registry
    return ServiceListResponse(
        total=3,
        services=[
            ServiceStatus(
                name="auth-server",
                url="http://auth-server:8001",
                status="running",
                health="healthy",
            ),
            ServiceStatus(
                name="gateway",
                url="http://gateway:8000",
                status="running",
                health="healthy",
            ),
            ServiceStatus(
                name="wegis-server",
                url="http://wegis-server:9000",
                status="running",
                health="healthy",
            ),
        ],
    )


@router.get("/{service_name}/metrics")
@require_admin
async def get_service_metrics(request: Request, service_name: str) -> dict:
    """Get metrics for a specific service (admin only).

    Args:
        request: FastAPI Request object
        service_name: Name of the service

    Returns:
        dict: Service metrics
    """
    # TODO: Fetch actual metrics from Prometheus
    return {
        "service": service_name,
        "metrics": {
            "request_count": 1000,
            "error_rate": 0.01,
            "avg_response_time": 0.05,
            "cpu_usage": 25.5,
            "memory_usage": 512,
        },
    }


@router.get("/{service_name}/health")
@require_admin
async def get_service_health(request: Request, service_name: str) -> dict:
    """Get health status of a specific service (admin only).

    Args:
        request: FastAPI Request object
        service_name: Name of the service

    Returns:
        dict: Service health status
    """
    # TODO: Check actual service health
    return {"service": service_name, "status": "healthy", "uptime": "5 days 3 hours"}
