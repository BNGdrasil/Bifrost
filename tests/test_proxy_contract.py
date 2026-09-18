# --------------------------------------------------------------------------
# Proxy contract tests against an in-process echo upstream (GW-02)
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import base64
import gzip
from typing import AsyncGenerator, Callable

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request, Response
from httpx import ASGITransport, AsyncClient

from src.core.database import SessionLocal, get_db
from src.crud.service import create_service, get_service_by_name
from src.main import create_app
from src.schemas.service import ServiceCreate
from src.services.services import ServiceProxy, ServiceRegistry, create_http_client

ECHO_SERVICE_NAME = "echo-upstream"
ECHO_SERVICE_URL = "http://echo-upstream:8080"
BINARY_PAYLOAD = bytes(range(256)) * 4


def build_echo_app() -> FastAPI:
    """Minimal upstream that reports back what it received."""
    echo = FastAPI()

    @echo.get("/gzip")
    async def gzipped() -> Response:
        body = gzip.compress(b"compressed-upstream-body" * 32)
        return Response(
            content=body,
            media_type="application/json",
            headers={"content-encoding": "gzip"},
        )

    @echo.get("/binary")
    async def binary() -> Response:
        return Response(content=BINARY_PAYLOAD, media_type="application/octet-stream")

    @echo.get("/cookies")
    async def cookies() -> Response:
        response = Response(content=b"{}", media_type="application/json")
        response.headers.append("set-cookie", "a=1; Path=/")
        response.headers.append("set-cookie", "b=2; Path=/")
        response.headers.append("connection", "keep-alive")
        return response

    @echo.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
    )
    async def catch_all(path: str, request: Request) -> Response:
        body = await request.body()
        payload = {
            "method": request.method,
            "path": request.url.path,
            "raw_query": request.url.query,
            "headers": {k.lower(): v for k, v in request.headers.items()},
            "body_b64": base64.b64encode(body).decode(),
        }
        import json

        return Response(
            content=json.dumps(payload).encode(),
            media_type="application/json",
        )

    return echo


def ensure_echo_service() -> None:
    with SessionLocal() as session:
        if get_service_by_name(session, ECHO_SERVICE_NAME) is None:
            create_service(
                session,
                ServiceCreate(
                    name=ECHO_SERVICE_NAME,
                    url=ECHO_SERVICE_URL,
                    display_name="Echo upstream",
                ),
            )


async def make_gateway_client(
    transport: httpx.AsyncBaseTransport,
) -> AsyncGenerator[AsyncClient, None]:
    ensure_echo_service()
    application = create_app()
    upstream_client = create_http_client(transport=transport)
    application.state.http_client = upstream_client
    registry = ServiceRegistry(http_client=upstream_client)
    application.state.service_registry = registry
    application.state.service_proxy = ServiceProxy(registry, upstream_client)
    await registry.initialize()

    def override_get_db():
        with SessionLocal() as session:
            yield session

    application.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://gateway"
    ) as gateway_client:
        yield gateway_client

    await upstream_client.aclose()


@pytest_asyncio.fixture
async def echo_client() -> AsyncGenerator[AsyncClient, None]:
    async for gateway_client in make_gateway_client(
        ASGITransport(app=build_echo_app())
    ):
        yield gateway_client


def failing_transport(error_factory: Callable[[httpx.Request], Exception]):
    def handler(request: httpx.Request) -> httpx.Response:
        raise error_factory(request)

    return httpx.MockTransport(handler)


