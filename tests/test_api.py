# --------------------------------------------------------------------------
# Tests for API Gateway functionality
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import json
from unittest.mock import Mock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from src.services.services import ServiceRegistry


@pytest.fixture
def test_app():
    """Create test app using real app factory but without lifespan for testing"""
    import os
    import tempfile
    from unittest.mock import patch

    # Create temporary config for testing
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        test_services_config = {
            "test-service": {
                "url": "http://test-service.example.com",
                "health_check": "/health",
                "timeout": 30,
                "rate_limit": 100,
            }
        }
        f.write(json.dumps(test_services_config))
        temp_config_path = f.name

    # Patch settings for test
    with patch("src.core.config.settings") as mock_settings:
        mock_settings.ENVIRONMENT = "test"
        mock_settings.ALLOWED_ORIGINS = ["*"]
        mock_settings.ALLOWED_HOSTS = ["*"]
        mock_settings.SERVICES_CONFIG_PATH = temp_config_path

        # Create app without lifespan for testing
        from src.main import create_app

        app = create_app()
        app.router.lifespan_context = None  # type: ignore

        # Initialize service registry manually
        from src.services.services import ServiceRegistry

        app.state.service_registry = ServiceRegistry()

        yield app

    # Cleanup
    os.unlink(temp_config_path)


@pytest.fixture
def initialized_test_app(test_app):
    """Initialized test app with service registry"""
    import asyncio

    # Initialize service registry synchronously for testing
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.run_until_complete(test_app.state.service_registry.initialize())

    yield test_app

    loop.run_until_complete(test_app.state.service_registry.cleanup())
    loop.close()


@pytest.fixture
def test_client(test_app):
    """Create test client"""
    return TestClient(test_app)


@pytest.fixture
def mock_service_registry():
    """Mock service registry"""
    registry = Mock(spec=ServiceRegistry)
    registry.services = {
        "test-service": {
            "url": "http://test-service.example.com",
            "health_check": "/health",
            "timeout": 30,
            "rate_limit": 100,
        }
    }
    return registry


class TestHealthEndpoint:
    """Test health check endpoint"""

    def test_health_check(self, test_client):
        """Test health check returns correct response"""
        response = test_client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy", "service": "bifrost"}


class TestRootEndpoint:
    """Test root endpoint"""

    def test_root_endpoint(self, test_client):
        """Test root endpoint returns welcome message"""
        response = test_client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "Welcome to Bifrost API Gateway" in data["message"]
        assert "version" in data


class TestMetricsEndpoint:
    """Test metrics endpoint"""

    def test_metrics_endpoint(self, test_client):
        """Test metrics endpoint returns prometheus format"""
        response = test_client.get("/metrics")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
        # Check if prometheus metrics format is present
        assert "# HELP" in response.text or "# TYPE" in response.text


