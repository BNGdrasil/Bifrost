# --------------------------------------------------------------------------
# Integration tests for API Gateway
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from src.crud.service import create_service, get_service_by_name
from src.schemas.service import ServiceCreate


@pytest.mark.integration
class TestServiceLifecycle:
    """Test complete service lifecycle"""

    @pytest.mark.asyncio
    async def test_end_to_end_service_management(
        self, db_session: Session, client: AsyncClient, mock_auth_admin
    ):
        """Test create, read, update, delete service"""
        unique_name = f"lifecycle-test-{uuid.uuid4().hex[:6]}"
        service_data = {
            "name": unique_name,
            "url": "http://lifecycle.example.com",
            "display_name": "Lifecycle Test",
            "description": "Testing lifecycle",
        }

        # 1. Create
        create_response = await client.post(
            "/admin/api/services",
            json=service_data,
            headers={"Authorization": "Bearer admin-token"},
        )
        assert create_response.status_code == 201
        service_id = create_response.json()["id"]

        # 2. Read
        get_response = await client.get(
            f"/admin/api/services/{service_id}",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert get_response.status_code == 200
        assert get_response.json()["name"] == unique_name

        # 3. Update
        update_response = await client.put(
            f"/admin/api/services/{service_id}",
            json={"display_name": "Updated Lifecycle"},
            headers={"Authorization": "Bearer admin-token"},
        )
        assert update_response.status_code == 200
        assert update_response.json()["display_name"] == "Updated Lifecycle"

        # 4. Delete
        delete_response = await client.delete(
            f"/admin/api/services/{service_id}",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert delete_response.status_code == 204

        # Verify deletion
        deleted_service = get_service_by_name(db_session, unique_name)
        assert deleted_service is None


@pytest.mark.integration
class TestServiceRegistry:
    """Test service registry functionality"""

    @pytest.mark.asyncio
    async def test_service_registry_with_database(self, db_session: Session):
        """Test that service registry can be populated from database"""
        from src.services.services import ServiceRegistry

        registry = ServiceRegistry()
        await registry.initialize(db_session=db_session)

        # Verify registry
        services = registry.list_services()
        assert len(services) >= 3
        assert "qshing-server" in services
        assert "hello" in services

        await registry.cleanup()


@pytest.mark.integration
class TestMiddleware:
    """Test middleware integration"""

    @pytest.mark.asyncio
    async def test_cors_middleware(self, client: AsyncClient):
        """Test CORS middleware"""
        response = await client.options(
            "/api/v1/services",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers

    @pytest.mark.asyncio
    async def test_rate_limiting(self, client: AsyncClient):
        """Test rate limiting doesn't block in test environment"""
        responses = []
        for _ in range(10):
            response = await client.get("/health")
            responses.append(response.status_code)

        # All should succeed in test environment
        assert all(status == 200 for status in responses)


@pytest.mark.integration
class TestErrorHandling:
    """Test error handling"""

    @pytest.mark.asyncio
    async def test_service_not_found(self, client: AsyncClient, mock_auth_admin):
        """Test 404 for non-existent service"""
        response = await client.get(
            "/admin/api/services/99999",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_duplicate_service_name(self, client: AsyncClient, mock_auth_admin):
        """Test error when creating duplicate service"""
        unique_name = f"duplicate-test-{uuid.uuid4().hex[:6]}"
        service_data = {
            "name": unique_name,
            "url": "http://duplicate.example.com",
        }

        # First creation should succeed
        response1 = await client.post(
            "/admin/api/services",
            json=service_data,
            headers={"Authorization": "Bearer admin-token"},
        )
        assert response1.status_code == 201

        # Second should fail
        response2 = await client.post(
            "/admin/api/services",
            json=service_data,
            headers={"Authorization": "Bearer admin-token"},
        )
        assert response2.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_service_data(self, client: AsyncClient, mock_auth_admin):
        """Test validation error for invalid data"""
        service_data = {
            "name": "invalid-service"
            # Missing required 'url' field
        }

        response = await client.post(
            "/admin/api/services",
            json=service_data,
            headers={"Authorization": "Bearer admin-token"},
        )
        assert response.status_code == 422  # Validation error


@pytest.mark.integration
class TestConcurrency:
    """Test concurrent operations"""

    @pytest.mark.asyncio
    async def test_concurrent_service_creation(
        self, client: AsyncClient, mock_auth_admin
    ):
        """Test creating multiple services concurrently"""
        import asyncio

        async def create_service_task(index: int):
            service_data = {
                "name": f"concurrent-{index}-{uuid.uuid4().hex[:4]}",
                "url": f"http://concurrent-{index}.example.com",
            }
            return await client.post(
                "/admin/api/services",
                json=service_data,
                headers={"Authorization": "Bearer admin-token"},
            )

        # Create 5 services concurrently
        tasks = [create_service_task(i) for i in range(5)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # Most should succeed
        success_count = sum(
            1
            for r in responses
            if not isinstance(r, Exception) and r.status_code == 201
        )
        assert success_count >= 4  # Allow for some failures

    @pytest.mark.asyncio
    async def test_concurrent_reads(self, client: AsyncClient):
        """Test concurrent read operations"""
        import asyncio

        async def read_health():
            return await client.get("/health")

        # Make 20 concurrent requests
        tasks = [read_health() for _ in range(20)]
        responses = await asyncio.gather(*tasks)

        # All should succeed
        assert all(r.status_code == 200 for r in responses)
