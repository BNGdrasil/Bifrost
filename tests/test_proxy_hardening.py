# --------------------------------------------------------------------------
# Regression tests for the proxy hardening review findings
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import json
from typing import AsyncGenerator, List

import httpx
import pytest
import pytest_asyncio
from httpx import AsyncClient

from src.services.services import (
    ServiceProxy,
    UnsafeProxyPathError,
    connection_tokens,
    create_http_client,
    filter_request_headers,
    filter_response_headers,
)
from tests.test_proxy_contract import ECHO_SERVICE_NAME, make_gateway_client


class RecordingUpstream:
    """Upstream that records every request and can set cookies."""

    def __init__(self) -> None:
        self.requests: List[httpx.Request] = []
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        payload = {
            "raw_path": request.url.raw_path.decode("latin-1"),
            "path": request.url.path,
            "query": request.url.query.decode("latin-1"),
            "headers": {k.lower(): v for k, v in request.headers.items()},
        }
        return httpx.Response(
            200,
            content=json.dumps(payload).encode(),
            headers=[
                ("content-type", "application/json"),
                ("set-cookie", "upstream_session=leaked; Path=/"),
            ],
        )


@pytest_asyncio.fixture
async def upstream() -> AsyncGenerator[RecordingUpstream, None]:
    yield RecordingUpstream()


@pytest_asyncio.fixture
async def recording_client(
    upstream: RecordingUpstream,
) -> AsyncGenerator[AsyncClient, None]:
    async for gateway_client in make_gateway_client(upstream.transport):
        yield gateway_client


