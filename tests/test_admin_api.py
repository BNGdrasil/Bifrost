# --------------------------------------------------------------------------
# Tests for admin endpoints that used to return sample data (UI-01)
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import pytest
from httpx import AsyncClient

ADMIN_HEADERS = {"Authorization": "Bearer admin-token"}


class TestUnimplementedWrites:
    """Unimplemented writes must never report success.

    User creation, update, activation and deletion are proxied to the auth
    server and covered by tests/test_admin_users_proxy.py.
    """

    @pytest.mark.asyncio
    async def test_reset_password_is_not_implemented(
        self, client: AsyncClient, mock_auth_admin
    ):
        response = await client.post(
            "/admin/api/users/5/reset-password", headers=ADMIN_HEADERS
        )
        assert response.status_code == 501

    @pytest.mark.asyncio
    async def test_settings_update_is_not_implemented(
        self, client: AsyncClient, mock_auth_super_admin
    ):
        response = await client.put(
            "/admin/api/settings/",
            json={"maintenance_mode": True},
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 501

    @pytest.mark.asyncio
    async def test_log_search_is_not_implemented(
        self, client: AsyncClient, mock_auth_admin
    ):
        response = await client.get("/admin/api/logs/", headers=ADMIN_HEADERS)
        assert response.status_code == 501

    @pytest.mark.asyncio
    async def test_audit_logs_are_not_implemented(
        self, client: AsyncClient, mock_auth_admin
    ):
        response = await client.get("/admin/api/logs/audit", headers=ADMIN_HEADERS)
        assert response.status_code == 501


class TestRealStatistics:
    """Statistics must be computed, not fabricated"""

    @pytest.mark.asyncio
    async def test_settings_reports_effective_configuration(
        self, client: AsyncClient, mock_auth_admin
    ):
        from src.core.config import settings

        response = await client.get("/admin/api/settings/", headers=ADMIN_HEADERS)
        assert response.status_code == 200
        body = response.json()["settings"]
        assert body["rate_limit_per_minute"] == settings.RATE_LIMIT_PER_MINUTE
        assert body["environment"] == settings.ENVIRONMENT
        assert body["editable_at_runtime"] is False

    @pytest.mark.asyncio
    async def test_stats_overview_uses_real_values(
        self, client: AsyncClient, mock_auth_admin
    ):
        response = await client.get(
            "/admin/api/settings/stats/overview", headers=ADMIN_HEADERS
        )
        assert response.status_code == 200
        body = response.json()

        assert body["services"]["total"] >= 3
        assert body["services"]["active"] >= 3
        assert body["registry"]["ready"] is True
        assert body["registry"]["loaded_services"] >= 3

        # Values Bifrost cannot compute must be null instead of a fake zero.
        assert body["users"] is None
        assert body["api_requests"] is None
        assert body["system"] is None

    @pytest.mark.asyncio
    async def test_service_stats_endpoint(self, client: AsyncClient, mock_auth_admin):
        response = await client.get("/admin/api/services/stats", headers=ADMIN_HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert body["total_services"] >= body["active_services"] >= 3


class TestRegistryReloadFailureIsReported:
    """A write that lands in the database but not in the routing table.

    reload_registry used to log the failure and return, so the handler still
    answered 200 or 201 with an ordinary body. The caller then believed the
    gateway was routing to a service it had never loaded. The write now
    reports the reload outcome in the body and answers 207.
    """

    @staticmethod
    def _break_reload(app) -> None:
        registry = app.state.service_registry

        def broken_loader(*args, **kwargs):
            raise RuntimeError("database unavailable")

        registry._build_snapshot = broken_loader
        registry._load_snapshot_sync = broken_loader

    @pytest.mark.asyncio
    async def test_create_reports_a_failed_reload(
        self, app, client: AsyncClient, mock_auth_admin
    ):
        import uuid

        self._break_reload(app)
        name = f"reload-fail-{uuid.uuid4().hex[:6]}"

        response = await client.post(
            "/admin/api/services",
            json={"name": name, "url": "http://reload-fail:8080"},
            headers=ADMIN_HEADERS,
        )

        assert response.status_code == 207
        body = response.json()
        # The record was stored, so it is returned in full.
        assert body["name"] == name
        assert body["id"]
        assert body["registry_reloaded"] is False
        assert "database unavailable" in body["registry_error"]
        # The routing table still holds the previous snapshot.
        assert app.state.service_registry.get_service(name) is None

    @pytest.mark.asyncio
    async def test_update_reports_a_failed_reload(
        self, app, client: AsyncClient, mock_auth_admin
    ):
        import uuid

        name = f"reload-update-{uuid.uuid4().hex[:6]}"
        created = await client.post(
            "/admin/api/services",
            json={"name": name, "url": "http://reload-update:8080"},
            headers=ADMIN_HEADERS,
        )
        assert created.status_code == 201
        assert created.json()["registry_reloaded"] is True

        self._break_reload(app)
        response = await client.put(
            f"/admin/api/services/{created.json()['id']}",
            json={"display_name": "Renamed"},
            headers=ADMIN_HEADERS,
        )

        assert response.status_code == 207
        body = response.json()
        assert body["display_name"] == "Renamed"
        assert body["registry_reloaded"] is False
        assert "database unavailable" in body["registry_error"]

    @pytest.mark.asyncio
    async def test_delete_reports_a_failed_reload(
        self, app, client: AsyncClient, mock_auth_admin
    ):
        import uuid

        from src.core.database import SessionLocal
        from src.crud.service import get_service_by_name

        name = f"reload-delete-{uuid.uuid4().hex[:6]}"
        created = await client.post(
            "/admin/api/services",
            json={"name": name, "url": "http://reload-delete:8080"},
            headers=ADMIN_HEADERS,
        )
        assert created.status_code == 201
        service_id = created.json()["id"]

        self._break_reload(app)
        response = await client.delete(
            f"/admin/api/services/{service_id}", headers=ADMIN_HEADERS
        )

        assert response.status_code == 207
        body = response.json()
        assert body["service_id"] == service_id
        assert body["service_name"] == name
        assert body["registry_reloaded"] is False
        assert "database unavailable" in body["registry_error"]

        # The row is gone even though the routing table still carries it.
        with SessionLocal() as session:
            assert get_service_by_name(session, name) is None
        assert app.state.service_registry.get_service(name) is not None

    @pytest.mark.asyncio
    async def test_a_successful_write_stays_on_its_usual_status(
        self, app, client: AsyncClient, mock_auth_admin
    ):
        import uuid

        name = f"reload-ok-{uuid.uuid4().hex[:6]}"
        created = await client.post(
            "/admin/api/services",
            json={"name": name, "url": "http://reload-ok:8080"},
            headers=ADMIN_HEADERS,
        )
        assert created.status_code == 201
        assert created.json()["registry_reloaded"] is True
        assert created.json()["registry_error"] is None
        assert app.state.service_registry.get_service(name) is not None

        deleted = await client.delete(
            f"/admin/api/services/{created.json()['id']}", headers=ADMIN_HEADERS
        )
        assert deleted.status_code == 200
        assert deleted.json()["registry_reloaded"] is True
