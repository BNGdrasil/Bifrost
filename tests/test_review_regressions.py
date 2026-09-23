# --------------------------------------------------------------------------
# Regression tests for the configuration, metrics and registry findings
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import asyncio
import pathlib
import re
from typing import Dict

import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from src.core.config import Settings, settings
from src.core.metrics import OTHER_METHOD, method_label

ENV_EXAMPLE = pathlib.Path(__file__).resolve().parents[1] / "env.example"


def parse_env_example() -> Dict[str, str]:
    """Read env.example the way an operator would copy it into an .env file."""
    values: Dict[str, str] = {}
    for line in ENV_EXAMPLE.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        # Drop a trailing inline comment, as a dotenv reader would.
        value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        values[key.strip()] = value
    return values


class TestEnvExampleLoads:
    """Every shipped example value must produce a usable Settings object"""

    def test_env_example_is_parsed(self, monkeypatch):
        values = parse_env_example()
        assert values, "env.example produced no values"

        for key, value in values.items():
            monkeypatch.setenv(key, value)

        loaded = Settings(_env_file=None)

        assert loaded.ENVIRONMENT == "development"
        assert loaded.ALLOWED_HOSTS == ["localhost", "127.0.0.1"]
        assert loaded.RATE_LIMIT_EXEMPT_PATHS == ["/health", "/ready", "/metrics"]
        assert loaded.SERVICE_URL_ALLOWED_HOSTS == []
        assert loaded.SERVICE_URL_DENIED_HOSTS == []
        assert loaded.BACKEND_CORS_ORIGINS == [
            "http://localhost:3000",
            "http://localhost:3001",
        ]
        assert loaded.AUTH_SERVER_USERS_PATH == "/users"
        assert loaded.DATABASE_URL.endswith("/bngdrasil")
        # The shipped file leaves both observability backends unset, so a copy
        # of it must not half enable the endpoints that read them.
        assert loaded.PROMETHEUS_URL is None
        assert loaded.ALERTMANAGER_URL is None
        assert loaded.OBSERVABILITY_QUERY_TIMEOUT_SECONDS == 2.5

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("/health,/ready", ["/health", "/ready"]),
            ('["/health", "/ready"]', ["/health", "/ready"]),
            ("  ", []),
            ("/health", ["/health"]),
        ],
    )
    def test_list_fields_accept_both_formats(self, monkeypatch, raw, expected):
        monkeypatch.setenv("RATE_LIMIT_EXEMPT_PATHS", raw)
        monkeypatch.setenv("SERVICE_URL_DENIED_HOSTS", raw)
        loaded = Settings(_env_file=None)
        assert loaded.RATE_LIMIT_EXEMPT_PATHS == expected
        assert loaded.SERVICE_URL_DENIED_HOSTS == expected

    def test_empty_list_value_falls_back_to_the_default(self, monkeypatch):
        """An empty value means "not set", so the declared default applies.

        This is what env_ignore_empty buys: compose expanding an unset
        variable no longer turns the exempt path list off by accident. A
        whitespace-only value is still a real value and yields an empty list.
        """
        monkeypatch.setenv("RATE_LIMIT_EXEMPT_PATHS", "")
        monkeypatch.setenv("SERVICE_URL_DENIED_HOSTS", "")
        loaded = Settings(_env_file=None)
        assert loaded.RATE_LIMIT_EXEMPT_PATHS == ["/health", "/ready", "/metrics"]
        assert loaded.SERVICE_URL_DENIED_HOSTS == []

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ('["*"]', ["*"]),
            ("localhost,127.0.0.1", ["localhost", "127.0.0.1"]),
            ('["a.example","b.example"]', ["a.example", "b.example"]),
        ],
    )
    def test_allowed_hosts_from_environment(self, monkeypatch, raw, expected):
        monkeypatch.setenv("ALLOWED_HOSTS", raw)
        assert Settings(_env_file=None).ALLOWED_HOSTS == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (
                "http://a.example,http://b.example",
                ["http://a.example", "http://b.example"],
            ),
            ('["http://a.example"]', ["http://a.example"]),
            ('["*"]', ["*"]),
        ],
    )
    def test_cors_origins_from_environment(self, monkeypatch, raw, expected):
        monkeypatch.setenv("BACKEND_CORS_ORIGINS", raw)
        monkeypatch.setenv("CLIENT_ORIGIN", "")
        assert Settings(_env_file=None).BACKEND_CORS_ORIGINS == expected

    def test_default_database_name(self):
        loaded = Settings(_env_file=None, DATABASE_URL="")
        assert loaded.DATABASE_URL.endswith("/bngdrasil")


