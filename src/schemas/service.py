# --------------------------------------------------------------------------
# Service schemas for request/response validation
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator

from src.core.urlpolicy import validate_health_check_path, validate_service_url


class ServiceBase(BaseModel):
    """Base service schema"""

    name: str = Field(..., min_length=1, max_length=100)
    display_name: Optional[str] = Field(None, max_length=200)
    url: str = Field(..., min_length=1, max_length=500)
    health_check_path: str = Field(default="/health", max_length=200)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    rate_limit_per_minute: int = Field(default=100, ge=1)
    is_active: bool = True
    description: Optional[str] = None
    service_metadata: Dict[str, Any] = Field(default_factory=dict)


class ServiceCreate(ServiceBase):
    """Schema for creating a new service.

    The destination policy is enforced here so that no write path can register
    an upstream the gateway is not allowed to reach.
    """

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        return validate_service_url(value)

    @field_validator("health_check_path")
    @classmethod
    def _validate_health_check_path(cls, value: str) -> str:
        return validate_health_check_path(value)


class ServiceUpdate(BaseModel):
    """Schema for updating a service"""

    display_name: Optional[str] = Field(None, max_length=200)
    url: Optional[str] = Field(None, min_length=1, max_length=500)
    health_check_path: Optional[str] = Field(None, max_length=200)
    timeout_seconds: Optional[int] = Field(None, ge=1, le=300)
    rate_limit_per_minute: Optional[int] = Field(None, ge=1)
    is_active: Optional[bool] = None
    description: Optional[str] = None
    service_metadata: Optional[Dict[str, Any]] = None

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        return validate_service_url(value)

    @field_validator("health_check_path")
    @classmethod
    def _validate_health_check_path(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        return validate_health_check_path(value)


class ServiceRead(ServiceBase):
    """Schema for reading service data (admin only).

    This exposes internal fields such as the upstream URL and metadata and must
    never be returned from a public endpoint.
    """

    id: int
    created_at: datetime
    updated_at: datetime
    last_health_check: Optional[datetime] = None
    health_status: str = "unknown"

    model_config = {"from_attributes": True}


class ServiceWriteResult(ServiceRead):
    """Result of an admin write, including the registry reload outcome.

    The database change is committed before the registry reload runs, and the
    reload is not rolled back when it fails, because the stored record is
    correct and re-applying it is the operator's next step. That leaves a
    state the plain ServiceRead body could not express: the service is saved
    but the routing table still holds the previous snapshot. These two fields
    carry that fact, and the handler answers 207 instead of 200 or 201 so a
    caller that only reads the status code cannot miss it.

    The extra fields are additive, so a client that parses the response as a
    ServiceRead keeps working.
    """

    registry_reloaded: bool = True
    registry_error: Optional[str] = None


class ServiceDeleteResult(BaseModel):
    """Result of a service deletion, including the registry reload outcome.

    Deletion used to answer 204 with no body, which left no place to report a
    failed reload. It now answers 200 with this body, or 207 when the record
    was deleted and the routing table still routes to it.
    """

    service_id: int
    service_name: str
    registry_reloaded: bool = True
    registry_error: Optional[str] = None


class ServicePublic(BaseModel):
    """Public view of a registered service.

    Internal routing details (URL, timeout, rate limit, metadata) are omitted
    on purpose.
    """

    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    health_status: str = "unknown"
    last_health_check: Optional[datetime] = None


class ServiceHealthStatus(BaseModel):
    """Schema for service health status"""

    service_id: int
    service_name: str
    health_status: str
    last_health_check: Optional[datetime] = None
    is_active: bool


class ServiceStats(BaseModel):
    """Schema for service statistics"""

    total_services: int
    active_services: int
    healthy_services: int
    unhealthy_services: int
    unknown_services: int
