# --------------------------------------------------------------------------
# Integration tests for API Gateway
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import asyncio
import json
from unittest.mock import Mock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.services.services import ServiceProxy, ServiceRegistry


@pytest.mark.integration
class TestServiceIntegration:
    """Integration tests for service proxy functionality"""

    @pytest.fixture
    def mock_backend_server(self):
        """Mock backend server responses"""

        async def mock_request(*args, **kwargs):
            # Check if this is a health check call
            if len(args) >= 1:
                url = args[0] if isinstance(args[0], str) else kwargs.get("url", "")
            else:
                url = kwargs.get("url", "")

            # Mock different responses based on URL
            if "test-service.example.com/api/users" in url:
                response = Mock(spec=httpx.Response)
                response.status_code = 200
                response.content = json.dumps({"users": ["user1", "user2"]}).encode()
                response.headers = {"content-type": "application/json"}
                return response
            elif "test-service.example.com/health" in url:
                response = Mock(spec=httpx.Response)
                response.status_code = 200
                response.content = json.dumps({"status": "healthy"}).encode()
                response.headers = {"content-type": "application/json"}
                return response
            else:
                response = Mock(spec=httpx.Response)
                response.status_code = 404
                response.content = b"Not Found"
                response.headers = {"content-type": "text/plain"}
                return response

        return mock_request

    @pytest.mark.asyncio
    async def test_end_to_end_service_proxy(self, mock_backend_server):
        """Test end-to-end service proxying"""
        # Initialize service registry
        registry = ServiceRegistry()
        await registry.initialize()

        # Add test service
        await registry.add_service(
            "test-service",
            {
                "url": "http://test-service.example.com",
                "health_check": "/health",
                "timeout": 30,
            },
        )

        # Create service proxy
        proxy = ServiceProxy(registry)

        # Mock HTTP client
        with patch.object(
            proxy.http_client, "request", side_effect=mock_backend_server
        ):
            # Test successful request
            response = await proxy.forward_request(
                service_name="test-service",
                method="GET",
                path="/api/users",
                headers={"accept": "application/json"},
            )

            assert response.status_code == 200
            data = json.loads(response.content.decode())
            assert "users" in data

        await proxy.cleanup()
        await registry.cleanup()

    @pytest.mark.asyncio
    async def test_service_health_check_integration(self, mock_backend_server):
        """Test service health check integration"""
        registry = ServiceRegistry()
        await registry.initialize()

        # Add test service
        await registry.add_service(
            "test-service",
            {
                "url": "http://test-service.example.com",
                "health_check": "/health",
                "timeout": 30,
            },
        )

        # Mock HTTP client for health check
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        with patch.object(registry.http_client, "get", return_value=mock_response):
            is_healthy = await registry.health_check("test-service")
            assert is_healthy is True

        await registry.cleanup()

    def test_full_api_proxy_flow(self, mock_backend_server):
        """Test full API proxy flow through FastAPI"""
        from fastapi import FastAPI

        from src.api.api import router as api_router
        from src.core.middleware import LoggingMiddleware, RateLimitMiddleware

        # Create simple app without lifespan for testing
        app = FastAPI(title="Test API Gateway")
        app.include_router(api_router, prefix="/api/v1")
        app.add_middleware(LoggingMiddleware)
        app.add_middleware(RateLimitMiddleware)

        # Mock service registry
        mock_registry = Mock(spec=ServiceRegistry)
        mock_registry.services = {
            "test-service": {
                "url": "http://test-service.example.com",
                "health_check": "/health",
                "timeout": 30,
            }
        }
        mock_registry.get_service.return_value = mock_registry.services["test-service"]

        # Set up app state
        app.state.service_registry = mock_registry

        # Mock HTTP response
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.content = json.dumps({"users": ["user1", "user2"]}).encode()
        mock_response.headers = {"content-type": "application/json"}

        with TestClient(app) as client:
            # Mock the service proxy's HTTP client
            with patch("httpx.AsyncClient.request", return_value=mock_response):
                response = client.get("/api/v1/test-service/api/users")
                assert response.status_code == 200
                assert "users" in response.json()


