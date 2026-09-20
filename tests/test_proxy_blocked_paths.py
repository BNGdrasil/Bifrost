# --------------------------------------------------------------------------
# Tests for blocking upstream operational endpoints at the proxy
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import os
from typing import AsyncGenerator
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from pydantic import ValidationError

from src.core.config import Settings, settings
from src.core.pathpolicy import comparable_path_segments, path_is_blocked
from src.core.urlpolicy import ServiceUrlPolicyError, validate_service_url
from src.schemas.service import ServiceCreate, ServiceUpdate
from src.services.services import BlockedUpstreamPathError, ServiceProxy
from tests.test_proxy_contract import ECHO_SERVICE_NAME, make_gateway_client
from tests.test_proxy_hardening import RecordingUpstream


@pytest_asyncio.fixture
async def blocking_upstream() -> AsyncGenerator[RecordingUpstream, None]:
    yield RecordingUpstream()


@pytest_asyncio.fixture
async def blocking_client(
    blocking_upstream: RecordingUpstream,
) -> AsyncGenerator[AsyncClient, None]:
    async for gateway_client in make_gateway_client(blocking_upstream.transport):
        yield gateway_client


class TestBlockedUpstreamPathsOverHttp:
    """The upstream Prometheus endpoint must not be reachable through /api/v1"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "suffix",
        [
            "metrics",
            "metrics/",
            "METRICS",
            "Metrics",
            "metrics/x",
            "metrics/deep/nested",
            # The server decodes the path once more than this gateway does, so
            # an encoded spelling has to be compared in its decoded form.
            "%6Detrics",
            "%6d%65trics",
            "METRICS/",
            # Path parameters and a doubled slash are stripped by some
            # upstream stacks before routing.
            "metrics;jsessionid=1",
            "/metrics",
            # An upstream that decodes the path a second time sees /metrics
            # again, so every decoding round is compared, not only the first.
            "%256Detrics",
            "%25%36%44etrics",
            "%256d%65trics",
            "metrics%3Fx",
        ],
    )
    async def test_metrics_paths_are_not_proxied(
        self,
        blocking_upstream: RecordingUpstream,
        blocking_client: AsyncClient,
        suffix: str,
    ):
        response = await blocking_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/{suffix}")
        assert response.status_code == 404
        assert blocking_upstream.requests == []

    @pytest.mark.asyncio
    async def test_blocked_response_does_not_name_the_endpoint(
        self, blocking_client: AsyncClient
    ):
        response = await blocking_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/metrics")
        assert response.status_code == 404
        assert response.json() == {"detail": "Not Found"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["GET", "POST", "HEAD", "OPTIONS"])
    async def test_every_proxied_method_is_blocked(
        self,
        blocking_upstream: RecordingUpstream,
        blocking_client: AsyncClient,
        method: str,
    ):
        response = await blocking_client.request(
            method, f"/api/v1/{ECHO_SERVICE_NAME}/metrics"
        )
        assert response.status_code == 404
        assert blocking_upstream.requests == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "suffix",
        [
            "metricsfoo",
            "metrics-report",
            "v1/metrics-report",
            "v1/metrics_summary",
            "deep/nested/x",
            "items",
        ],
    )
    async def test_neighbouring_paths_still_reach_the_upstream(
        self,
        blocking_upstream: RecordingUpstream,
        blocking_client: AsyncClient,
        suffix: str,
    ):
        response = await blocking_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/{suffix}")
        assert response.status_code == 200
        assert len(blocking_upstream.requests) == 1

    @pytest.mark.asyncio
    async def test_query_strings_survive_on_an_allowed_path(
        self, blocking_client: AsyncClient
    ):
        response = await blocking_client.get(
            f"/api/v1/{ECHO_SERVICE_NAME}/metrics-report?tag=a&tag=b"
        )
        assert response.status_code == 200
        assert response.json()["query"] == "tag=a&tag=b"

    @pytest.mark.asyncio
    async def test_block_list_is_configurable(
        self,
        blocking_upstream: RecordingUpstream,
        blocking_client: AsyncClient,
        monkeypatch,
    ):
        monkeypatch.setattr(
            settings, "PROXY_BLOCKED_UPSTREAM_PATHS", ["/internal/admin"]
        )

        allowed = await blocking_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/metrics")
        assert allowed.status_code == 200

        refused = await blocking_client.get(
            f"/api/v1/{ECHO_SERVICE_NAME}/internal/admin/reload"
        )
        assert refused.status_code == 404
        assert len(blocking_upstream.requests) == 1

    @pytest.mark.asyncio
    async def test_empty_block_list_proxies_everything(
        self, blocking_client: AsyncClient, monkeypatch
    ):
        monkeypatch.setattr(settings, "PROXY_BLOCKED_UPSTREAM_PATHS", [])

        response = await blocking_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/metrics")
        assert response.status_code == 200


class TestGatewayOwnEndpointsAreUntouched:
    """Blocking upstream metrics must not affect the gateway's own endpoints"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", ["/health", "/ready", "/metrics"])
    async def test_gateway_endpoints_still_answer(
        self, blocking_client: AsyncClient, path: str
    ):
        response = await blocking_client.get(path)
        assert response.status_code == 200


