# --------------------------------------------------------------------------
# Service schemas for request/response validation
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


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
    """Schema for creating a new service"""

    pass


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


class ServiceRead(ServiceBase):
    """Schema for reading service data"""

    id: int
    created_at: datetime
    updated_at: datetime
    last_health_check: Optional[datetime] = None
    health_status: str = "unknown"

    class Config:
        from_attributes = True


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