@pytest.mark.integration
class TestMiddlewareIntegration:
    """Integration tests for middleware stack"""

    def test_middleware_order_and_execution(self):
        """Test that all middleware executes in correct order"""
        app = create_app()

        with TestClient(app) as client:
            with patch("src.core.middleware.logger") as mock_logger:
                response = client.get("/health")
                assert response.status_code == 200

                # Verify logging middleware executed
                assert mock_logger.info.called

    def test_cors_middleware_integration(self):
        """Test CORS middleware with actual requests"""
        app = create_app()

        with TestClient(app) as client:
            # Test preflight request
            response = client.options(
                "/api/v1/services",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert response.status_code == 200
            assert "access-control-allow-origin" in response.headers

    def test_trusted_host_middleware_integration(self):
        """Test trusted host middleware"""
        app = create_app()

        with TestClient(app) as client:
            # Test with allowed host
            response = client.get("/health", headers={"host": "localhost:8000"})
            assert response.status_code == 200


@pytest.mark.integration
class TestConfigurationIntegration:
    """Integration tests for configuration management"""

    def test_environment_specific_configuration(self):
        """Test environment-specific configuration loading"""
        from src.core.config import Settings

        # Test development environment
        dev_settings = Settings(ENVIRONMENT="development")
        assert dev_settings.DEBUG is False  # Default value

        # Test production environment
        prod_settings = Settings(ENVIRONMENT="production")
        assert prod_settings.ENVIRONMENT == "production"

    def test_cors_origins_parsing(self):
        """Test CORS origins parsing from environment"""
        from src.core.config import Settings

        # Test comma-separated string
        settings = Settings(
            BACKEND_CORS_ORIGINS="http://localhost:3000,http://localhost:3001"
        )
        assert len(settings.BACKEND_CORS_ORIGINS) == 2

    def test_redis_url_configuration(self):
        """Test Redis URL configuration"""
        from src.core.config import settings

        assert settings.REDIS_URL.startswith("redis://")
        assert "redis:6379" in settings.REDIS_URL

    def test_database_url_configuration(self):
        """Test database URL configuration"""
        from src.core.config import settings

        assert settings.DATABASE_URL.startswith("postgresql://")
        assert "postgres:5432" in settings.DATABASE_URL


@pytest.mark.integration
class TestErrorHandling:
    """Integration tests for error handling"""

    def test_service_not_found_error_handling(self):
        """Test error handling when service is not found"""
        app = create_app()

        # Mock empty service registry
        mock_registry = Mock(spec=ServiceRegistry)
        mock_registry.get_service.return_value = None
        app.state.service_registry = mock_registry

        with TestClient(app) as client:
            response = client.get("/api/v1/nonexistent-service/api/test")
            assert response.status_code == 404
            assert "not found" in response.json()["detail"]

    def test_backend_service_error_handling(self):
        """Test error handling when backend service fails"""
        from fastapi import FastAPI

        from src.api.api import router as api_router
        from src.core.middleware import LoggingMiddleware, RateLimitMiddleware

        # Create simple app without lifespan for testing
        app = FastAPI(title="Test API Gateway")
        app.include_router(api_router, prefix="/api/v1")
        app.add_middleware(LoggingMiddleware)
        app.add_middleware(RateLimitMiddleware)

        # Mock service registry with valid service
        mock_registry = Mock(spec=ServiceRegistry)
        mock_registry.get_service.return_value = {
            "url": "http://test-service.example.com",
            "timeout": 30,
        }
        app.state.service_registry = mock_registry

        with TestClient(app) as client:
            # Mock HTTP client to raise exception
            with patch(
                "httpx.AsyncClient.request",
                side_effect=httpx.RequestError("Connection failed"),
            ):
                response = client.get("/api/v1/test-service/api/test")
                assert response.status_code == 500
                assert "Internal server error" in response.json()["detail"]

    def test_invalid_json_request_handling(self):
        """Test handling of invalid JSON in requests"""
        from fastapi import FastAPI

        from src.api.api import router as api_router
        from src.core.middleware import LoggingMiddleware, RateLimitMiddleware
        from src.services.services import ServiceRegistry

        # Create simple app without lifespan for testing
        app = FastAPI(title="Test API Gateway")
        app.include_router(api_router, prefix="/api/v1")
        app.add_middleware(LoggingMiddleware)
        app.add_middleware(RateLimitMiddleware)

        # Initialize empty service registry
        app.state.service_registry = ServiceRegistry()

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/admin/services",
                content="invalid json",
                headers={"content-type": "application/json"},
            )
            assert response.status_code == 422  # Unprocessable Entity


