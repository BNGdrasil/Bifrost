# --------------------------------------------------------------------------
# Service registry and proxy functionality for the API Gateway service
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import asyncio
from http.cookiejar import CookieJar
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import httpx
import structlog
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from src.core.config import settings
from src.core.database import SessionLocal
from src.crud.service import get_all_active_services, update_service_health

logger = structlog.get_logger()

# Headers that are meaningful for a single transport hop only and must never be
# copied between the client connection and the upstream connection.
HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)

# Request headers that are rewritten or recalculated by this gateway.
DROPPED_REQUEST_HEADERS = HOP_BY_HOP_HEADERS | {
    "host",
    "content-length",
    "accept-encoding",
}

# Response headers that would contradict the decoded body handed to Starlette.
DROPPED_RESPONSE_HEADERS = HOP_BY_HOP_HEADERS | {
    "content-length",
    "content-encoding",
}


class NoStoreCookieJar(CookieJar):
    """Cookie jar that never stores anything.

    The gateway shares one HTTP client across all callers. A stock jar would
    keep an upstream Set-Cookie and replay it as a Cookie header on the next
    unrelated request, leaking one caller's session to another. Inbound Cookie
    headers are still forwarded verbatim by the proxy.
    """

    def extract_cookies(self, response: Any, request: Any) -> None:
        return None

    def set_cookie(self, cookie: Any) -> None:
        return None

    def set_cookie_if_ok(self, cookie: Any, request: Any) -> None:
        return None

    def add_cookie_header(self, request: Any) -> None:
        return None


def connection_tokens(items: Sequence[Tuple[str, str]]) -> Set[str]:
    """Header names listed by the Connection header of this message.

    RFC 9110 lets a message nominate additional connection-scoped headers, and
    those must not be forwarded either.
    """
    tokens: Set[str] = set()
    for key, value in items:
        if key.lower() != "connection":
            continue
        for token in value.split(","):
            name = token.strip().lower()
            if name and name != "close" and name != "keep-alive":
                tokens.add(name)
    return tokens


def _filter(
    items: Sequence[Tuple[str, str]], dropped: Iterable[str]
) -> List[Tuple[str, str]]:
    drop = set(dropped) | connection_tokens(items)
    return [(key, value) for key, value in items if key.lower() not in drop]


class ServiceNotFoundError(LookupError):
    """Raised when a request targets a service that is not registered."""


class UnsafeProxyPathError(ValueError):
    """Raised when a request path cannot be forwarded safely."""


class RegistryLoadError(RuntimeError):
    """Raised when the registry cannot be loaded from the database."""


def filter_request_headers(
    items: Sequence[Tuple[str, str]],
) -> List[Tuple[str, str]]:
    """Drop hop-by-hop and rewritten headers from an inbound request."""
    return _filter(items, DROPPED_REQUEST_HEADERS)


def filter_response_headers(
    items: Sequence[Tuple[str, str]],
) -> List[Tuple[str, str]]:
    """Drop hop-by-hop and body-describing headers from an upstream response."""
    return _filter(items, DROPPED_RESPONSE_HEADERS)