class TestCookieIsolation:
    """A shared client must never replay one caller's cookies to another"""

    @pytest.mark.asyncio
    async def test_upstream_set_cookie_is_not_replayed(
        self, upstream: RecordingUpstream, recording_client: AsyncClient
    ):
        first = await recording_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/first")
        assert first.status_code == 200
        assert "set-cookie" in first.headers

        # The outer client keeps the cookie the way the first caller's browser
        # would. Clearing it stands for a second, unrelated caller reaching the
        # same gateway process.
        recording_client.cookies.clear()

        second = await recording_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/second")
        assert second.status_code == 200

        assert "cookie" not in second.json()["headers"]

    @pytest.mark.asyncio
    async def test_inbound_cookie_is_still_forwarded(
        self, recording_client: AsyncClient
    ):
        response = await recording_client.get(
            f"/api/v1/{ECHO_SERVICE_NAME}/x",
            headers={"cookie": "caller_session=mine"},
        )
        assert response.json()["headers"]["cookie"] == "caller_session=mine"

    @pytest.mark.asyncio
    async def test_client_jar_stays_empty(self):
        recorded: List[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            return httpx.Response(200, headers={"set-cookie": "a=1; Path=/"})

        client = create_http_client(transport=httpx.MockTransport(handler))
        try:
            await client.get("http://upstream.invalid/one")
            assert len(client.cookies.jar) == 0
            await client.get("http://upstream.invalid/two")
        finally:
            await client.aclose()

        assert "cookie" not in recorded[1].headers


class TestPathTraversal:
    """The registered base path must contain every proxied request"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "suffix",
        [
            "%2e%2e/%2e%2e/admin",
            "a/%2E%2E/%2e%2e/admin",
            "..%2Fadmin",
            "a/%2e/b",
            "%2e%2e%2fadmin",
        ],
    )
    async def test_dot_segments_are_rejected(
        self, upstream: RecordingUpstream, recording_client: AsyncClient, suffix: str
    ):
        response = await recording_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/{suffix}")
        assert response.status_code == 400
        assert upstream.requests == []

    @pytest.mark.asyncio
    async def test_encoded_question_mark_stays_in_the_path(
        self, upstream: RecordingUpstream, recording_client: AsyncClient
    ):
        response = await recording_client.get(
            f"/api/v1/{ECHO_SERVICE_NAME}/a%3Fb?real=1"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["raw_path"].startswith("/a%3Fb")
        assert body["query"] == "real=1"
        assert body["path"] == "/a?b"

    @pytest.mark.asyncio
    async def test_encoded_hash_stays_in_the_path(self, recording_client: AsyncClient):
        response = await recording_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/a%23b")
        assert response.status_code == 200
        assert response.json()["raw_path"] == "/a%23b"

    @pytest.mark.asyncio
    async def test_encoded_space_is_preserved(self, recording_client: AsyncClient):
        response = await recording_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/a%20b")
        assert response.status_code == 200
        assert response.json()["raw_path"] == "/a%20b"
        assert response.json()["path"] == "/a b"

    @pytest.mark.asyncio
    async def test_non_ascii_path_is_preserved(self, recording_client: AsyncClient):
        response = await recording_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/가/나")
        assert response.status_code == 200
        body = response.json()
        assert body["path"] == "/가/나"
        assert "%EA%B0%80" in body["raw_path"].upper()

    @pytest.mark.asyncio
    async def test_duplicate_query_keys_still_survive(
        self, recording_client: AsyncClient
    ):
        response = await recording_client.get(
            f"/api/v1/{ECHO_SERVICE_NAME}/items?tag=a&tag=b"
        )
        assert response.json()["query"] == "tag=a&tag=b"

    @pytest.mark.parametrize("path", ["../admin", "./admin", "a/../../admin", ".."])
    def test_literal_dot_segments_are_rejected(self, path: str):
        """Clients normalise literal dot segments, so this is a unit check."""
        from src.api.api import PathExtractionError, reject_unsafe_path

        with pytest.raises(PathExtractionError):
            reject_unsafe_path(("/" + path).encode(), path)

    def test_normal_path_passes_the_check(self):
        from src.api.api import reject_unsafe_path

        reject_unsafe_path(b"/a%20b/c", "a b/c")

    def test_build_target_url_refuses_to_escape_the_base_path(self):
        proxy = ServiceProxy.__new__(ServiceProxy)
        service = {"url": "http://upstream:8080/base"}

        assert (
            str(proxy.build_target_url(service, b"/inside", b""))
            == "http://upstream:8080/base/inside"
        )
        with pytest.raises(UnsafeProxyPathError):
            proxy.build_target_url(service, b"/../../escaped", b"")


class TestDynamicHopByHopHeaders:
    """Headers nominated by Connection must not cross the hop"""

    def test_connection_tokens_are_collected(self):
        items = [("Connection", "keep-alive, X-Internal-Token, close")]
        assert connection_tokens(items) == {"x-internal-token"}

    def test_request_headers_listed_by_connection_are_dropped(self):
        items = [
            ("connection", "x-internal-token"),
            ("x-internal-token", "secret"),
            ("x-keep", "yes"),
        ]
        filtered = dict(filter_request_headers(items))
        assert "x-internal-token" not in filtered
        assert filtered["x-keep"] == "yes"

    def test_response_headers_listed_by_connection_are_dropped(self):
        items = [
            ("connection", "x-upstream-hint"),
            ("x-upstream-hint", "internal"),
            ("x-keep", "yes"),
        ]
        filtered = dict(filter_response_headers(items))
        assert "x-upstream-hint" not in filtered
        assert filtered["x-keep"] == "yes"

    @pytest.mark.asyncio
    async def test_dynamic_hop_header_is_not_forwarded(
        self, recording_client: AsyncClient
    ):
        response = await recording_client.get(
            f"/api/v1/{ECHO_SERVICE_NAME}/x",
            headers={
                "connection": "x-internal-token",
                "x-internal-token": "secret",
                "x-keep": "yes",
            },
        )
        received = response.json()["headers"]
        assert "x-internal-token" not in received
        assert received["x-keep"] == "yes"


class TestBackslashAndFallbackPaths:
    """Backslashes never reach an upstream, and an unverifiable path is refused"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("suffix", ["a%5Cb", "a%5cb"])
    async def test_encoded_backslash_is_rejected(
        self, upstream: RecordingUpstream, recording_client: AsyncClient, suffix: str
    ):
        response = await recording_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/{suffix}")
        assert response.status_code == 400
        assert upstream.requests == []

    def test_literal_backslash_in_raw_bytes_is_rejected(self):
        from src.api.api import PathExtractionError, reject_unsafe_path

        with pytest.raises(PathExtractionError, match="Backslash"):
            reject_unsafe_path(b"/a\\b", "a\\b")

    def test_literal_backslash_in_decoded_segment_is_rejected(self):
        from src.api.api import PathExtractionError, reject_unsafe_path

        with pytest.raises(PathExtractionError, match="Backslash"):
            reject_unsafe_path(b"/ok", "..\\windows")

    @pytest.mark.parametrize(
        "decoded", ["a%20b", "a%2e%2e", ".hidden/x", "a/.b", "..", "a\\b", "50%"]
    )
    def test_fallback_mode_refuses_unverifiable_paths(self, decoded: str):
        from src.api.api import PathExtractionError, reject_unsafe_path

        with pytest.raises(PathExtractionError):
            reject_unsafe_path(("/" + decoded).encode(), decoded, from_fallback=True)

    @pytest.mark.parametrize("decoded", ["a/b", "items/42", "v1/x-y_z"])
    def test_fallback_mode_still_allows_plain_paths(self, decoded: str):
        from src.api.api import reject_unsafe_path

        reject_unsafe_path(("/" + decoded).encode(), decoded, from_fallback=True)

    @pytest.mark.asyncio
    async def test_missing_raw_path_uses_the_strict_check(
        self, upstream: RecordingUpstream, recording_client: AsyncClient, monkeypatch
    ):
        import src.api.api as api_module

        original = api_module.raw_request_suffix

        def without_raw_path(request, decoded_path):
            request.scope.pop("raw_path", None)
            return original(request, decoded_path)

        monkeypatch.setattr(api_module, "raw_request_suffix", without_raw_path)

        allowed = await recording_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/plain/path")
        assert allowed.status_code == 200

        # A literal percent survives decoding, so the original encoding can no
        # longer be reconstructed and the request is refused.
        refused = await recording_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/a%25b")
        assert refused.status_code == 400

        hidden = await recording_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/.hidden")
        assert hidden.status_code == 400


class TestNormalisationIsNotTrusted:
    """httpx collapses literal dot segments; the prefix check must still hold"""

    def test_httpx_collapses_literal_dot_segments(self):
        url = httpx.URL("http://up:8080/base").copy_with(raw_path=b"/base/../../admin")
        assert url.raw_path == b"/admin"

    def test_httpx_keeps_encoded_dot_segments(self):
        url = httpx.URL("http://up:8080/base").copy_with(raw_path=b"/base/%2e%2e/x")
        assert url.raw_path == b"/base/%2e%2e/x"

    def test_prefix_check_runs_after_normalisation(self):
        proxy = ServiceProxy.__new__(ServiceProxy)
        service = {"url": "http://upstream:8080/base"}

        with pytest.raises(UnsafeProxyPathError):
            proxy.build_target_url(service, b"/../../admin", b"")

        assert (
            str(proxy.build_target_url(service, b"/a/../b", b""))
            == "http://upstream:8080/base/b"
        )


class TestDotSegmentsWithPathParameters:
    """A `;parameters` suffix must not hide a dot segment from the check.

    Servlet style upstreams strip the path parameters of a segment before they
    normalise the path, so `..;` and `..;jsessionid=1` are dot segments there.
    Accepting them would hand such an upstream a way out of the registered base
    path, and past the blocked upstream path list on the way.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "suffix",
        [
            "x/..;/metrics",
            "x/..;foo/metrics",
            "x/.;/y",
            "..;/admin",
            "x/..%3b/metrics",
            "x/..%3B/metrics",
            "x/.. ;/metrics",
        ],
    )
    async def test_dot_segments_with_parameters_are_rejected(
        self, upstream: RecordingUpstream, recording_client: AsyncClient, suffix: str
    ):
        response = await recording_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/{suffix}")
        assert response.status_code == 400
        assert upstream.requests == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("suffix", ["items;v=1", "a/b;charset=utf8/c", "x;"])
    async def test_ordinary_path_parameters_still_reach_the_upstream(
        self, upstream: RecordingUpstream, recording_client: AsyncClient, suffix: str
    ):
        response = await recording_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/{suffix}")
        assert response.status_code == 200
        assert len(upstream.requests) == 1

    @pytest.mark.parametrize("path", ["x/..;/y", "..;jsessionid=1/y", "x/.;/y"])
    def test_unit_check_rejects_parameterised_dot_segments(self, path: str):
        from src.api.api import PathExtractionError, reject_unsafe_path

        with pytest.raises(PathExtractionError):
            reject_unsafe_path(("/" + path).encode(), path)

    def test_build_target_url_refuses_a_parameterised_dot_segment(self):
        """The proxy must not depend on the route handler alone."""
        proxy = ServiceProxy.__new__(ServiceProxy)
        service = {"url": "http://upstream:8080/base"}

        with pytest.raises(UnsafeProxyPathError):
            proxy.build_target_url(service, b"/..;/..;/admin", b"")

        assert (
            str(proxy.build_target_url(service, b"/items;v=1", b""))
            == "http://upstream:8080/base/items;v=1"
        )


class TestMultiplyEncodedPaths:
    """Every decoding round of a path is checked, not only the first.

    A gateway that decodes once forwards `%252e` as the literal text `%2e`. An
    upstream or an intermediate proxy that decodes the request a second time
    turns that back into a dot segment, so the whole family has to be refused
    here instead of trusting the upstream to stop at one round.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "suffix",
        [
            "%252e%252e/admin",
            "%252E%252E/admin",
            "a%252fb",
            "a%255cb",
            "%25252e%25252e/admin",
            "a%2525252fb",
        ],
    )
    async def test_multiply_encoded_separators_are_rejected(
        self, upstream: RecordingUpstream, recording_client: AsyncClient, suffix: str
    ):
        response = await recording_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/{suffix}")
        assert response.status_code == 400
        assert upstream.requests == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "suffix, expected_path",
        [
            ("files/100%25", "/files/100%"),
            ("files/a%25b", "/files/a%b"),
            ("files/%25", "/files/%"),
            ("a%20b/c", "/a b/c"),
        ],
    )
    async def test_a_literal_percent_still_reaches_the_upstream(
        self,
        upstream: RecordingUpstream,
        recording_client: AsyncClient,
        suffix: str,
        expected_path: str,
    ):
        response = await recording_client.get(f"/api/v1/{ECHO_SERVICE_NAME}/{suffix}")
        assert response.status_code == 200
        assert response.json()["path"] == expected_path

    def test_encoding_nested_beyond_the_bound_is_rejected(self):
        """An unbounded loop is a denial of service, so the bound refuses."""
        from src.api.api import PathExtractionError, reject_unsafe_path
        from src.core.pathpolicy import MAX_PATH_DECODING_ROUNDS

        nested = "%25" * (MAX_PATH_DECODING_ROUNDS + 2) + "2e"
        with pytest.raises(PathExtractionError):
            reject_unsafe_path(("/" + nested).encode(), nested)


