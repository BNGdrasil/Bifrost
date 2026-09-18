# --------------------------------------------------------------------------
# Router for the API Gateway service
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import uuid
from typing import Any, Dict, Tuple
from urllib.parse import unquote

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from src.core.config import settings
from src.core.metrics import UNKNOWN_SERVICE
from src.schemas.service import ServicePublic
from src.services.services import (
    ServiceNotFoundError,
    ServiceProxy,
    ServiceRegistry,
    UnsafeProxyPathError,
    filter_response_headers,
)

logger = structlog.get_logger()
router = APIRouter()

PROXY_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]

# Spelled out to stay stable across Starlette renames of the 413 constant.
HTTP_413_CONTENT_TOO_LARGE = 413

# Percent encodings that could reintroduce a path separator or a dot segment
# after the server already decoded the path once.
FORBIDDEN_PATH_ENCODINGS = (b"%2e", b"%2f", b"%5c")

# A backslash is a path separator on some upstream stacks, so it must never
# reach one, encoded or not.
BACKSLASH = "\\"


class PathExtractionError(ValueError):
    """Raised when the original request path cannot be recovered safely."""


def raw_request_suffix(request: Request, decoded_path: str) -> Tuple[bytes, bool]:
    """Recover the still-encoded part of the path that follows the route prefix.

    Starlette hands the handler an already decoded path parameter. Rebuilding
    the upstream URL from that decoded value lets `%2e%2e` turn into a real
    dot segment and escape the registered base path, so the bytes of the
    original request line are used instead.

    The prefix length is derived by comparing the decoded scope path with the
    decoded path parameter, then the same number of leading segments is
    dropped from the raw bytes. The result must decode back to exactly what
    the router matched, otherwise the request is rejected rather than guessed.

    Returns the suffix and whether it had to be rebuilt from the already
    decoded path because the server did not provide raw_path. The caller
    applies a stricter check in that case, since the original encoding can no
    longer be told apart from literal characters.
    """
    from_fallback = False
    raw_path = request.scope.get("raw_path")
    if not raw_path:
        from_fallback = True
        raw_path = request.url.path.encode("latin-1")
    raw_path = raw_path.split(b"?", 1)[0]

    root_path = (request.scope.get("root_path") or "").encode("latin-1")
    if root_path and raw_path.startswith(root_path):
        raw_path = raw_path[len(root_path) :]

    scope_path = request.scope.get("path") or request.url.path
    scope_segments = scope_path.split("/")
    matched_segments = decoded_path.split("/")
    prefix_segments = len(scope_segments) - len(matched_segments)
    if prefix_segments < 1:
        raise PathExtractionError("Request path is shorter than the route prefix")

    raw_segments = raw_path.split(b"/")
    if len(raw_segments) < prefix_segments:
        raise PathExtractionError("Raw request path does not match the route prefix")

    suffix = b"/" + b"/".join(raw_segments[prefix_segments:])

    expected = "/" + decoded_path
    if unquote(suffix.decode("latin-1")) != expected:
        raise PathExtractionError("Encoded request path does not match the route")

    return suffix, from_fallback


def reject_unsafe_path(
    raw_suffix: bytes, decoded_path: str, from_fallback: bool = False
) -> None:
    """Refuse dot segments and path separators in a proxied path."""
    lowered = raw_suffix.lower()
    for encoding in FORBIDDEN_PATH_ENCODINGS:
        if encoding in lowered:
            raise PathExtractionError(
                "Encoded path separators and dot segments are not accepted"
            )
    if b"\\" in raw_suffix:
        raise PathExtractionError("Backslashes are not accepted in a proxied path")

    for segment in decoded_path.split("/"):
        if segment in (".", ".."):
            raise PathExtractionError("Relative path segments are not accepted")
        if BACKSLASH in segment:
            raise PathExtractionError("Backslashes are not accepted in a proxied path")

    if from_fallback:
        # Without raw_path the original encoding is unknown, so anything that
        # could have been an escape is refused instead of guessed.
        if "%" in decoded_path:
            raise PathExtractionError(
                "Percent encoded characters cannot be verified for this request"
            )
        for segment in decoded_path.split("/"):
            if segment.startswith("."):
                raise PathExtractionError(
                    "Dot segments cannot be verified for this request"
                )


async def get_service_registry(request: Request) -> ServiceRegistry:
    """Get service registry from application state"""
    registry = getattr(request.app.state, "service_registry", None)
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service registry not initialized",
        )
    return registry  # type: ignore[no-any-return]


async def get_service_proxy(request: Request) -> ServiceProxy:
    """Get the process wide service proxy from application state"""
    proxy = getattr(request.app.state, "service_proxy", None)
    if proxy is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service proxy not initialized",
        )
    return proxy  # type: ignore[no-any-return]


