# --------------------------------------------------------------------------
# Admin Users API - User management endpoints
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
from fastapi import APIRouter, Request
from pydantic import BaseModel

from src.core.permissions import require_admin, require_super_admin

router = APIRouter()


class UserListResponse(BaseModel):
    """Response model for user list."""

    total: int
    users: list[dict]


@router.get("/", response_model=UserListResponse)
@require_admin
async def list_users(
    request: Request, skip: int = 0, limit: int = 100
) -> UserListResponse:
    """List all users (admin only).

    Args:
        request: FastAPI Request object (injected)
        skip: Number of users to skip
        limit: Maximum number of users to return

    Returns:
        UserListResponse: List of users
    """
    # Access authenticated user info from request.state
    current_user = request.state.user

    # TODO: Implement actual user fetching from database via Auth Server
    # For now, return mock data
    return UserListResponse(
        total=2,
        users=[
            {
                "id": 1,
                "username": "admin",
                "email": "admin@bnbong.xyz",
                "role": "admin",
                "is_active": True,
            },
            {
                "id": 2,
                "username": "user",
                "email": "user@bnbong.xyz",
                "role": "user",
                "is_active": True,
            },
        ],
    )


@router.get("/{user_id}")
@require_admin
async def get_user(request: Request, user_id: int) -> dict:
    """Get specific user details (admin only).

    Args:
        request: FastAPI Request object
        user_id: ID of the user to retrieve

    Returns:
        dict: User information
    """
    # TODO: Implement actual user fetching
    return {
        "id": user_id,
        "username": f"user{user_id}",
        "email": f"user{user_id}@bnbong.xyz",
        "role": "user",
        "is_active": True,
    }


@router.delete("/{user_id}")
@require_super_admin
async def delete_user(request: Request, user_id: int) -> dict:
    """Delete a user (super admin only).

    Args:
        request: FastAPI Request object
        user_id: ID of the user to delete

    Returns:
        dict: Deletion confirmation
    """
    # TODO: Implement actual user deletion via Auth Server
    return {"message": f"User {user_id} deleted successfully", "deleted_id": user_id}


@router.post("/{user_id}/reset-password")
@require_admin
async def reset_user_password(request: Request, user_id: int) -> dict:
    """Reset user password (admin only).

    Args:
        request: FastAPI Request object
        user_id: ID of the user

    Returns:
        dict: Password reset confirmation
    """
    # TODO: Implement password reset via Auth Server
    return {
        "message": f"Password reset email sent to user {user_id}",
        "user_id": user_id,
    }
