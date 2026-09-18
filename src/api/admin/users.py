# --------------------------------------------------------------------------
# Admin Users API - proxy to the Bidar auth server
#
# @author bnbong bbbong9@gmail.com
#
# User records live in the Bidar auth server, which owns every business rule
# (duplicate detection, last administrator protection, self deletion). Bifrost
# enforces its own role check first, then forwards the caller's Authorization
# header so the auth server applies the authoritative check as well, and
# returns the auth server status and detail unchanged.
# --------------------------------------------------------------------------
from typing import Any, Dict, Optional

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from src.core.config import settings
from src.core.permissions import require_admin, require_super_admin
from src.schemas.user import UserCreateRequest, UserUpdateRequest

router = APIRouter()
logger = structlog.get_logger()

# The auth server is a separate process on the same private network, so a
# short timeout is enough and keeps the admin UI responsive.
AUTH_SERVER_TIMEOUT_SECONDS = 10.0


def _base_url() -> str:
    """Root of the auth server user management API."""
    path = settings.AUTH_SERVER_USERS_PATH.strip().strip("/")
    root = settings.AUTH_SERVER_URL.rstrip("/")
    return f"{root}/{path}" if path else root


def _collection_url() -> str:
    """Auth server collection endpoint used for reads and item operations."""
    return f"{_base_url()}/users"


def _item_url(user_id: int, suffix: str = "") -> str:
    return f"{_collection_url()}/{user_id}{suffix}"


def _extract_detail(response: httpx.Response) -> Any:
    """Return the auth server error detail unchanged when it sends one."""
    try:
        payload = response.json()
    except ValueError:
        return response.text[:500]
    if isinstance(payload, dict) and "detail" in payload:
        return payload["detail"]
    return payload


async def _call_auth_server(
    request: Request,
    method: str,
    url: str,
    *,
    params: Optional[str] = None,
    json_body: Optional[Dict[str, Any]] = None,
) -> httpx.Response:
    """Send one request to the auth server with the caller's credentials."""
    client: Optional[httpx.AsyncClient] = getattr(
        request.app.state, "http_client", None
    )
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="HTTP client not initialized",
        )

    headers = {"Authorization": request.headers.get("authorization", "")}
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        headers["X-Request-ID"] = str(request_id)

    target = httpx.URL(url)
    if params:
        target = target.copy_with(query=params.encode("utf-8"))

    try:
        return await client.request(
            method,
            target,
            headers=headers,
            json=json_body,
            timeout=AUTH_SERVER_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as exc:
        logger.warning("Auth server timed out", url=url, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Auth server unavailable: timed out after "
            f"{AUTH_SERVER_TIMEOUT_SECONDS:.0f}s",
        )
    except httpx.RequestError as exc:
        logger.warning("Auth server unreachable", url=url, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Auth server unavailable: {exc}",
        )


def _relay(response: httpx.Response) -> Response:
    """Turn an auth server response into the gateway response.

    Client errors keep the auth server status and detail so that duplicate,
    validation and last-administrator responses survive the hop. Auth server
    faults become 502 because the gateway itself is not at fault.
    """
    if response.status_code >= 500:
        logger.error(
            "Auth server returned a server error",
            status_code=response.status_code,
            body=response.text[:200],
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Auth server error ({response.status_code})",
        )

    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail=_extract_detail(response),
        )

    if response.status_code == status.HTTP_204_NO_CONTENT or not response.content:
        return Response(status_code=response.status_code)

    try:
        payload = response.json()
    except ValueError:
        return Response(
            content=response.content,
            status_code=response.status_code,
            media_type=response.headers.get("content-type"),
        )
    return JSONResponse(content=payload, status_code=response.status_code)


@router.get("/")
@require_admin
async def list_users(request: Request) -> Response:
    """List users (admin or above).

    Query parameters are forwarded verbatim. Returns the auth server's
    UserRead array unchanged.
    """
    response = await _call_auth_server(
        request, "GET", _collection_url(), params=request.url.query
    )
    return _relay(response)


@router.get("/{user_id}")
@require_admin
async def get_user(request: Request, user_id: int) -> Response:
    """Get one user (admin or above). 404 when the auth server has no such user."""
    response = await _call_auth_server(request, "GET", _item_url(user_id))
    return _relay(response)


@router.post("/", status_code=status.HTTP_201_CREATED)
@require_super_admin
async def create_user(request: Request, payload: UserCreateRequest) -> Response:
    """Create a user (super admin only).

    The auth server answers 400 for a duplicate and 422 for invalid input;
    both are returned unchanged.
    """
    response = await _call_auth_server(
        request,
        "POST",
        _base_url(),
        json_body=payload.model_dump(exclude_unset=True),
    )
    return _relay(response)


@router.patch("/{user_id}")
@require_super_admin
async def update_user(
    request: Request, user_id: int, payload: UserUpdateRequest
) -> Response:
    """Update a user (super admin only).

    The auth server answers 409 when the change would remove the last super
    admin; that response is returned unchanged.
    """
    response = await _call_auth_server(
        request,
        "PATCH",
        _item_url(user_id),
        json_body=payload.model_dump(exclude_unset=True),
    )
    return _relay(response)


@router.put("/{user_id}/activate")
@require_admin
async def activate_user(request: Request, user_id: int) -> Response:
    """Activate a user account (admin or above)."""
    response = await _call_auth_server(request, "PUT", _item_url(user_id, "/activate"))
    return _relay(response)


@router.put("/{user_id}/deactivate")
@require_admin
async def deactivate_user(request: Request, user_id: int) -> Response:
    """Deactivate a user account (admin or above)."""
    response = await _call_auth_server(
        request, "PUT", _item_url(user_id, "/deactivate")
    )
    return _relay(response)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_super_admin
async def delete_user(request: Request, user_id: int) -> Response:
    """Delete a user (super admin only).

    The auth server answers 409 for the last administrator and 400 for self
    deletion; both are returned unchanged.
    """
    response = await _call_auth_server(request, "DELETE", _item_url(user_id))
    return _relay(response)


@router.post("/{user_id}/reset-password")
@require_admin
async def reset_user_password(request: Request, user_id: int) -> Dict[str, Any]:
    """Not implemented. Password reset is owned by the auth server."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "Password reset is not implemented in Bifrost. "
            "Use the auth server password reset flow instead."
        ),
    )