class TestMetricLabels:
    """Label values must come from a bounded set"""

    @pytest.mark.parametrize(
        "method", ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
    )
    def test_standard_methods_are_kept(self, method: str):
        assert method_label(method) == method

    @pytest.mark.parametrize("method", ["PROPFIND", "banana", "", "GET ", "\x00"])
    def test_unknown_methods_collapse(self, method: str):
        assert method_label(method) == OTHER_METHOD

    def test_lowercase_is_normalised(self):
        assert method_label("get") == "GET"

    @pytest.mark.asyncio
    async def test_metrics_never_show_an_unknown_method(self, client: AsyncClient):
        await client.request("PROPFIND", "/api/v1/nope/path")
        body = (await client.get("/metrics")).text
        assert 'method="PROPFIND"' not in body
        assert 'method="OTHER"' in body


def counter_total(body: str, status_class: str) -> float:
    pattern = re.compile(
        r'^http_requests_total\{[^}]*status_class="%s"[^}]*\}\s+([0-9.eE+-]+)$'
        % status_class,
        re.MULTILINE,
    )
    return sum(float(match.group(1)) for match in pattern.finditer(body))


class TestMiddlewareOrder:
    """Rejected requests must still be logged and counted"""

    @pytest.mark.asyncio
    async def test_rate_limited_response_is_observed(
        self, client: AsyncClient, monkeypatch
    ):
        monkeypatch.setattr(settings, "RATE_LIMIT_PER_MINUTE", 1)

        before = counter_total((await client.get("/metrics")).text, "4xx")

        first = await client.get("/api/v1/services")
        assert first.status_code == 200

        limited = await client.get("/api/v1/services")
        assert limited.status_code == 429
        assert limited.headers["x-request-id"]
        assert "x-process-time" in limited.headers

        after = counter_total((await client.get("/metrics")).text, "4xx")
        assert after > before


class TestAdminSessionRelease:
    """The request session is returned before the registry reload runs"""

    @pytest.mark.asyncio
    async def test_session_is_closed_before_reload(self):
        from src.api.admin import services as admin_services

        order = []

        class FakeSession:
            def close(self):
                order.append("close")

        class FakeRegistry:
            async def reload(self):
                order.append("reload")

        class FakeState:
            service_registry = FakeRegistry()

        class FakeApp:
            state = FakeState()

        class FakeRequest:
            app = FakeApp()

        await admin_services.reload_registry(FakeRequest(), FakeSession())

        assert order == ["close", "reload"]


class TestRegistryGeneration:
    """Reloads are serialised and stale probes must not write back"""

    @pytest.mark.asyncio
    async def test_generation_increases_on_reload(self, app: FastAPI):
        registry = app.state.service_registry
        before = registry.generation
        await registry.reload()
        assert registry.generation == before + 1

    @pytest.mark.asyncio
    async def test_concurrent_reloads_are_serialised(self, app: FastAPI):
        registry = app.state.service_registry
        before = registry.generation

        active = 0
        peak = 0
        original = registry._load_snapshot_sync

        def instrumented(db_session=None):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                return original(db_session)
            finally:
                active -= 1

        registry._load_snapshot_sync = instrumented
        await asyncio.gather(*[registry.reload() for _ in range(5)])

        assert peak == 1
        assert registry.generation == before + 5

    @pytest.mark.asyncio
    async def test_stale_probe_does_not_touch_a_newer_snapshot(self, app: FastAPI):
        registry = app.state.service_registry
        name = "hello"
        assert registry.get_service(name) is not None

        async def probe(url, **kwargs):
            # A reload lands while the probe is in flight.
            registry._generation += 1
            return httpx.Response(200, request=httpx.Request("GET", url))

        registry.http_client.get = probe  # type: ignore[method-assign]

        assert await registry.health_check(name) is True
        assert registry.get_service(name)["health_status"] == "unknown"

    @pytest.mark.asyncio
    async def test_current_probe_updates_the_snapshot(self, app: FastAPI):
        registry = app.state.service_registry
        name = "hello"

        async def probe(url, **kwargs):
            return httpx.Response(200, request=httpx.Request("GET", url))

        registry.http_client.get = probe  # type: ignore[method-assign]

        assert await registry.health_check(name) is True
        assert registry.get_service(name)["health_status"] == "healthy"


