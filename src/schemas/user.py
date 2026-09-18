# --------------------------------------------------------------------------
# User schemas for the admin proxy to the Bidar auth server
#
# @author bnbong bbbong9@gmail.com
#
# Bifrost owns no user table. These models only document and lightly validate
# the request bodies that are forwarded to the auth server, which remains the
# authority for business rules such as duplicate detection and last-admin
# protection. Unknown fields are allowed so that an auth server addition does
# not require a gateway release.
# --------------------------------------------------------------------------
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class UserCreateRequest(BaseModel):
    """Body of POST /admin/api/users/ forwarded to the auth server."""

    model_config = ConfigDict(extra="allow")

    username: str = Field(..., min_length=1, max_length=50)
    email: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=1)
    full_name: Optional[str] = Field(None, max_length=100)
    role: Optional[str] = "user"
    is_active: Optional[bool] = True


class UserUpdateRequest(BaseModel):
    """Body of PATCH /admin/api/users/{user_id} forwarded to the auth server."""

    model_config = ConfigDict(extra="allow")

    full_name: Optional[str] = Field(None, max_length=100)
    role: Optional[str] = None
    is_active: Optional[bool] = None


class UserRead(BaseModel):
    """Auth server user representation, documented for API consumers.

    Responses are passed through unchanged rather than re-validated, so extra
    fields added by the auth server reach the caller.
    """

    model_config = ConfigDict(extra="allow")

    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    is_active: bool
    is_superuser: bool
    role: str
    created_at: Optional[datetime] = None
