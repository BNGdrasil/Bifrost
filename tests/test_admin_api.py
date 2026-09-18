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