class TestHostCheckingIsNotOptional:
    """Host checking must fail loudly instead of disappearing"""

    VALID_KEY = "p" * 40
    VALID_DB = "postgresql://user:pass@db:5432/bngdrasil"

    def _production(self, **overrides):
        values = {
            "_env_file": None,
            "ENVIRONMENT": "production",
            "SECRET_KEY": self.VALID_KEY,
            "DATABASE_URL": self.VALID_DB,
            "BACKEND_CORS_ORIGINS": "https://bnbong.com",
            "ALLOWED_HOSTS": "api.bnbong.com",
        }
        values.update(overrides)
        return Settings(**values)

    def test_production_requires_allowed_hosts(self):
        with pytest.raises(ValueError, match="ALLOWED_HOSTS"):
            self._production(ALLOWED_HOSTS="")

    def test_production_accepts_explicit_hosts(self):
        loaded = self._production(ALLOWED_HOSTS="api.bnbong.com,admin.bnbong.com")
        assert loaded.ALLOWED_HOSTS == ["api.bnbong.com", "admin.bnbong.com"]

    def test_empty_hosts_outside_production_warn_and_fall_back(self):
        with pytest.warns(UserWarning, match="ALLOWED_HOSTS"):
            loaded = Settings(
                _env_file=None, ENVIRONMENT="development", ALLOWED_HOSTS=""
            )
        assert loaded.ALLOWED_HOSTS == ["*"]

    def test_trusted_host_middleware_is_always_registered(self, monkeypatch):
        from starlette.middleware.trustedhost import TrustedHostMiddleware

        from src.main import create_app

        monkeypatch.setattr(settings, "ENVIRONMENT", "development")
        monkeypatch.setattr(settings, "ALLOWED_HOSTS", ["api.example"])

        application = create_app()
        classes = [middleware.cls for middleware in application.user_middleware]
        assert TrustedHostMiddleware in classes

    def test_production_rejects_wildcard_host(self):
        with pytest.raises(ValueError, match="must not contain"):
            self._production(ALLOWED_HOSTS="*")

    def test_production_rejects_wildcard_mixed_with_names(self):
        with pytest.raises(ValueError, match="must not contain"):
            self._production(ALLOWED_HOSTS="api.bnbong.com,*")

    def test_production_still_allows_wildcard_cors_with_a_warning(self):
        with pytest.warns(UserWarning, match="BACKEND_CORS_ORIGINS"):
            loaded = self._production(BACKEND_CORS_ORIGINS="*")
        assert loaded.all_cors_origins == ["*"]

    def test_default_allowed_hosts_is_empty(self):
        assert Settings.model_fields["ALLOWED_HOSTS"].default == []

    @pytest.mark.asyncio
    async def test_wildcard_hosts_warn_at_startup(self, monkeypatch, caplog):
        import logging

        from src.main import create_app

        monkeypatch.setattr(settings, "ALLOWED_HOSTS", ["*"])

        application = create_app()
        with caplog.at_level(logging.WARNING, logger="src.main"):
            async with application.router.lifespan_context(application):
                pass

        assert any(
            "Host header checking is disabled" in record.getMessage()
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_wildcard_forwarded_ips_warn_at_startup(self, monkeypatch, caplog):
        import logging

        from src.main import create_app

        monkeypatch.setattr(settings, "FORWARDED_ALLOW_IPS", "*")

        application = create_app()
        with caplog.at_level(logging.WARNING, logger="src.main"):
            async with application.router.lifespan_context(application):
                pass

        assert any(
            "Forwarded headers are trusted from any address" in record.getMessage()
            for record in caplog.records
        )


class TestForwardedAllowIpsIsShared:
    """The entry point and the container command read the same setting"""

    def test_default_is_loopback(self):
        assert Settings(_env_file=None).FORWARDED_ALLOW_IPS == "127.0.0.1"

    def test_environment_override(self, monkeypatch):
        monkeypatch.setenv("FORWARDED_ALLOW_IPS", "10.0.0.0/8")
        assert Settings(_env_file=None).FORWARDED_ALLOW_IPS == "10.0.0.0/8"

    def test_entry_point_passes_the_setting_to_uvicorn(self, monkeypatch):
        import src.main as main_module

        captured = {}

        def fake_run(app, **kwargs):
            captured["app"] = app
            captured.update(kwargs)

        monkeypatch.setattr(main_module.uvicorn, "run", fake_run)
        monkeypatch.setattr(settings, "FORWARDED_ALLOW_IPS", "10.1.2.3")
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")

        main_module.main()

        assert captured["forwarded_allow_ips"] == "10.1.2.3"
        assert captured["proxy_headers"] is True
        assert captured["workers"] == 1
        assert captured["reload"] is False

    def test_container_command_uses_the_entry_point(self):
        dockerfile = (
            pathlib.Path(__file__).resolve().parents[1] / "Dockerfile"
        ).read_text()
        # The command must not hardcode uvicorn flags that could drift from
        # the Settings object.
        assert 'CMD ["python", "-m", "src.main"]' in dockerfile
        assert "--forwarded-allow-ips" not in dockerfile