class TestUpstreamRedirectsAreNotFollowed:
    """Following a 3xx would let an upstream reach past the gateway's checks"""

    @pytest.mark.asyncio
    async def test_the_shared_client_does_not_follow_redirects(self):
        client = create_http_client()
        try:
            assert client.follow_redirects is False
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_a_redirect_to_a_blocked_path_is_handed_to_the_caller(self):
        """The 302 is returned as is, so the block list is never bypassed."""
        seen: List[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if request.url.path == "/redirect-me":
                return httpx.Response(302, headers={"location": "/metrics"})
            return httpx.Response(200, content=b"secret-metrics")

        async for gateway_client in make_gateway_client(httpx.MockTransport(handler)):
            response = await gateway_client.get(
                f"/api/v1/{ECHO_SERVICE_NAME}/redirect-me",
                follow_redirects=False,
            )

        assert response.status_code == 302
        assert response.headers["location"] == "/metrics"
        assert [request.url.path for request in seen] == ["/redirect-me"]


@pytest.mark.asyncio
async def test_chunked_body_stops_reading_at_limit(monkeypatch):
    from types import SimpleNamespace

    from fastapi import HTTPException, Request

    from src.api.api import proxy_request
    from src.core.config import settings

    monkeypatch.setattr(settings, "MAX_REQUEST_BODY_BYTES", 4)
    received = []

    async def receive():
        received.append(5)
        return {
            "type": "http.request",
            "body": b"x" * 5,
            "more_body": len(received) < 3,
        }

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/test/upload",
            "raw_path": b"/api/v1/test/upload",
            "query_string": b"",
            "headers": [],
        },
        receive,
    )
    proxy = SimpleNamespace(resolve=lambda name: {"name": name})
    with pytest.raises(HTTPException) as exc:
        await proxy_request("test", "upload", request, proxy)
    assert exc.value.status_code == 413
    assert len(received) == 1
