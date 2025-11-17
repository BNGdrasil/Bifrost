# --------------------------------------------------------------------------
# Service registry and proxy functionality for the API Gateway service
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
from typing import Any, Dict, Optional

import httpx
import structlog

from src.core.database import SessionLocal
from src.crud.service import get_services, update_service_health

logger = structlog.get_logger()


class ServiceRegistry:
    """Service registry for managing API endpoints (DB-based)"""

    def __init__(self) -> None:
        self.services: Dict[str, Dict[str, Any]] = {}
        self.http_client = httpx.AsyncClient(timeout=30.0)

    def _load_services(self, db_session) -> None:
        db_services = get_services(db_session, active_only=True)
        self.services = {}
        for service in db_services:
            service_name: str = service.name  # type: ignore[assignment]
            self.services[service_name] = {
                "id": service.id,
                "url": service.url,
                "health_check": service.health_check_path,
                "timeout": service.timeout_seconds,
                "rate_limit": service.rate_limit_per_minute,
                "display_name": service.display_name,
                "description": service.description,
                "service_metadata": service.service_metadata,
            }

    async def initialize(self, db_session=None) -> None:
        """Initialize service registry from database"""
        try:
            if db_session is not None:
                self._load_services(db_session)
            else:
                with SessionLocal() as session:
                    self._load_services(session)
            logger.info("Loaded services from database", count=len(self.services))
        except Exception as e:
            logger.error(
                "Failed to initialize service registry from database", error=str(e)
            )
            self.services = {}

    async def cleanup(self) -> None:
        """Cleanup resources"""
        await self.http_client.aclose()

    def get_service(self, service_name: str) -> Optional[Dict[str, Any]]:
        """Get service configuration by name"""
        return self.services.get(service_name)

    def list_services(self) -> Dict[str, Dict[str, Any]]:
        """List all registered services"""
        return self.services.copy()

    async def add_service(self, name: str, config: Dict[str, Any]) -> bool:
        """Add a new service to the registry"""
        try:
            # Validate service configuration
            required_fields = ["url"]
            for field in required_fields:
                if field not in config:
                    logger.error(f"Missing required field: {field}")
                    return False

            self.services[name] = config
            logger.info("Service added to registry", service_name=name)
            return True
        except Exception as e:
            logger.error("Failed to add service", service_name=name, error=str(e))
            return False

    async def remove_service(self, name: str) -> bool:
        """Remove a service from the registry"""
        if name in self.services:
            del self.services[name]
            logger.info("Service removed from registry", service_name=name)
            return True
        return False

    async def reload(self, db_session=None) -> None:
        """Reload services from database

        Args:
            db_session: Optional database session. If not provided, creates a new one.
        """
        await self.initialize(db_session=db_session)
        logger.info("Service registry reloaded from database")

    async def health_check(self, service_name: str) -> bool:
        """Check health of a service and update database"""
        service = self.get_service(service_name)
        if not service:
            return False

        try:
            health_url = f"{service['url']}{service.get('health_check', '/health')}"
            response = await self.http_client.get(health_url)
            is_healthy = bool(response.status_code == 200)

            # Update health status in database
            with SessionLocal() as db:
                health_status = "healthy" if is_healthy else "unhealthy"
                update_service_health(db, service["id"], health_status)

            logger.info(
                "Health check completed",
                service_name=service_name,
                status=health_status,
            )

            return is_healthy
        except Exception as e:
            logger.error("Health check failed", service_name=service_name, error=str(e))

            # Update health status as unhealthy in database
            try:
                with SessionLocal() as db:
                    update_service_health(db, service["id"], "unhealthy")
            except Exception:
                pass

            return False


class ServiceProxy:
    """Proxy for forwarding requests to backend services"""

    def __init__(self, service_registry: ServiceRegistry) -> None:
        self.service_registry = service_registry
        self.http_client = httpx.AsyncClient(timeout=30.0)

    async def forward_request(
        self,
        service_name: str,
        method: str,
        path: str,
        headers: Dict[str, str],
        body: Optional[bytes] = None,
        params: Optional[Dict[str, str]] = None,
    ) -> httpx.Response:
        """Forward request to backend service"""
        service = self.service_registry.get_service(service_name)
        if not service:
            raise ValueError(f"Service '{service_name}' not found")

        # Build target URL
        target_url = f"{service['url']}{path}"

        # Prepare headers (remove host header to avoid conflicts)
        forward_headers = {k: v for k, v in headers.items() if k.lower() != "host"}

        try:
            # Forward request
            response = await self.http_client.request(
                method=method,
                url=target_url,
                headers=forward_headers,
                content=body,
                params=params,
                timeout=service.get("timeout", 30),
            )

            logger.info(
                "Request forwarded",
                service_name=service_name,
                method=method,
                path=path,
                status_code=response.status_code,
            )

            return response

        except Exception as e:
            logger.error(
                "Request forwarding failed",
                service_name=service_name,
                method=method,
                path=path,
                error=str(e),
            )
            raise

    async def cleanup(self) -> None:
        """Cleanup resources"""
        await self.http_client.aclose()
