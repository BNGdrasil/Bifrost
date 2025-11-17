# --------------------------------------------------------------------------
# Service model for database storage
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from src.core.database import Base


class Service(Base):
    """Service model for storing API service configurations"""

    __tablename__ = "services"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    display_name = Column(String(200), nullable=True)
    url = Column(String(500), nullable=False)
    health_check_path = Column(String(200), default="/health")
    timeout_seconds = Column(Integer, default=30)
    rate_limit_per_minute = Column(Integer, default=100)
    is_active = Column(Boolean, default=True, index=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_health_check = Column(DateTime(timezone=True), nullable=True)
    health_status = Column(String(20), default="unknown", index=True)
    service_metadata = Column("metadata", JSON, default={})

    def to_dict(self):
        """Convert model to dictionary"""
        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "url": self.url,
            "health_check_path": self.health_check_path,
            "timeout_seconds": self.timeout_seconds,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "is_active": self.is_active,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_health_check": (
                self.last_health_check.isoformat() if self.last_health_check else None
            ),
            "health_status": self.health_status,
            "service_metadata": self.service_metadata,
        }
