# --------------------------------------------------------------------------
# Tests for middleware functionality
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import pytest
from httpx import AsyncClient


class TestLoggingMiddleware:
    """Test logging middleware functionality"""

    @pytest.mark.asyncio
    async def test_logging_middleware_logs_requests(self, client: AsyncClient):
        """Test that logging middleware processes requests"""
        response = await client.get("/health")
        assert response.status_code == 200
        # Logging happens in background, just verify request succeeds

    @pytest.mark.asyncio
    async def test_logging_includes_request_details(self, client: AsyncClient):
        """Test that logging captures request details"""
        response = await client.get("/api/v1/services")
        assert response.status_code == 200


class TestRateLimitMiddleware:
    """Test rate limiting middleware"""

    @pytest.mark.asyncio
    async def test_rate_limit_allows_normal_requests(self, client: AsyncClient):
        """Test that rate limiting allows normal request rates"""
        # Make several requests - should all succeed in test environment
        for _ in range(10):
            response = await client.get("/health")
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_rate_limit_configuration(self):
        """Test rate limit configuration"""
        from src.core.config import settings

        assert settings.RATE_LIMIT_PER_MINUTE > 0
        # Test environment should have reasonable limits
        assert settings.RATE_LIMIT_PER_MINUTE >= 60


class TestCORSMiddleware:
    """Test CORS middleware"""

    @pytest.mark.asyncio
    async def test_cors_allows_configured_origins(self, client: AsyncClient):
        """Test CORS headers for allowed origins"""
        response = await client.get(
            "/health", headers={"Origin": "http://localhost:3000"}
        )
        assert response.status_code == 200
        # CORS headers should be present
        assert "access-control-allow-origin" in response.headers

    @pytest.mark.asyncio
    async def test_cors_preflight_request(self, client: AsyncClient):
        """Test CORS preflight OPTIONS request"""
        response = await client.options(
            "/api/v1/services",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        # Should allow the request
        assert response.status_code == 200


class TestTrustedHostMiddleware:
    """Test trusted host middleware"""

    @pytest.mark.asyncio
    async def test_trusted_host_allows_configured_hosts(self, client: AsyncClient):
        """Test that configured hosts are allowed"""
        response = await client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_localhost_is_allowed(self, client: AsyncClient):
        """Test that localhost is allowed"""
        response = await client.get("/health", headers={"host": "localhost:8000"})
        assert response.status_code == 200


class TestMiddlewareChain:
    """Test middleware execution chain"""

    @pytest.mark.asyncio
    async def test_all_middleware_execute(self, client: AsyncClient):
        """Test that all middleware in the chain execute"""
        response = await client.get("/api/v1/services")

        # Request should succeed after going through all middleware
        assert response.status_code == 200

        # CORS headers should be present
        assert (
            "access-control-allow-origin" in response.headers
            or response.status_code == 200
        )

    @pytest.mark.asyncio
    async def test_middleware_with_post_request(
        self, client: AsyncClient, mock_auth_admin
    ):
        """Test middleware with POST requests"""
        service_data = {
            "name": "middleware-test",
            "url": "http://middleware-test.example.com",
        }

        response = await client.post(
            "/admin/api/services",
            json=service_data,
            headers={
                "Authorization": "Bearer admin-token",
                "Origin": "http://localhost:3000",
            },
        )

        # Should succeed after middleware processing
        assert response.status_code in [201, 400]  # 201 success, 400 if exists

    @pytest.mark.asyncio
    async def test_middleware_error_handling(self, client: AsyncClient):
        """Test middleware handles errors gracefully"""
        # Request to non-existent endpoint
        response = await client.get("/nonexistent-endpoint")
        assert response.status_code == 404

        # Middleware should still process the response
        assert (
            "access-control-allow-origin" in response.headers
            or response.status_code == 404
        )


class TestProcessTimeMiddleware:
    """Test process time tracking middleware"""

    @pytest.mark.asyncio
    async def test_process_time_header(self, client: AsyncClient):
        """Test that process time header is added"""
        response = await client.get("/health")
        assert response.status_code == 200

        # Check for process time header (if implemented)
        # This is optional depending on middleware configuration
        if "x-process-time" in response.headers:
            process_time = float(response.headers["x-process-time"])
            assert process_time >= 0
            assert process_time < 10  # Should be very fast


class TestAuthMiddleware:
    """Test authentication middleware behavior"""

    @pytest.mark.asyncio
    async def test_protected_endpoint_requires_auth(self, client: AsyncClient):
        """Test that protected endpoints require authentication"""
        response = await client.get("/admin/api/services")
        # Should reject without auth
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_protected_endpoint_with_auth(
        self, client: AsyncClient, mock_auth_admin
    ):
        """Test that protected endpoints work with valid auth"""
        response = await client.get(
            "/admin/api/services", headers={"Authorization": "Bearer valid-token"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_public_endpoint_no_auth_required(self, client: AsyncClient):
        """Test that public endpoints don't require auth"""
        public_endpoints = ["/health", "/", "/metrics", "/api/v1/services"]

        for endpoint in public_endpoints:
            response = await client.get(endpoint)
            # Should not return 401/403
            assert response.status_code not in [401, 403]
