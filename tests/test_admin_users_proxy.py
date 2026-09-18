# --------------------------------------------------------------------------
# Tests for the admin user proxy to the Bidar auth server (I07)
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
from typing import Any, Dict, List, Optional

import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from src.core.config import settings

ADMIN_HEADERS = {"Authorization": "Bearer admin-token"}

USER_RECORD: Dict[str, Any] = {
    "id": 7,
    "username": "someone",
    "email": "someone@example.com",
    "full_name": "Some One",
    "is_active": True,
    "is_superuser": False,
    "role": "user",
    "created_at": "2026-09-18T00:00:00Z",
}


class RecordingAuthServer:
    """Stub Bidar auth server built on httpx.MockTransport."""

    def __init__(self, responder) -> None:
        self.calls: List[httpx.Request] = []
        self._responder = responder
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return self._responder(request)

    @property
    def last(self) -> httpx.Request:
        assert self.calls, "the auth server was never called"
        return self.calls[-1]

    def body(self) -> Any:
        import json

        return json.loads(self.last.content.decode())


def install(app: FastAPI, responder) -> RecordingAuthServer:
    """Replace the shared HTTP client with one talking to the stub."""
    server = RecordingAuthServer(responder)
    app.state.http_client = httpx.AsyncClient(transport=server.transport)
    return server


def json_responder(status_code: int, payload: Optional[Any] = None):
    def responder(request: httpx.Request) -> httpx.Response:
        if payload is None:
            return httpx.Response(status_code)
        return httpx.Response(status_code, json=payload)

    return responder


@pytest.fixture(autouse=True)
def _restore_client(app: FastAPI):
    original = app.state.http_client
    yield
    if app.state.http_client is not original:
        app.state.http_client = original


class TestReadProxy:
    """Reads require admin and reach the auth server collection routes"""

    @pytest.mark.asyncio
    async def test_list_users(self, app: FastAPI, client: AsyncClient, mock_auth_admin):
        server = install(app, json_responder(200, [USER_RECORD]))

        response = await client.get("/admin/api/users/", headers=ADMIN_HEADERS)

        assert response.status_code == 200
        assert response.json() == [USER_RECORD]
        assert server.last.method == "GET"
        assert str(server.last.url) == f"{settings.AUTH_SERVER_URL}/users/users"
        assert server.last.headers["authorization"] == "Bearer admin-token"

    @pytest.mark.asyncio
    async def test_list_users_forwards_query_parameters(
        self, app: FastAPI, client: AsyncClient, mock_auth_admin
    ):
        server = install(app, json_responder(200, []))

        response = await client.get(
            "/admin/api/users/?skip=10&limit=5&role=admin&role=user",
            headers=ADMIN_HEADERS,
        )

        assert response.status_code == 200
        assert server.last.url.query.decode() == "skip=10&limit=5&role=admin&role=user"

    @pytest.mark.asyncio
    async def test_get_user(self, app: FastAPI, client: AsyncClient, mock_auth_admin):
        server = install(app, json_responder(200, USER_RECORD))

        response = await client.get("/admin/api/users/7", headers=ADMIN_HEADERS)

        assert response.status_code == 200
        assert response.json() == USER_RECORD
        assert str(server.last.url) == f"{settings.AUTH_SERVER_URL}/users/users/7"

    @pytest.mark.asyncio
    async def test_get_user_not_found_is_passed_through(
        self, app: FastAPI, client: AsyncClient, mock_auth_admin
    ):
        install(app, json_responder(404, {"detail": "User not found"}))

        response = await client.get("/admin/api/users/999", headers=ADMIN_HEADERS)

        assert response.status_code == 404
        assert response.json() == {"detail": "User not found"}

    @pytest.mark.asyncio
    async def test_read_requires_authentication(self, client: AsyncClient):
        assert (await client.get("/admin/api/users/")).status_code == 401

    @pytest.mark.asyncio
    async def test_read_rejects_non_admin(
        self, client: AsyncClient, mock_auth_forbidden
    ):
        response = await client.get(
            "/admin/api/users/", headers={"Authorization": "Bearer user-token"}
        )
        assert response.status_code == 403