class TestProxySemantics:
    """Query strings, headers and bodies must survive the hop"""

    @pytest.mark.asyncio
    async def test_duplicate_query_keys_are_preserved(self, echo_client: AsyncClient):
        response = await echo_client.get(
            f"/api/v1/{ECHO_SERVICE_NAME}/items?tag=a&tag=b&empty=&plain"
        )
        assert response.status_code == 200
        assert response.json()["raw_query"] == "tag=a&tag=b&empty=&plain"

    @pytest.mark.asyncio
    async def test_path_is_forwarded(self, echo_client: AsyncClient):
        response = await echo_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/deep/nested/x")
        assert response.json()["path"] == "/deep/nested/x"

    @pytest.mark.asyncio
    async def test_hop_by_hop_request_headers_are_dropped(
        self, echo_client: AsyncClient
    ):
        response = await echo_client.get(
            f"/api/v1/{ECHO_SERVICE_NAME}/headers",
            headers={
                "connection": "close",
                "te": "trailers",
                "proxy-authorization": "Basic zzz",
                "x-keep-me": "yes",
            },
        )
        received = response.json()["headers"]
        assert "te" not in received
        assert "proxy-authorization" not in received
        # The client hop header must not leak into the upstream hop.
        assert received.get("connection") != "close"
        assert received["x-keep-me"] == "yes"
        assert received["host"] != "gateway"

    @pytest.mark.asyncio
    async def test_forwarding_headers_are_added(self, echo_client: AsyncClient):
        response = await echo_client.get(
            f"/api/v1/{ECHO_SERVICE_NAME}/headers",
            headers={"x-forwarded-for": "203.0.113.9"},
        )
        received = response.json()["headers"]
        assert received["x-forwarded-for"].startswith("203.0.113.9")
        assert received["x-forwarded-proto"] in ("http", "https")
        assert received["x-request-id"]

    @pytest.mark.asyncio
    async def test_binary_body_round_trip(self, echo_client: AsyncClient):
        response = await echo_client.post(
            f"/api/v1/{ECHO_SERVICE_NAME}/upload",
            content=BINARY_PAYLOAD,
            headers={"content-type": "application/octet-stream"},
        )
        assert response.status_code == 200
        assert base64.b64decode(response.json()["body_b64"]) == BINARY_PAYLOAD

    @pytest.mark.asyncio
    async def test_binary_response_is_intact(self, echo_client: AsyncClient):
        response = await echo_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/binary")
        assert response.status_code == 200
        assert response.content == BINARY_PAYLOAD
        assert response.headers["content-type"] == "application/octet-stream"

    @pytest.mark.asyncio
    async def test_gzip_response_is_decoded_consistently(
        self, echo_client: AsyncClient
    ):
        response = await echo_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/gzip")
        assert response.status_code == 200
        assert "content-encoding" not in response.headers
        assert response.content == b"compressed-upstream-body" * 32
        assert int(response.headers["content-length"]) == len(response.content)

    @pytest.mark.asyncio
    async def test_multiple_set_cookie_headers_are_preserved(
        self, echo_client: AsyncClient
    ):
        response = await echo_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/cookies")
        cookies = response.headers.get_list("set-cookie")
        assert len(cookies) == 2
        assert "a=1; Path=/" in cookies
        assert "b=2; Path=/" in cookies
        assert "connection" not in response.headers

    @pytest.mark.asyncio
    async def test_head_request_is_supported(self, echo_client: AsyncClient):
        response = await echo_client.head(f"/api/v1/{ECHO_SERVICE_NAME}/anything")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_options_request_is_supported(self, echo_client: AsyncClient):
        response = await echo_client.request(
            "OPTIONS", f"/api/v1/{ECHO_SERVICE_NAME}/anything"
        )
        assert response.status_code == 200
        assert response.json()["method"] == "OPTIONS"

    @pytest.mark.asyncio
    async def test_upstream_status_is_passed_through(self, echo_client: AsyncClient):
        response = await echo_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/gzip/missing")
        assert response.status_code == 200


class TestProxyErrorMapping:
    """Upstream failures must map to distinct gateway statuses"""

    @pytest.mark.asyncio
    async def test_unknown_service_is_404(self, echo_client: AsyncClient):
        response = await echo_client.get("/api/v1/not-registered/path")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_timeout_is_504(self):
        transport = failing_transport(
            lambda request: httpx.ReadTimeout("timed out", request=request)
        )
        async for gateway_client in make_gateway_client(transport):
            response = await gateway_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/slow")
            assert response.status_code == 504

    @pytest.mark.asyncio
    async def test_connect_error_is_502(self):
        transport = failing_transport(
            lambda request: httpx.ConnectError("refused", request=request)
        )
        async for gateway_client in make_gateway_client(transport):
            response = await gateway_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/down")
            assert response.status_code == 502

    @pytest.mark.asyncio
    async def test_oversized_body_is_413(self, echo_client: AsyncClient, monkeypatch):
        from src.core.config import settings

        monkeypatch.setattr(settings, "MAX_REQUEST_BODY_BYTES", 1024)
        response = await echo_client.post(
            f"/api/v1/{ECHO_SERVICE_NAME}/upload",
            content=b"x" * 4096,
        )
        assert response.status_code == 413
