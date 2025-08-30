# --------------------------------------------------------------------------
# Router for the API Gateway service
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from src.services.services import ServiceProxy, ServiceRegistry

logger = structlog.get_logger()
router = APIRouter()


async def get_service_registry(request: Request) -> ServiceRegistry:
    """Get service registry from request state"""
    return request.app.state.service_registry  # type: ignore


async def get_service_proxy(request: Request) -> ServiceProxy:
    """Get service proxy from request state"""
    service_registry = request.app.state.service_registry
    return ServiceProxy(service_registry)


@router.get("/services")
async def list_services(
    service_registry: ServiceRegistry = Depends(get_service_registry),
) -> Dict[str, Any]:
    """List all registered services"""
    services = service_registry.list_services()
    return {"services": services, "count": len(services)}


@router.get("/services/{service_name}/health")
async def service_health(
    service_name: str, service_registry: ServiceRegistry = Depends(get_service_registry)
) -> Dict[str, Any]:
    """Check health of a specific service"""
    is_healthy = await service_registry.health_check(service_name)
    return {"service": service_name, "healthy": is_healthy}


@router.post("/admin/services")
async def add_service(
    service_data: Dict[str, Any],
    service_registry: ServiceRegistry = Depends(get_service_registry),
) -> Dict[str, Any]:
    """Add a new service to the registry (admin only)"""
    # TODO: Add authentication/authorization
    name = service_data.get("name")
    config = service_data.get("config", {})

    if not name:
        raise HTTPException(status_code=400, detail="Service name is required")

    success = await service_registry.add_service(name, config)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to add service")

    return {"message": f"Service '{name}' added successfully"}


@router.delete("/admin/services/{service_name}")
async def remove_service(
    service_name: str, service_registry: ServiceRegistry = Depends(get_service_registry)
) -> Dict[str, Any]:
    """Remove a service from the registry (admin only)"""
    # TODO: Add authentication/authorization
    success = await service_registry.remove_service(service_name)
    if not success:
        raise HTTPException(
            status_code=404, detail=f"Service '{service_name}' not found"
        )

    return {"message": f"Service '{service_name}' removed successfully"}


# Catch-all proxy route - MUST be last to avoid conflicts with specific routes
@router.api_route(
    "/{service_name}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"]
)
async def proxy_request(
    service_name: str,
    path: str,
    request: Request,
    service_proxy: ServiceProxy = Depends(get_service_proxy),
) -> Response:
    """Proxy request to backend service"""
    try:
        # Get request body
        body = await request.body()

        # Get query parameters
        params = dict(request.query_params)

        # Get headers
        headers = dict(request.headers)

        # Forward request
        response = await service_proxy.forward_request(
            service_name=service_name,
            method=request.method,
            path=f"/{path}",
            headers=headers,
            body=body if body else None,
            params=params,
        )

        # Create response
        return StreamingResponse(
            iter([response.content]),
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.headers.get("content-type"),
        )

    except ValueError as e:
        logger.error("Service not found", service_name=service_name, error=str(e))
        raise HTTPException(
            status_code=404, detail=f"Service '{service_name}' not found"
        )
    except Exception as e:
        logger.error("Proxy request failed", service_name=service_name, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")