class TestCreateProxy:
    """Creation is super admin only and posts to the auth server root"""

    @pytest.mark.asyncio
    async def test_create_user(
        self, app: FastAPI, client: AsyncClient, mock_auth_super_admin
    ):
        server = install(app, json_responder(201, USER_RECORD))

        response = await client.post(
            "/admin/api/users/",
            json={
                "username": "someone",
                "email": "someone@example.com",
                "password": "secret-value",
                "full_name": "Some One",
                "role": "user",
            },
            headers=ADMIN_HEADERS,
        )

        assert response.status_code == 201
        assert response.json() == USER_RECORD
        assert server.last.method == "POST"
        assert str(server.last.url) == f"{settings.AUTH_SERVER_URL}/users"
        assert server.body()["username"] == "someone"
        assert server.body()["password"] == "secret-value"
        assert server.last.headers["authorization"] == "Bearer admin-token"

    @pytest.mark.asyncio
    async def test_duplicate_is_passed_through(
        self, app: FastAPI, client: AsyncClient, mock_auth_super_admin
    ):
        install(app, json_responder(400, {"detail": "Username already registered"}))

        response = await client.post(
            "/admin/api/users/",
            json={
                "username": "dupe",
                "email": "dupe@example.com",
                "password": "secret-value",
            },
            headers=ADMIN_HEADERS,
        )

        assert response.status_code == 400
        assert response.json() == {"detail": "Username already registered"}

    @pytest.mark.asyncio
    async def test_auth_server_validation_error_is_passed_through(
        self, app: FastAPI, client: AsyncClient, mock_auth_super_admin
    ):
        detail = [{"loc": ["body", "email"], "msg": "invalid", "type": "value_error"}]
        install(app, json_responder(422, {"detail": detail}))

        response = await client.post(
            "/admin/api/users/",
            json={
                "username": "bad",
                "email": "not-an-email",
                "password": "secret-value",
            },
            headers=ADMIN_HEADERS,
        )

        assert response.status_code == 422
        assert response.json() == {"detail": detail}

    @pytest.mark.asyncio
    async def test_create_requires_super_admin(
        self, client: AsyncClient, mock_auth_forbidden
    ):
        response = await client.post(
            "/admin/api/users/",
            json={
                "username": "x",
                "email": "x@example.com",
                "password": "secret-value",
            },
            headers={"Authorization": "Bearer admin-token"},
        )
        assert response.status_code == 403
        assert mock_auth_forbidden.await_args.args[1] == "super_admin"


class TestUpdateProxy:
    """Partial updates and activation toggles"""

    @pytest.mark.asyncio
    async def test_patch_user(
        self, app: FastAPI, client: AsyncClient, mock_auth_super_admin
    ):
        server = install(app, json_responder(200, USER_RECORD))

        response = await client.patch(
            "/admin/api/users/7",
            json={"role": "admin"},
            headers=ADMIN_HEADERS,
        )

        assert response.status_code == 200
        assert server.last.method == "PATCH"
        assert str(server.last.url) == f"{settings.AUTH_SERVER_URL}/users/users/7"
        # Only the supplied fields are forwarded.
        assert server.body() == {"role": "admin"}

    @pytest.mark.asyncio
    async def test_patch_last_super_admin_conflict_is_passed_through(
        self, app: FastAPI, client: AsyncClient, mock_auth_super_admin
    ):
        install(app, json_responder(409, {"detail": "Cannot demote the last admin"}))

        response = await client.patch(
            "/admin/api/users/7", json={"role": "user"}, headers=ADMIN_HEADERS
        )

        assert response.status_code == 409
        assert response.json() == {"detail": "Cannot demote the last admin"}

    @pytest.mark.asyncio
    async def test_activate_user(
        self, app: FastAPI, client: AsyncClient, mock_auth_admin
    ):
        server = install(app, json_responder(200, {"message": "User activated"}))

        response = await client.put(
            "/admin/api/users/7/activate", headers=ADMIN_HEADERS
        )

        assert response.status_code == 200
        assert response.json() == {"message": "User activated"}
        assert server.last.method == "PUT"
        assert (
            str(server.last.url) == f"{settings.AUTH_SERVER_URL}/users/users/7/activate"
        )

    @pytest.mark.asyncio
    async def test_deactivate_user(
        self, app: FastAPI, client: AsyncClient, mock_auth_admin
    ):
        server = install(app, json_responder(200, {"message": "User deactivated"}))

        response = await client.put(
            "/admin/api/users/7/deactivate", headers=ADMIN_HEADERS
        )

        assert response.status_code == 200
        assert (
            str(server.last.url)
            == f"{settings.AUTH_SERVER_URL}/users/users/7/deactivate"
        )

    @pytest.mark.asyncio
    async def test_deactivate_conflict_is_passed_through(
        self, app: FastAPI, client: AsyncClient, mock_auth_admin
    ):
        install(app, json_responder(409, {"detail": "Cannot deactivate last admin"}))

        response = await client.put(
            "/admin/api/users/7/deactivate", headers=ADMIN_HEADERS
        )

        assert response.status_code == 409
        assert response.json() == {"detail": "Cannot deactivate last admin"}


