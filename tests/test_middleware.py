# --------------------------------------------------------------------------
# Tests for middleware functionality (Fixed version)
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.core.middleware import LoggingMiddleware, RateLimitMiddleware
from src.main import create_app


class TestLoggingMiddleware:
    """Test logging middleware functionality"""

    @pytest.fixture
    def app_with_logging_middleware(self):
        """Create test app with logging middleware"""
        app = FastAPI()
        app.add_middleware(LoggingMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "test"}

        return app

    @pytest.fixture
    def real_app_with_middleware(self):
        """Create app using real app factory"""
        with patch("src.core.config.settings") as mock_settings:
            mock_settings.ENVIRONMENT = "test"
            mock_settings.ALLOWED_ORIGINS = ["*"]
            mock_settings.ALLOWED_HOSTS = ["*"]

            app = create_app()
            app.router.lifespan_context = None  # type: ignore

            # Add a test endpoint
            @app.get("/test-real")
            async def test_real_endpoint():
                return {"message": "real test"}

            return app

    def test_logging_middleware_logs_request_start(self, app_with_logging_middleware):
        """Test that logging middleware logs request start"""
        with patch("src.core.middleware.logger") as mock_logger:
            client = TestClient(app_with_logging_middleware)
            response = client.get("/test")

            assert response.status_code == 200

            # Check that request start was logged
            mock_logger.info.assert_any_call(
                "Request started",
                method="GET",
                url="http://testserver/test",
                client_ip="testclient",
                user_agent="testclient",
            )

    def test_logging_middleware_logs_request_completion(
        self, app_with_logging_middleware
    ):
        """Test that logging middleware logs request completion"""
        with patch("src.core.middleware.logger") as mock_logger:
            client = TestClient(app_with_logging_middleware)
            response = client.get("/test")

            assert response.status_code == 200

            # Check that request completion was logged
            completion_calls = [
                call
                for call in mock_logger.info.call_args_list
                if call[0][0] == "Request completed"
            ]
            assert len(completion_calls) > 0

            # Verify completion log contains required fields
            completion_call = completion_calls[0]
            assert completion_call[1]["method"] == "GET"
            assert completion_call[1]["status_code"] == 200
            assert "duration" in completion_call[1]

    def test_logging_middleware_measures_duration(self, app_with_logging_middleware):
        """Test that logging middleware measures request duration"""
        with patch("src.core.middleware.logger") as mock_logger:
            client = TestClient(app_with_logging_middleware)
            response = client.get("/test")

            assert response.status_code == 200

            # Find completion log call
            completion_calls = [
                call
                for call in mock_logger.info.call_args_list
                if call[0][0] == "Request completed"
            ]
            assert len(completion_calls) > 0

            # Just check that duration exists and is a float
            duration = completion_calls[0][1]["duration"]
            assert isinstance(duration, float)
            assert duration >= 0

    def test_real_app_middleware_integration(self, real_app_with_middleware):
        """Test middleware integration with real app configuration"""
        with patch("src.core.middleware.logger") as mock_logger:
            client = TestClient(real_app_with_middleware)
            response = client.get("/test-real")

            assert response.status_code == 200
            assert response.json() == {"message": "real test"}

            # Verify both logging and rate limiting middleware worked
            assert mock_logger.info.called

            # Check request start log
            start_calls = [
                call
                for call in mock_logger.info.call_args_list
                if call[0][0] == "Request started"
            ]
            assert len(start_calls) > 0

            # Check request completion log
            completion_calls = [
                call
                for call in mock_logger.info.call_args_list
                if call[0][0] == "Request completed"
            ]
            assert len(completion_calls) > 0


class TestRateLimitMiddleware:
    """Test rate limit middleware functionality"""

    @pytest.fixture
    def app_with_rate_limit_middleware(self):
        """Create test app with rate limit middleware"""
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "test"}

        return app

    def test_rate_limit_middleware_allows_normal_requests(
        self, app_with_rate_limit_middleware
    ):
        """Test that rate limit middleware allows normal request rates"""
        client = TestClient(app_with_rate_limit_middleware)

        # Make several requests within limit
        for i in range(5):
            response = client.get("/test")
            assert response.status_code == 200
            assert response.json() == {"message": "test"}

    def test_rate_limit_middleware_blocks_excessive_requests(
        self, app_with_rate_limit_middleware
    ):
        """Test that rate limit middleware blocks excessive requests"""
        with patch("src.core.middleware.time.time", return_value=1000.0):
            client = TestClient(app_with_rate_limit_middleware)

            # Make 61 requests (exceeding limit of 60)
            responses = []
            for i in range(61):
                response = client.get("/test")
                responses.append(response)

            # First 60 should succeed, 61st should be rate limited
            successful_responses = [r for r in responses if r.status_code == 200]
            rate_limited_responses = [r for r in responses if r.status_code == 429]

            assert len(successful_responses) == 60
            assert len(rate_limited_responses) == 1
            assert "Rate limit exceeded" in rate_limited_responses[0].text
