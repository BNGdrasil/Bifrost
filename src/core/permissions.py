# --------------------------------------------------------------------------
# permissions module - RBAC decorators and utilities
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
from functools import wraps
from typing import Callable

import httpx
from fastapi import HTTPException, Request, status

from src.core.config import settings


async def verify_role_with_auth_server(token: str, required_role: str) -> dict:
    """Verify user role with Bidar Auth Server.

    Args:
        token: JWT access token
        required_role: Minimum role required

    Returns:
        dict: User information from auth server

    Raises:
        HTTPException: If verification fails
    """
    auth_server_url = settings.AUTH_SERVER_URL

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{auth_server_url}/rbac/verify-permission",
                json={"required_role": required_role},
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0,
            )

            if response.status_code == 401:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Unauthorized - Invalid or expired token",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            elif response.status_code == 403:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Forbidden - Insufficient permissions. Required role: {required_role}",
                )
            elif response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to verify permissions with auth server",
                )

            return response.json()  # type: ignore[no-any-return]
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Auth server unavailable: {str(e)}",
            ) from e


def require_role(required_role: str = "admin") -> Callable:
    """Decorator to require specific role for endpoint access.

    Usage:
        @router.get("/admin/api/users")
        @require_role("admin")
        async def list_users(request: Request):
            ...

    Args:
        required_role: Minimum role required (user, moderator, admin, super_admin)

    Returns:
        Decorator function
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract request object from kwargs
            request: Request | None = kwargs.get("request")
            if not request:
                # Try to find request in args (if it's a positional argument)
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break

            if not request:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Request object not found. Make sure to include 'request: Request' parameter.",
                )

            # Extract token from Authorization header
            authorization = request.headers.get("Authorization")
            if not authorization or not authorization.startswith("Bearer "):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Missing or invalid authorization header",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            token = authorization.replace("Bearer ", "")

            # Verify role with auth server
            user_info = await verify_role_with_auth_server(token, required_role)

            # Add user info to request state for access in endpoint
            request.state.user = user_info

            return await func(*args, **kwargs)

        return wrapper

    return decorator


def require_admin(func: Callable) -> Callable:
    """Shorthand decorator for @require_role("admin").

    Usage:
        @router.get("/admin/endpoint")
        @require_admin
        async def admin_endpoint(request: Request):
            ...
    """
    decorated: Callable = require_role("admin")(func)
    return decorated


def require_super_admin(func: Callable) -> Callable:
    """Shorthand decorator for @require_role("super_admin").

    Usage:
        @router.get("/super-admin/endpoint")
        @require_super_admin
        async def super_admin_endpoint(request: Request):
            ...
    """
    decorated: Callable = require_role("super_admin")(func)
    return decorated