def create_http_client(
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> httpx.AsyncClient:
    """Create the single shared HTTP client used for the whole process.

    The client is shared by every caller, so it must not accumulate cookies.
    The transport argument exists so that tests exercise this exact
    configuration against an in-process upstream.
    """
    limits = httpx.Limits(max_connections=settings.PROXY_MAX_CONNECTIONS)
    return httpx.AsyncClient(
        timeout=settings.PROXY_TIMEOUT_SECONDS,
        limits=limits,
        follow_redirects=False,
        cookies=NoStoreCookieJar(),
        transport=transport,
    )


class ServiceRegistry:
    """In-memory snapshot of the routing table stored in the database.

    The snapshot is replaced atomically. A failed reload keeps the last known
    good snapshot and marks the registry as not ready so that readiness probes
    report the degraded state.
    """

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._services: Dict[str, Dict[str, Any]] = {}
        self._owns_client = http_client is None
        self.http_client = (
            http_client if http_client is not None else create_http_client()
        )
        self.ready = False
        self.last_error: Optional[str] = None
        # Reloads are serialised so that two concurrent admin writes cannot
        # interleave partial snapshots.
        self._reload_lock = asyncio.Lock()
        # Incremented on every successful swap. A health probe started against
        # an older snapshot must not write its result into a newer one.
        self._generation = 0

    @property
    def generation(self) -> int:
        """Snapshot generation, incremented on every successful load."""
        return self._generation

    @property
    def services(self) -> Dict[str, Dict[str, Any]]:
        """Current snapshot. The returned mapping is a copy."""
        return dict(self._services)

    def _build_snapshot(self, db_session: Session) -> Dict[str, Dict[str, Any]]:
        snapshot: Dict[str, Dict[str, Any]] = {}
        for service in get_all_active_services(db_session):
            service_name: str = service.name  # type: ignore[assignment]
            snapshot[service_name] = {
                "id": service.id,
                "name": service_name,
                "url": service.url,
                "health_check": service.health_check_path or "/health",
                "timeout": service.timeout_seconds or settings.PROXY_TIMEOUT_SECONDS,
                "rate_limit": service.rate_limit_per_minute,
                "display_name": service.display_name,
                "description": service.description,
                "service_metadata": service.service_metadata,
                "health_status": service.health_status or "unknown",
                "last_health_check": service.last_health_check,
            }
        return snapshot

    def _load_snapshot_sync(
        self, db_session: Optional[Session] = None
    ) -> Dict[str, Dict[str, Any]]:
        if db_session is not None:
            return self._build_snapshot(db_session)
        with SessionLocal() as session:
            return self._build_snapshot(session)

    async def _load(self, db_session: Optional[Session] = None) -> None:
        """Load a complete snapshot and swap it in atomically."""
        async with self._reload_lock:
            if db_session is not None:
                snapshot = await run_in_threadpool(self._build_snapshot, db_session)
            else:
                snapshot = await run_in_threadpool(self._load_snapshot_sync, None)
            self._services = snapshot
            self._generation += 1
            self.ready = True
            self.last_error = None
        logger.info(
            "Loaded services from database",
            count=len(snapshot),
            generation=self._generation,
        )

    async def initialize(self, db_session: Optional[Session] = None) -> bool:
        """Load the registry at startup.

        Failures are logged and reported through the ready flag instead of
        crashing the process. Any previously loaded snapshot is kept so that
        existing routes keep working in a degraded state.
        """
        try:
            await self._load(db_session=db_session)
            return True
        except Exception as exc:  # noqa: BLE001 - startup must not crash here
            self.ready = False
            self.last_error = str(exc)
            logger.error(
                "Failed to initialize service registry from database",
                error=str(exc),
                retained_services=len(self._services),
                exc_info=True,
            )
            return False

    async def reload(self, db_session: Optional[Session] = None) -> None:
        """Reload the registry and propagate failures to the caller."""
        try:
            await self._load(db_session=db_session)
        except Exception as exc:  # noqa: BLE001 - converted to a typed error
            self.ready = False
            self.last_error = str(exc)
            logger.error(
                "Failed to reload service registry",
                error=str(exc),
                retained_services=len(self._services),
                exc_info=True,
            )
            raise RegistryLoadError(str(exc)) from exc
        logger.info("Service registry reloaded from database")

    async def cleanup(self) -> None:
        """Close resources owned by this registry."""
        if self._owns_client:
            await self.http_client.aclose()

    def get_service(self, service_name: str) -> Optional[Dict[str, Any]]:
        """Get service configuration by name"""
        return self._services.get(service_name)

    def list_services(self) -> Dict[str, Dict[str, Any]]:
        """List all registered services with their internal configuration"""
        return self.services

    def list_public_services(self) -> List[Dict[str, Any]]:
        """List registered services without internal routing details."""
        return [
            {
                "name": config["name"],
                "display_name": config.get("display_name"),
                "description": config.get("description"),
                "health_status": config.get("health_status") or "unknown",
                "last_health_check": config.get("last_health_check"),
            }
            for config in sorted(
                self._services.values(), key=lambda item: str(item["name"])
            )
        ]

    def _record_health_sync(self, service_id: int, health_status: str) -> None:
        with SessionLocal() as db:
            update_service_health(db, service_id, health_status)

    async def health_check(self, service_name: str) -> bool:
        """Probe a service and persist the result. Admin triggered only."""
        service = self.get_service(service_name)
        if not service:
            return False

        probe_generation = self._generation
        health_status = "unhealthy"
        is_healthy = False
        try:
            health_url = f"{service['url']}{service.get('health_check', '/health')}"
            response = await self.http_client.get(
                health_url, timeout=service.get("timeout", 30)
            )
            is_healthy = bool(response.status_code == 200)
            health_status = "healthy" if is_healthy else "unhealthy"
        except Exception as exc:  # noqa: BLE001 - any failure means unhealthy
            logger.error(
                "Health check failed", service_name=service_name, error=str(exc)
            )

        try:
            await run_in_threadpool(
                self._record_health_sync, service["id"], health_status
            )
        except Exception as exc:  # noqa: BLE001 - reporting must not raise
            logger.error(
                "Failed to persist health status",
                service_name=service_name,
                error=str(exc),
            )
        else:
            # Only refresh the snapshot that was probed. A reload that landed
            # while the probe was in flight already carries fresh values.
            if probe_generation == self._generation:
                cached = self._services.get(service_name)
                if cached is not None:
                    cached["health_status"] = health_status

        logger.info(
            "Health check completed", service_name=service_name, status=health_status
        )
        return is_healthy


class ServiceProxy:
    """Buffered reverse proxy for registered upstream services.

    The whole request and response body is held in memory. Streaming responses
    and server sent events are out of scope; request bodies are capped by
    ``MAX_REQUEST_BODY_BYTES`` and upstream responses are read in full.
    """

    def __init__(
        self, service_registry: ServiceRegistry, http_client: httpx.AsyncClient
    ) -> None:
        self.service_registry = service_registry
        self.http_client = http_client

    def resolve(self, service_name: str) -> Dict[str, Any]:
        service = self.service_registry.get_service(service_name)
        if not service:
            raise ServiceNotFoundError(f"Service '{service_name}' not found")
        return service

    def build_target_url(
        self, service: Dict[str, Any], raw_suffix: bytes, raw_query: bytes
    ) -> httpx.URL:
        """Build the upstream URL from raw bytes.

        The suffix is taken from the original request line, so percent encoded
        characters keep their encoding and are never re-interpreted as path,
        query or fragment delimiters.

        httpx does resolve literal dot segments while building the URL, so
        `/base/../x` becomes `/x`. That normalisation is not relied on for
        safety: the check below runs on the resolved path, so a suffix that
        escapes the registered base path is rejected whether httpx collapsed
        it or left it alone. Encoded dot segments survive normalisation and
        are refused earlier, by the route handler.
        """
        base = httpx.URL(str(service["url"]))
        base_path = base.raw_path.split(b"?", 1)[0].rstrip(b"/")
        suffix = raw_suffix if raw_suffix.startswith(b"/") else b"/" + raw_suffix
        raw_path = base_path + suffix
        if raw_query:
            raw_path = raw_path + b"?" + raw_query
        url = base.copy_with(raw_path=raw_path)

        # The resolved path, after any dot segment collapsing httpx applied,
        # must still live under the registered base path.
        final_path = url.raw_path.split(b"?", 1)[0]
        if base_path and not (
            final_path == base_path or final_path.startswith(base_path + b"/")
        ):
            raise UnsafeProxyPathError(
                "Resolved upstream path escapes the registered base path"
            )
        return url

    async def forward_request(
        self,
        service_name: str,
        method: str,
        raw_suffix: bytes,
        headers: Sequence[Tuple[str, str]],
        body: Optional[bytes] = None,
        raw_query: bytes = b"",
    ) -> httpx.Response:
        """Forward a request to a registered upstream service."""
        service = self.resolve(service_name)
        target_url = self.build_target_url(service, raw_suffix, raw_query)

        forward_headers = filter_request_headers(headers)
        # httpx decodes compressed responses, so ask upstream for identity and
        # let Starlette recompute the body framing headers.
        forward_headers.append(("accept-encoding", "identity"))

        response = await self.http_client.request(
            method=method,
            url=target_url,
            headers=forward_headers,
            content=body,
            timeout=service.get("timeout", settings.PROXY_TIMEOUT_SECONDS),
        )

        logger.info(
            "Request forwarded",
            service_name=service_name,
            method=method,
            path=target_url.path,
            status_code=response.status_code,
        )
        return response
