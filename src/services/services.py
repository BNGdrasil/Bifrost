# --------------------------------------------------------------------------
# Service registry and proxy functionality for the API Gateway service
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import json
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import structlog

logger = structlog.get_logger()


class ServiceRegistry:
    """Service registry for managing API endpoints"""

    def __init__(self) -> None:
        self.services: Dict[str, Dict[str, Any]] = {}
        self.http_client = httpx.AsyncClient(timeout=30.0)

    async def initialize(self) -> None:
        """Initialize service registry from configuration"""
        try:
            # Load services from JSON config
            config_path = Path("/app/config/services.json")
            if config_path.exists():
                with open(config_path, "r") as f:
                    self.services = json.load(f)
                logger.info(
                    "Loaded services from configuration", count=len(self.services)
                )
            else:
                # Default services for development
                self.services = {
                    "qshing-server": {
                        "url": "https://qshing-server.example.com",
                        "health_check": "/health",
                        "timeout": 30,
                        "rate_limit": 100,
                    },
                    "hello": {
                        "url": "https://hello-service.example.com",
                        "health_check": "/health",
                        "timeout": 30,
                        "rate_limit": 100,
                    },
                }
                logger.info(
                    "Using default services configuration", count=len(self.services)
                )
        except Exception as e:
            logger.error("Failed to initialize service registry", error=str(e))
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

    async def health_check(self, service_name: str) -> bool:
        """Check health of a service"""
        service = self.get_service(service_name)
        if not service:
            return False

        try:
            health_url = f"{service['url']}{service.get('health_check', '/health')}"
            response = await self.http_client.get(health_url)
            return bool(response.status_code == 200)
        except Exception as e:
            logger.error("Health check failed", service_name=service_name, error=str(e))
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
