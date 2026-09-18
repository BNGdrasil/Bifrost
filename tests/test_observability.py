# --------------------------------------------------------------------------
# Tests for health, readiness, metrics and rate limiting (OBS-01, SEC-06)
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import re

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _counter_value(body: str, service: str) -> float:
    total = 0.0
    pattern = re.compile(
        r'^http_requests_total\{[^}]*service="%s"[^}]*\}\s+([0-9.eE+-]+)$' % service,
        re.MULTILINE,
    )
    for match in pattern.finditer(body):
        total += float(match.group(1))
    return total


class TestHealthAndReadiness:
    """Liveness and readiness must be separate signals"""

    @pytest.mark.asyncio
    async def test_health_is_liveness_only(self, client: AsyncClient):
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy", "service": "bifrost"}

    @pytest.mark.asyncio
    async def test_ready_reports_ok(self, client: AsyncClient):
        response = await client.get("/ready")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["database"] == "ok"
        assert body["registry"] == "ok"

    @pytest.mark.asyncio
    async def test_ready_fails_when_database_is_down(
        self, client: AsyncClient, monkeypatch
    ):
        def broken_connection() -> bool:
            raise RuntimeError("connection refused")

        monkeypatch.setattr("src.main.check_database_connection", broken_connection)

        response = await client.get("/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not_ready"
        assert body["database"] == "error"
        assert "connection refused" in body["database_error"]

    @pytest.mark.asyncio
    async def test_ready_fails_when_registry_is_degraded(
        self, app: FastAPI, client: AsyncClient
    ):
        app.state.service_registry.ready = False
        app.state.service_registry.last_error = "registry load failed"

        response = await client.get("/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["registry"] == "degraded"
        assert body["registry_error"] == "registry load failed"

    @pytest.mark.asyncio
    async def test_health_stays_up_when_registry_is_degraded(
        self, app: FastAPI, client: AsyncClient
    ):
        app.state.service_registry.ready = False
        response = await client.get("/health")
        assert response.status_code == 200


class TestRegistryDegradedMode:
    """A failed reload keeps the last known good routing table"""

    @pytest.mark.asyncio
    async def test_failed_reload_keeps_previous_snapshot(self, app: FastAPI):
        from src.services.services import RegistryLoadError

        registry = app.state.service_registry
        before = registry.services
        assert before

        def broken_loader(*args, **kwargs):
            raise RuntimeError("database unavailable")

        registry._build_snapshot = broken_loader
        registry._load_snapshot_sync = broken_loader

        with pytest.raises(RegistryLoadError):
            await registry.reload()

        assert registry.ready is False
        assert registry.last_error is not None
        assert registry.services == before

    @pytest.mark.asyncio
    async def test_cold_start_failure_is_not_ready(self):
        from src.services.services import ServiceRegistry

        registry = ServiceRegistry()

        def broken_loader(*args, **kwargs):
            raise RuntimeError("database unavailable")

        registry._load_snapshot_sync = broken_loader

        assert await registry.initialize() is False
        assert registry.ready is False
        assert registry.services == {}
        await registry.cleanup()

    @pytest.mark.asyncio
    async def test_registry_loads_more_than_the_page_limit(self):
        from src.core.database import SessionLocal
        from src.crud.service import create_service, get_service_by_name
        from src.schemas.service import ServiceCreate
        from src.services.services import ServiceRegistry

        with SessionLocal() as session:
            for index in range(120):
                name = f"bulk-{index:03d}"
                if get_service_by_name(session, name) is None:
                    create_service(
                        session,
                        ServiceCreate(name=name, url=f"http://bulk-{index:03d}:8080"),
                    )

        registry = ServiceRegistry()
        assert await registry.initialize() is True
        assert len(registry.services) >= 120
        await registry.cleanup()


class TestMetrics:
    """Declared collectors must actually be incremented"""

    @pytest.mark.asyncio
    async def test_request_counter_increases(self, client: AsyncClient):
        before = _counter_value((await client.get("/metrics")).text, "gateway")
        await client.get("/health")
        after = _counter_value((await client.get("/metrics")).text, "gateway")
        assert after > before

    @pytest.mark.asyncio
    async def test_latency_histogram_is_observed(self, client: AsyncClient):
        await client.get("/health")
        body = (await client.get("/metrics")).text
        assert "http_request_duration_seconds_bucket" in body

    @pytest.mark.asyncio
    async def test_unknown_proxy_target_is_labelled_unknown(self, client: AsyncClient):
        before = _counter_value((await client.get("/metrics")).text, "unknown")
        await client.get("/api/v1/definitely-not-registered/path")
        after = _counter_value((await client.get("/metrics")).text, "unknown")
        assert after > before

    @pytest.mark.asyncio
    async def test_path_is_not_used_as_a_label(self, client: AsyncClient):
        await client.get("/api/v1/definitely-not-registered/some/deep/path")
        body = (await client.get("/metrics")).text
        assert "some/deep/path" not in body


class TestRateLimiting:
    """The limiter must use configuration and exempt operational endpoints"""

    @pytest.mark.asyncio
    async def test_configured_limit_is_enforced(self, monkeypatch):
        from src.core.config import settings
        from src.core.middleware import RateLimitMiddleware

        monkeypatch.setattr(settings, "RATE_LIMIT_PER_MINUTE", 3)

        limited = FastAPI()
        limited.add_middleware(RateLimitMiddleware)

        @limited.get("/ping")
        async def ping() -> dict:
            return {"ok": True}

        transport = ASGITransport(app=limited)
        async with AsyncClient(transport=transport, base_url="http://t") as http:
            statuses = [
                (
                    await http.get("/ping", headers={"x-forwarded-for": "198.51.100.7"})
                ).status_code
                for _ in range(5)
            ]

        assert statuses == [200, 200, 200, 429, 429]

    @pytest.mark.asyncio
    async def test_operational_endpoints_are_exempt(self, monkeypatch):
        from src.core.config import settings
        from src.core.middleware import RateLimitMiddleware

        monkeypatch.setattr(settings, "RATE_LIMIT_PER_MINUTE", 1)

        limited = FastAPI()
        limited.add_middleware(RateLimitMiddleware)

        @limited.get("/health")
        async def health() -> dict:
            return {"ok": True}

        @limited.get("/ready")
        async def ready() -> dict:
            return {"ok": True}

        @limited.get("/metrics")
        async def metrics() -> dict:
            return {"ok": True}

        transport = ASGITransport(app=limited)
        async with AsyncClient(transport=transport, base_url="http://t") as http:
            for path in ("/health", "/ready", "/metrics"):
                for _ in range(5):
                    response = await http.get(path)
                    assert response.status_code == 200

    def test_idle_clients_are_swept(self, monkeypatch):
        import time

        from src.core.middleware import RateLimitMiddleware

        middleware = RateLimitMiddleware(app=None)  # type: ignore[arg-type]
        assert middleware._check_rate_limit("203.0.113.1") is True
        assert "203.0.113.1" in middleware.rate_limits

        future = time.monotonic() + 3600
        monkeypatch.setattr(time, "monotonic", lambda: future)
        middleware._check_rate_limit("203.0.113.2")

        assert "203.0.113.1" not in middleware.rate_limits
        assert "203.0.113.2" in middleware.rate_limits