class TestComparablePathSegments:
    """The comparison must survive every spelling that reaches the handler"""

    @pytest.mark.parametrize(
        "path, expected",
        [
            ("/metrics", ("metrics",)),
            ("/metrics/", ("metrics",)),
            ("//metrics//", ("metrics",)),
            ("/METRICS", ("metrics",)),
            ("/%6Detrics", ("metrics",)),
            ("/metrics;x=1", ("metrics",)),
            ("/metrics%20", ("metrics",)),
            ("/a/b/c", ("a", "b", "c")),
            ("/metricsfoo", ("metricsfoo",)),
            ("/metrics?x=1", ("metrics",)),
            ("/files/100%25", ("files", "100%")),
        ],
    )
    def test_segments_are_normalised(self, path: str, expected):
        assert comparable_path_segments(path) == expected

    def test_decoding_runs_until_the_path_stops_changing(self):
        """A doubly encoded spelling reaches /metrics on a second decoding.

        The earlier version of this helper stopped after one round and treated
        `%256D` as the literal text `%6D`. That holds only for an upstream that
        decodes exactly once. An upstream or an intermediate proxy that decodes
        again routes the request to the real endpoint, and the cost of being
        wrong the other way is a refused request whose path contains a doubly
        encoded spelling of a blocked endpoint, which no client sends by
        accident. So the comparison now decodes until the path settles.
        """
        assert comparable_path_segments("/%256Detrics") == ("metrics",)
        assert comparable_path_segments("/%25%36%44etrics") == ("metrics",)


class TestPathIsBlocked:
    """An entry blocks a whole segment and everything below it"""

    @pytest.mark.parametrize(
        "path",
        [
            "/metrics",
            "/metrics/",
            "/METRICS",
            "/metrics/x",
            "/%6Detrics",
            "/metrics;x",
            "//metrics",
            "/%256Detrics",
            "/metrics%3Fx",
        ],
    )
    def test_blocked_paths(self, path: str):
        assert path_is_blocked(path, ["/metrics"]) is True

    @pytest.mark.parametrize(
        "path",
        [
            "/metricsfoo",
            "/v1/metrics-report",
            "/v1/metrics",
            "/",
            "",
            "/metricsz/x",
            "/files/100%25",
            "/metrics-report",
        ],
    )
    def test_allowed_paths(self, path: str):
        assert path_is_blocked(path, ["/metrics"]) is False

    def test_an_empty_list_blocks_nothing(self):
        assert path_is_blocked("/metrics", []) is False

    def test_a_multi_segment_entry_matches_whole_segments(self):
        assert path_is_blocked("/internal/admin/reload", ["/internal/admin"]) is True
        assert path_is_blocked("/internal/administration", ["/internal/admin"]) is False


class TestBuildTargetUrlBlocking:
    """The block runs on both the relative and the absolute upstream path"""

    def test_root_service_metrics_is_blocked(self):
        proxy = ServiceProxy.__new__(ServiceProxy)
        service = {"url": "http://auth-server:8001"}

        with pytest.raises(BlockedUpstreamPathError):
            proxy.build_target_url(service, b"/metrics", b"")

    def test_base_path_service_metrics_is_blocked(self):
        """Base path /x moves the upstream endpoint to /x/metrics"""
        proxy = ServiceProxy.__new__(ServiceProxy)
        service = {"url": "http://upstream:8080/x"}

        with pytest.raises(BlockedUpstreamPathError):
            proxy.build_target_url(service, b"/metrics", b"")

    def test_base_path_that_already_ends_at_the_endpoint_is_blocked(self):
        proxy = ServiceProxy.__new__(ServiceProxy)
        service = {"url": "http://upstream:8080/metrics"}

        with pytest.raises(BlockedUpstreamPathError):
            proxy.build_target_url(service, b"/", b"")

    def test_neighbouring_path_is_still_built(self):
        proxy = ServiceProxy.__new__(ServiceProxy)
        service = {"url": "http://upstream:8080/x"}

        assert (
            str(proxy.build_target_url(service, b"/metrics-report", b""))
            == "http://upstream:8080/x/metrics-report"
        )

    def test_query_string_cannot_hide_the_path(self):
        proxy = ServiceProxy.__new__(ServiceProxy)
        service = {"url": "http://upstream:8080"}

        with pytest.raises(BlockedUpstreamPathError):
            proxy.build_target_url(service, b"/metrics", b"x=1")