@router.get("/services")
async def list_services(
    service_registry: ServiceRegistry = Depends(get_service_registry),
) -> Dict[str, Any]:
    """List registered services.

    This is a public endpoint, so internal routing details such as the upstream
    URL, timeouts, rate limits and metadata are not exposed. Use the admin API
    for the full record.
    """
    services = [
        ServicePublic(**item) for item in service_registry.list_public_services()
    ]
    return {"services": services, "count": len(services)}


@router.get("/services/{service_name}/health", response_model=ServicePublic)
async def service_health(
    service_name: str,
    service_registry: ServiceRegistry = Depends(get_service_registry),
) -> ServicePublic:
    """Return the last recorded health status of a service.

    This endpoint never calls the upstream service and never writes to the
    database, so it cannot be used as an unauthenticated internal probe. Use
    the admin API to trigger an actual health check.
    """
    service = service_registry.get_service(service_name)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service '{service_name}' not found",
        )
    return ServicePublic(
        name=service["name"],
        display_name=service.get("display_name"),
        description=service.get("description"),
        health_status=service.get("health_status") or "unknown",
        last_health_check=service.get("last_health_check"),
    )


# Catch-all proxy route - MUST be last to avoid conflicts with specific routes
# Excluded from the OpenAPI schema: a single wildcard entry documents nothing
# useful for clients, and a multi-method catch-all route makes FastAPI emit
# duplicate operation id warnings while rendering the docs page.
@router.api_route(
    "/{service_name}/{path:path}",
    methods=PROXY_METHODS,
    include_in_schema=False,
)
async def proxy_request(
    service_name: str,
    path: str,
    request: Request,
    service_proxy: ServiceProxy = Depends(get_service_proxy),
) -> Response:
    """Proxy a request to a registered backend service.

    This is a buffered proxy: the request body and the upstream response body
    are fully read into memory. Real streaming and server sent events are out
    of scope. Request bodies larger than MAX_REQUEST_BODY_BYTES are rejected
    with 413.
    """
    request.state.proxy_service = UNKNOWN_SERVICE
    try:
        service = service_proxy.resolve(service_name)
    except ServiceNotFoundError:
        logger.info("Service not found", service_name=service_name)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service '{service_name}' not found",
        )
    request.state.proxy_service = service["name"]

    try:
        raw_suffix, from_fallback = raw_request_suffix(request, path)
        reject_unsafe_path(raw_suffix, path, from_fallback=from_fallback)
    except PathExtractionError as exc:
        logger.warning("Rejected proxy path", service_name=service_name, error=str(exc))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            if int(declared_length) > settings.MAX_REQUEST_BODY_BYTES:
                raise HTTPException(
                    status_code=HTTP_413_CONTENT_TOO_LARGE,
                    detail="Request body too large",
                )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Content-Length header",
            )

    body = await request.body()
    if len(body) > settings.MAX_REQUEST_BODY_BYTES:
        raise HTTPException(
            status_code=HTTP_413_CONTENT_TOO_LARGE,
            detail="Request body too large",
        )

    request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex
    client_host = request.client.host if request.client else ""
    existing_forwarded_for = request.headers.get("x-forwarded-for")
    forwarded_for = (
        f"{existing_forwarded_for}, {client_host}"
        if existing_forwarded_for and client_host
        else (existing_forwarded_for or client_host)
    )

    headers = list(request.headers.items())
    if forwarded_for:
        headers.append(("x-forwarded-for", forwarded_for))
    headers.append(
        (
            "x-forwarded-proto",
            request.headers.get("x-forwarded-proto") or request.url.scheme,
        )
    )
    headers.append(("x-request-id", request_id))

    try:
        upstream = await service_proxy.forward_request(
            service_name=service_name,
            method=request.method,
            raw_suffix=raw_suffix,
            headers=headers,
            body=body if body else None,
            raw_query=request.scope.get("query_string", b""),
        )
    except UnsafeProxyPathError as exc:
        logger.warning(
            "Rejected unsafe proxy path", service_name=service_name, error=str(exc)
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except httpx.TimeoutException as exc:
        logger.warning("Upstream timeout", service_name=service_name, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Upstream service '{service_name}' timed out",
        )
    except httpx.RequestError as exc:
        logger.warning(
            "Upstream connection error", service_name=service_name, error=str(exc)
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Upstream service '{service_name}' is unreachable",
        )

    response = Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )
    for key, value in filter_response_headers(list(upstream.headers.multi_items())):
        if key.lower() == "content-type":
            continue
        response.headers.append(key, value)
    return response
