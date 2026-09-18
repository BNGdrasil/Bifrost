# --------------------------------------------------------------------------
# Tests for the gateway trust boundary (SEC-02, GW-04)
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import uuid

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.orm import Session


class TestLegacyRegistryEndpointsRemoved:
    """The unauthenticated in-memory registry API must no longer exist"""

    @pytest.mark.asyncio
    async def test_legacy_add_service_is_gone(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/admin/services",
            json={"name": "audit", "config": {"url": "http://example.invalid"}},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_legacy_delete_service_is_gone(self, client: AsyncClient):
        response = await client.delete("/api/v1/admin/services/audit")
        assert response.status_code == 404

    def test_registry_has_no_direct_mutators(self):
        from src.services.services import ServiceRegistry

        assert not hasattr(ServiceRegistry, "add_service")
        assert not hasattr(ServiceRegistry, "remove_service")


class TestAdminApiRequiresAuthentication:
    """Registry changes are only possible through the authenticated admin API"""

    @pytest.mark.asyncio
    async def test_create_without_token_is_rejected(self, client: AsyncClient):
        response = await client.post(
            "/admin/api/services",
            json={"name": "nope", "url": "http://nope:8080"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_delete_without_token_is_rejected(self, client: AsyncClient):
        response = await client.delete("/admin/api/services/1")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_create_as_regular_user_is_rejected(
        self, client: AsyncClient, mock_auth_forbidden
    ):
        response = await client.post(
            "/admin/api/services",
            json={"name": "nope", "url": "http://nope:8080"},
            headers={"Authorization": "Bearer user-token"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_rejects_denied_destination(
        self, client: AsyncClient, mock_auth_admin
    ):
        response = await client.post(
            "/admin/api/services",
            json={"name": "meta", "url": "http://169.254.169.254"},
            headers={"Authorization": "Bearer admin-token"},
        )
        assert response.status_code == 422


class TestAdminApiUpdatesRegistry:
    """A database change through the admin API must reach the routing table"""

    @pytest.mark.asyncio
    async def test_create_and_delete_round_trip(
        self,
        app: FastAPI,
        client: AsyncClient,
        db_session: Session,
        mock_auth_admin,
    ):
        from src.crud.service import get_service_by_name

        name = f"registry-sync-{uuid.uuid4().hex[:6]}"
        registry = app.state.service_registry
        assert registry.get_service(name) is None

        create = await client.post(
            "/admin/api/services",
            json={"name": name, "url": "http://registry-sync:8080"},
            headers={"Authorization": "Bearer admin-token"},
        )
        assert create.status_code == 201
        service_id = create.json()["id"]

        # The database is the source of truth and the registry follows it.
        assert get_service_by_name(db_session, name) is not None
        assert registry.get_service(name) is not None

        delete = await client.delete(
            f"/admin/api/services/{service_id}",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert delete.status_code == 204
        assert registry.get_service(name) is None

    @pytest.mark.asyncio
    async def test_reload_endpoint_reports_result(
        self, client: AsyncClient, mock_auth_admin
    ):
        response = await client.post(
            "/admin/api/services/reload",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["service_count"] >= 3

    @pytest.mark.asyncio
    async def test_reload_failure_is_reported(
        self, app: FastAPI, client: AsyncClient, mock_auth_admin, monkeypatch
    ):
        from src.services.services import RegistryLoadError

        async def failing_reload(*args, **kwargs):
            raise RegistryLoadError("database is down")

        monkeypatch.setattr(app.state.service_registry, "reload", failing_reload)

        response = await client.post(
            "/admin/api/services/reload",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert response.status_code == 503
        assert "database is down" in response.json()["detail"]


class TestPublicServiceExposure:
    """The public listing must not leak internal routing details"""

    @pytest.mark.asyncio
    async def test_public_list_has_no_internal_fields(self, client: AsyncClient):
        response = await client.get("/api/v1/services")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] >= 3
        assert isinstance(body["services"], list)

        for service in body["services"]:
            assert set(service) == {
                "name",
                "display_name",
                "description",
                "health_status",
                "last_health_check",
            }

    @pytest.mark.asyncio
    async def test_public_health_does_not_probe_upstream(
        self, app: FastAPI, client: AsyncClient, monkeypatch
    ):
        called = []

        async def fail_if_called(*args, **kwargs):
            called.append(args)
            raise AssertionError("public health must not probe the upstream")

        monkeypatch.setattr(app.state.service_registry, "health_check", fail_if_called)

        response = await client.get("/api/v1/services/hello/health")
        assert response.status_code == 200
        assert called == []
        body = response.json()
        assert body["name"] == "hello"
        assert "url" not in body

    @pytest.mark.asyncio
    async def test_public_health_unknown_service(self, client: AsyncClient):
        response = await client.get("/api/v1/services/does-not-exist/health")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_list_still_exposes_url(
        self, client: AsyncClient, mock_auth_admin
    ):
        response = await client.get(
            "/admin/api/services", headers={"Authorization": "Bearer admin-token"}
        )
        assert response.status_code == 200
        assert all("url" in item for item in response.json())