class TestBlockedPathsSetting:
    """The setting follows the StringList conventions of the other lists"""

    @staticmethod
    def _build(**env):
        with patch.dict(os.environ, env, clear=True):
            return Settings(_env_file=None)

    def test_default_blocks_metrics(self):
        assert self._build().PROXY_BLOCKED_UPSTREAM_PATHS == ["/metrics"]

    def test_empty_environment_value_keeps_the_default(self):
        """An unset compose variable must not turn the block list off"""
        built = self._build(PROXY_BLOCKED_UPSTREAM_PATHS="")
        assert built.PROXY_BLOCKED_UPSTREAM_PATHS == ["/metrics"]

    def test_comma_separated_value_is_accepted(self):
        built = Settings(
            _env_file=None, PROXY_BLOCKED_UPSTREAM_PATHS="/metrics, /internal"
        )
        assert built.PROXY_BLOCKED_UPSTREAM_PATHS == ["/metrics", "/internal"]

    def test_json_list_is_accepted(self):
        built = Settings(
            _env_file=None,
            PROXY_BLOCKED_UPSTREAM_PATHS='["/metrics", "/debug/pprof"]',
        )
        assert built.PROXY_BLOCKED_UPSTREAM_PATHS == ["/metrics", "/debug/pprof"]

    def test_an_explicit_json_empty_list_turns_the_block_off(self):
        built = Settings(_env_file=None, PROXY_BLOCKED_UPSTREAM_PATHS="[]")
        assert built.PROXY_BLOCKED_UPSTREAM_PATHS == []

    @pytest.mark.parametrize("value", [" ", "   ", ",", ", ,", "\t", " , "])
    def test_a_blank_value_keeps_the_default(self, value: str):
        """A blank list is what a half written variable expands to.

        `env_ignore_empty` already turns an exactly empty value into "not
        set", but a value made only of whitespace and commas slipped past it
        and silently emptied the block list. Since the 2026-09-19 outage this
        repository treats an empty environment value as "use the safe
        default", so the same answer applies here.
        """
        built = Settings(_env_file=None, PROXY_BLOCKED_UPSTREAM_PATHS=value)
        assert built.PROXY_BLOCKED_UPSTREAM_PATHS == ["/metrics"]

    def test_a_blank_environment_value_keeps_the_default(self):
        built = self._build(PROXY_BLOCKED_UPSTREAM_PATHS=" , ")
        assert built.PROXY_BLOCKED_UPSTREAM_PATHS == ["/metrics"]

    def test_the_default_is_not_shared_between_instances(self):
        first = self._build()
        first.PROXY_BLOCKED_UPSTREAM_PATHS.append("/debug")
        assert self._build().PROXY_BLOCKED_UPSTREAM_PATHS == ["/metrics"]


class TestBlockedPathsInRegisteredServiceUrls:
    """A base URL must not park a service on top of a blocked endpoint"""

    @pytest.mark.parametrize(
        "url",
        [
            "http://upstream:8080/metrics",
            "http://upstream:8080/metrics/",
            "http://upstream:8080/METRICS",
            "http://upstream:8080/metrics/sub",
            "http://upstream:8080/%6Detrics",
        ],
    )
    def test_a_blocked_base_path_is_refused(self, url: str):
        with pytest.raises(ServiceUrlPolicyError):
            validate_service_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://upstream:8080",
            "http://upstream:8080/",
            "http://upstream:8080/x",
            "http://upstream:8080/metrics-report",
            "http://upstream:8080/v1/metrics",
        ],
    )
    def test_a_neighbouring_base_path_is_accepted(self, url: str):
        assert validate_service_url(url) == url.rstrip("/")

    def test_the_create_schema_refuses_a_blocked_base_path(self):
        """The admin write path answers 422 through this validator."""
        with pytest.raises(ValidationError):
            ServiceCreate(name="blocked", url="http://upstream:8080/metrics")

    def test_the_update_schema_refuses_a_blocked_base_path(self):
        with pytest.raises(ValidationError):
            ServiceUpdate(url="http://upstream:8080/metrics/sub")

    def test_the_schemas_still_accept_an_ordinary_base_path(self):
        created = ServiceCreate(name="ok", url="http://upstream:8080/x")
        assert created.url == "http://upstream:8080/x"
        assert ServiceUpdate(url="http://upstream:8080/x").url == (
            "http://upstream:8080/x"
        )