class TestServiceRegistry:
    """Test service registry functionality"""

    @pytest.mark.asyncio
    async def test_service_registry_initialization(self):
        """Test service registry initialization with default services"""
        registry = ServiceRegistry()
        await registry.initialize()

        # Should have default services
        services = registry.list_services()
        assert "qshing-server" in services
        assert "hello" in services

        await registry.cleanup()

    @pytest.mark.asyncio
    async def test_add_service(self):
        """Test adding a new service"""
        registry = ServiceRegistry()
        await registry.initialize()

        success = await registry.add_service(
            "new-service",
            {
                "url": "http://new-service.example.com",
                "health_check": "/health",
                "timeout": 30,
            },
        )

        assert success is True
        assert "new-service" in registry.services

        await registry.cleanup()

    @pytest.mark.asyncio
    async def test_add_service_missing_url(self):
        """Test adding service without required URL field"""
        registry = ServiceRegistry()
        await registry.initialize()

        success = await registry.add_service("bad-service", {})
        assert success is False

        await registry.cleanup()

    @pytest.mark.asyncio
    async def test_remove_service(self):
        """Test removing a service"""
        registry = ServiceRegistry()
        await registry.initialize()

        # Add service first
        await registry.add_service("temp-service", {"url": "http://temp.example.com"})
        assert "temp-service" in registry.services

        # Remove service
        success = await registry.remove_service("temp-service")
        assert success is True
        assert "temp-service" not in registry.services

        await registry.cleanup()

    @pytest.mark.asyncio
    async def test_remove_nonexistent_service(self):
        """Test removing a service that doesn't exist"""
        registry = ServiceRegistry()
        await registry.initialize()

        success = await registry.remove_service("nonexistent-service")
        assert success is False

        await registry.cleanup()

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """Test health check for healthy service"""
        registry = ServiceRegistry()
        await registry.initialize()

        # Mock successful health check
        with patch.object(registry.http_client, "get") as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response

            is_healthy = await registry.health_check("qshing-server")
            assert is_healthy is True

        await registry.cleanup()

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        """Test health check for unhealthy service"""
        registry = ServiceRegistry()
        await registry.initialize()

        # Mock failed health check
        with patch.object(registry.http_client, "get") as mock_get:
            mock_response = Mock()
            mock_response.status_code = 500
            mock_get.return_value = mock_response

            is_healthy = await registry.health_check("qshing-server")
            assert is_healthy is False

        await registry.cleanup()

    @pytest.mark.asyncio
    async def test_health_check_nonexistent_service(self):
        """Test health check for nonexistent service"""
        registry = ServiceRegistry()
        await registry.initialize()

        is_healthy = await registry.health_check("nonexistent-service")
        assert is_healthy is False

        await registry.cleanup()


class TestServiceProxy:
    """Test service proxy functionality"""

    @pytest.mark.asyncio
    async def test_forward_request_success(self):
        """Test successful request forwarding"""
        from src.services.services import ServiceProxy

        registry = Mock(spec=ServiceRegistry)
        registry.get_service.return_value = {
            "url": "http://test-service.example.com",
            "timeout": 30,
        }

        proxy = ServiceProxy(registry)

        # Mock successful response
        with patch.object(proxy.http_client, "request") as mock_request:
            mock_response = Mock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.content = b'{"result": "success"}'
            mock_response.headers = {"content-type": "application/json"}
            mock_request.return_value = mock_response

            response = await proxy.forward_request(
                service_name="test-service",
                method="GET",
                path="/api/test",
                headers={"user-agent": "test"},
                params={"param": "value"},
            )

            assert response.status_code == 200
            mock_request.assert_called_once()

        await proxy.cleanup()

    @pytest.mark.asyncio
    async def test_forward_request_service_not_found(self):
        """Test request forwarding to nonexistent service"""
        from src.services.services import ServiceProxy

        registry = Mock(spec=ServiceRegistry)
        registry.get_service.return_value = None

        proxy = ServiceProxy(registry)

        with pytest.raises(ValueError, match="Service 'nonexistent' not found"):
            await proxy.forward_request(
                service_name="nonexistent",
                method="GET",
                path="/api/test",
                headers={},
            )

        await proxy.cleanup()


