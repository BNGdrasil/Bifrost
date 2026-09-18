# --------------------------------------------------------------------------
# Tests for application lifespan wiring (GW-01)
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.main import create_app


class TestLifespan:
    """One HTTP client per process, created and closed by the lifespan"""

    @pytest.mark.asyncio
    async def test_lifespan_creates_and_closes_one_client(self):
        application = create_app()

        async with application.router.lifespan_context(application):
            client = application.state.http_client
            assert isinstance(client, httpx.AsyncClient)
            assert client.is_closed is False
            # The registry and the proxy share the very same client.
            assert application.state.service_registry.http_client is client
            assert application.state.service_proxy.http_client is client
            assert application.state.service_registry.ready is True

        assert client.is_closed is True

    @pytest.mark.asyncio
    async def test_startup_survives_a_broken_database(self, monkeypatch):
        def broken_loader(*args, **kwargs):
            raise RuntimeError("database unavailable")

        monkeypatch.setattr(
            "src.services.services.get_all_active_services", broken_loader
        )

        application = create_app()
        async with application.router.lifespan_context(application):
            registry = application.state.service_registry
            assert registry.ready is False
            assert registry.services == {}

            transport = ASGITransport(app=application)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                assert (await client.get("/health")).status_code == 200
                assert (await client.get("/ready")).status_code == 503

    @pytest.mark.asyncio
    async def test_proxy_client_is_not_recreated_per_request(
        self, app: FastAPI, client: AsyncClient
    ):
        seen = set()
        for _ in range(3):
            await client.get("/api/v1/services")
            seen.add(id(app.state.service_proxy.http_client))
        assert len(seen) == 1
