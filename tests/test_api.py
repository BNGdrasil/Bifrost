# --------------------------------------------------------------------------
# Tests for API Gateway functionality
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from src.crud.service import create_service, get_service_by_name, get_services
from src.schemas.service import ServiceCreate


class TestBasicEndpoints:
    """Test basic application endpoints"""

    @pytest.mark.asyncio
    async def test_health_check(self, client: AsyncClient):
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy", "service": "bifrost"}

    @pytest.mark.asyncio
    async def test_root_endpoint(self, client: AsyncClient):
        """Test root endpoint"""
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "Welcome to Bifrost API Gateway" in data["message"]
        assert "version" in data

    @pytest.mark.asyncio
    async def test_metrics_endpoint(self, client: AsyncClient):
        """Test Prometheus metrics endpoint"""
        response = await client.get("/metrics")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; charset=utf-8"


class TestServiceCRUD:
    """Test service CRUD operations"""

    def test_get_services_from_db(self, db_session: Session):
        """Test getting services from database"""
        services = get_services(db_session, active_only=True)
        assert isinstance(services, list)
        assert len(services) >= 3  # Test data has 3 services

        service_names = [s.name for s in services]
        assert "qshing-server" in service_names
        assert "hello" in service_names

    def test_create_and_get_service(self, db_session: Session):
        """Test creating and retrieving a service"""
        unique_name = f"test-service-{uuid.uuid4().hex[:8]}"
        service_data = ServiceCreate(
            name=unique_name,
            url="http://test.example.com",
            display_name="Test Service",
        )
        created = create_service(db_session, service_data)
        assert created.id is not None
        assert created.name == unique_name

        found = get_service_by_name(db_session, unique_name)
        assert found is not None
        assert found.id == created.id


class TestAdminAPI:
    """Test admin API endpoints"""

    @pytest.mark.asyncio
    async def test_list_services(self, client: AsyncClient, mock_auth_admin):
        """Test admin list services endpoint"""
        response = await client.get(
            "/admin/api/services", headers={"Authorization": "Bearer admin-token"}
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_create_service_via_api(self, client: AsyncClient, mock_auth_admin):
        """Test creating service via API"""
        unique_name = f"api-test-service-{uuid.uuid4().hex[:6]}"
        service_data = {
            "name": unique_name,
            "url": "http://api-test.example.com",
            "display_name": "API Test Service",
        }

        response = await client.post(
            "/admin/api/services",
            json=service_data,
            headers={"Authorization": "Bearer admin-token"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == unique_name


class TestPublicAPI:
    """Test public API endpoints"""

    @pytest.mark.asyncio
    async def test_list_services_public(self, client: AsyncClient):
        """Test public service listing"""
        response = await client.get("/api/v1/services")
        assert response.status_code == 200
        data = response.json()
        assert "services" in data
        assert "count" in data
        assert data["count"] >= 3