class TestAPIRoutes:
    """Test API Gateway routes using real service registry"""

    def test_list_services_endpoint(self, initialized_test_app):
        """Test listing services endpoint with real service registry"""
        client = TestClient(initialized_test_app)
        response = client.get("/api/v1/services")

        assert response.status_code == 200
        data = response.json()
        assert "services" in data
        assert "count" in data
        assert data["count"] >= 1  # Should have default services or loaded services

        # Check that we have some expected default services
        services = data["services"]
        assert isinstance(services, dict)
        # Default services should include 'qshing-server' and 'hello'
        assert any(
            service in ["qshing-server", "hello", "test-service"]
            for service in services.keys()
        )

    def test_service_health_endpoint(self, initialized_test_app):
        """Test service health check endpoint"""
        client = TestClient(initialized_test_app)

        # Use a service that exists in the registry (qshing-server or hello)
        # Mock the HTTP call to external service for health check
        with patch("src.services.services.httpx.AsyncClient.get") as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response

            response = client.get("/api/v1/services/qshing-server/health")
            assert response.status_code == 200
            data = response.json()
            assert data["service"] == "qshing-server"
            assert data["healthy"] is True

    def test_service_registry_functionality(self, initialized_test_app):
        """Test service registry basic functionality"""
        # Test that we can get the service registry and it works
        registry = initialized_test_app.state.service_registry
        assert registry is not None

        # Test list services works
        services = registry.list_services()
        assert isinstance(services, dict)
        assert len(services) >= 0

        # Test adding a service directly
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        success = loop.run_until_complete(
            registry.add_service(
                "test-direct-service",
                {"url": "http://test-direct.example.com", "health_check": "/health"},
            )
        )
        assert success is True

        # Verify it was added
        updated_services = registry.list_services()
        assert "test-direct-service" in updated_services

        # Clean up
        loop.run_until_complete(registry.remove_service("test-direct-service"))
        loop.close()

    def test_add_service_missing_name(self, initialized_test_app):
        """Test add service endpoint with missing name"""
        client = TestClient(initialized_test_app)
        service_data = {"config": {"url": "http://test.example.com"}}

        response = client.post("/api/v1/admin/services", json=service_data)
        assert response.status_code == 400
        assert "Service name is required" in response.json()["detail"]

    def test_remove_service_endpoint(self, initialized_test_app):
        """Test remove service endpoint"""
        client = TestClient(initialized_test_app)

        # First add a service to remove
        add_data = {
            "name": "temp-service-to-remove",
            "config": {"url": "http://temp.example.com", "health_check": "/health"},
        }
        add_response = client.post("/api/v1/admin/services", json=add_data)
        assert add_response.status_code == 200

        # Now remove it
        response = client.delete("/api/v1/admin/services/temp-service-to-remove")
        assert response.status_code == 200
        data = response.json()
        assert "temp-service-to-remove" in data["message"]

        # Verify service was actually removed
        services_response = client.get("/api/v1/services")
        services_data = services_response.json()
        assert "temp-service-to-remove" not in services_data["services"]

    def test_remove_nonexistent_service(self, initialized_test_app):
        """Test removing nonexistent service"""
        client = TestClient(initialized_test_app)
        response = client.delete("/api/v1/admin/services/nonexistent")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]


class TestMiddleware:
    """Test middleware functionality"""

    def test_logging_middleware_logs_requests(self, test_client):
        """Test that logging middleware logs requests"""
        with patch("src.core.middleware.logger") as mock_logger:
            response = test_client.get("/health")
            assert response.status_code == 200

            # Verify logging was called
            assert mock_logger.info.call_count >= 2  # Request start and completion

    def test_rate_limit_middleware_allows_normal_requests(self, test_client):
        """Test that rate limiting allows normal request rates"""
        # Make a few requests - should all succeed
        for _ in range(5):
            response = test_client.get("/health")
            assert response.status_code == 200

    def test_rate_limit_middleware_blocks_excessive_requests(self, test_client):
        """Test that rate limiting blocks excessive requests"""
        from src.core.middleware import RateLimitMiddleware

        # Patch the rate limit check to simulate exceeded limit
        with patch.object(RateLimitMiddleware, "_check_rate_limit", return_value=False):
            response = test_client.get("/health")
            assert response.status_code == 429
            assert "Rate limit exceeded" in response.text


class TestConfiguration:
    """Test configuration management"""

    def test_settings_default_values(self):
        """Test that settings have expected default values"""
        from src.core.config import settings

        assert settings.PROJECT_NAME == "bifrost"
        assert settings.ENVIRONMENT in ["development", "production", "test"]
        assert settings.HOST == "0.0.0.0"
        assert settings.PORT == 8000
        assert settings.RATE_LIMIT_PER_MINUTE == 60

    def test_settings_env_override(self):
        """Test that environment variables override defaults"""
        import os

        from src.core.config import Settings

        # Set environment variable
        os.environ["PORT"] = "9000"

        # Create new settings instance
        test_settings = Settings()
        assert test_settings.PORT == 9000

        # Clean up
        del os.environ["PORT"]