class TestDeleteProxy:
    """Deletion is super admin only and relays 204, 409 and 400"""

    @pytest.mark.asyncio
    async def test_delete_user(
        self, app: FastAPI, client: AsyncClient, mock_auth_super_admin
    ):
        server = install(app, json_responder(204))

        response = await client.delete("/admin/api/users/7", headers=ADMIN_HEADERS)

        assert response.status_code == 204
        assert response.content == b""
        assert server.last.method == "DELETE"
        assert str(server.last.url) == f"{settings.AUTH_SERVER_URL}/users/users/7"

    @pytest.mark.asyncio
    async def test_delete_last_admin_conflict(
        self, app: FastAPI, client: AsyncClient, mock_auth_super_admin
    ):
        install(app, json_responder(409, {"detail": "Cannot delete the last admin"}))

        response = await client.delete("/admin/api/users/7", headers=ADMIN_HEADERS)

        assert response.status_code == 409
        assert response.json() == {"detail": "Cannot delete the last admin"}

    @pytest.mark.asyncio
    async def test_delete_self_is_rejected_by_auth_server(
        self, app: FastAPI, client: AsyncClient, mock_auth_super_admin
    ):
        install(app, json_responder(400, {"detail": "Cannot delete yourself"}))

        response = await client.delete("/admin/api/users/1", headers=ADMIN_HEADERS)

        assert response.status_code == 400
        assert response.json() == {"detail": "Cannot delete yourself"}


class TestFailureMapping:
    """Transport failures and auth server faults map to 503 and 502"""

    @pytest.mark.asyncio
    async def test_connection_error_is_503(
        self, app: FastAPI, client: AsyncClient, mock_auth_admin
    ):
        def responder(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        install(app, responder)

        response = await client.get("/admin/api/users/", headers=ADMIN_HEADERS)

        assert response.status_code == 503
        assert "unavailable" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_timeout_is_503(
        self, app: FastAPI, client: AsyncClient, mock_auth_admin
    ):
        def responder(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=request)

        install(app, responder)

        response = await client.get("/admin/api/users/", headers=ADMIN_HEADERS)

        assert response.status_code == 503
        assert "timed out" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_auth_server_500_becomes_502(
        self, app: FastAPI, client: AsyncClient, mock_auth_admin
    ):
        install(app, json_responder(500, {"detail": "boom"}))

        response = await client.get("/admin/api/users/", headers=ADMIN_HEADERS)

        assert response.status_code == 502
        assert "502" not in response.json()["detail"]
        assert "500" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_auth_server_401_is_passed_through(
        self, app: FastAPI, client: AsyncClient, mock_auth_admin
    ):
        install(app, json_responder(401, {"detail": "Invalid token"}))

        response = await client.get("/admin/api/users/", headers=ADMIN_HEADERS)

        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid token"}

    @pytest.mark.asyncio
    async def test_auth_server_403_is_passed_through(
        self, app: FastAPI, client: AsyncClient, mock_auth_admin
    ):
        install(app, json_responder(403, {"detail": "Insufficient permissions"}))

        response = await client.get("/admin/api/users/7", headers=ADMIN_HEADERS)

        assert response.status_code == 403
        assert response.json() == {"detail": "Insufficient permissions"}


class TestStillNotImplemented:
    """Password reset stays unimplemented"""

    @pytest.mark.asyncio
    async def test_reset_password_is_501(self, client: AsyncClient, mock_auth_admin):
        response = await client.post(
            "/admin/api/users/7/reset-password", headers=ADMIN_HEADERS
        )
        assert response.status_code == 501
        assert "not implemented" in response.json()["detail"].lower()


class TestNoExtraConfigurationNeeded:
    """The proxy works with the shipped defaults"""

    def test_default_users_path(self):
        from src.api.admin.users import _base_url, _collection_url

        assert settings.AUTH_SERVER_USERS_PATH == "/users"
        assert _base_url() == f"{settings.AUTH_SERVER_URL}/users"
        assert _collection_url() == f"{settings.AUTH_SERVER_URL}/users/users"