@pytest.mark.integration
class TestPerformanceAndScaling:
    """Integration tests for performance and scaling aspects"""

    @pytest.mark.slow
    def test_concurrent_requests_handling(self):
        """Test handling of concurrent requests"""
        app = create_app()

        async def make_concurrent_requests():
            async with httpx.AsyncClient(app=app, base_url="http://test") as client:
                tasks = []
                for _ in range(10):
                    tasks.append(client.get("/health"))

                responses = await asyncio.gather(*tasks)
                return responses

        responses = asyncio.run(make_concurrent_requests())
        assert len(responses) == 10
        assert all(r.status_code == 200 for r in responses)

    @pytest.mark.slow
    def test_rate_limiting_under_load(self):
        """Test rate limiting behavior under load"""
        app = create_app()

        with TestClient(app) as client:
            # Make many requests to trigger rate limiting
            responses = []
            for _ in range(70):  # Exceed rate limit of 60/minute
                response = client.get("/health")
                responses.append(response)

            # Some requests should be rate limited
            status_codes = [r.status_code for r in responses]
            assert 429 in status_codes  # Rate limit exceeded

    def test_memory_usage_with_service_registry(self):
        """Test memory usage with large service registry"""
        from fastapi import FastAPI

        from src.api.api import router as api_router
        from src.core.middleware import LoggingMiddleware, RateLimitMiddleware

        # Create simple app without lifespan for testing
        app = FastAPI(title="Test API Gateway")
        app.include_router(api_router, prefix="/api/v1")
        app.add_middleware(LoggingMiddleware)
        app.add_middleware(RateLimitMiddleware)

        # Mock large service registry
        mock_registry = Mock(spec=ServiceRegistry)
        large_services = {}
        for i in range(100):
            large_services[f"service-{i}"] = {
                "url": f"http://service-{i}.example.com",
                "health_check": "/health",
                "timeout": 30,
            }

        mock_registry.list_services.return_value = large_services
        app.state.service_registry = mock_registry

        with TestClient(app) as client:
            response = client.get("/api/v1/services")
            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 100


@pytest.mark.integration
class TestMonitoringIntegration:
    """Integration tests for monitoring and metrics"""

    def test_prometheus_metrics_collection(self):
        """Test that Prometheus metrics are collected"""
        app = create_app()

        with TestClient(app) as client:
            # Make some requests to generate metrics
            client.get("/health")
            client.get("/")

            # Check metrics endpoint
            response = client.get("/metrics")
            assert response.status_code == 200

            # Verify metrics format
            metrics_text = response.text
            assert "# HELP" in metrics_text or "# TYPE" in metrics_text

    def test_structured_logging_output(self):
        """Test structured logging output format"""
        import logging
        from io import StringIO

        # Capture log output
        log_capture = StringIO()
        handler = logging.StreamHandler(log_capture)
        logger = logging.getLogger("src")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        app = create_app()
        with TestClient(app) as client:
            client.get("/health")

        # Check log output contains structured data
        log_output = log_capture.getvalue()
        # Note: structlog outputs JSON, so we expect JSON-like structure
        assert "method" in log_output or "status_code" in log_output

        logger.removeHandler(handler)
