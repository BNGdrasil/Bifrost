# --------------------------------------------------------------------------
# CRUD operations for Service model
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
from datetime import datetime
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.service import Service
from src.schemas.service import ServiceCreate, ServiceStats, ServiceUpdate


def get_service_by_id(db: Session, service_id: int) -> Optional[Service]:
    """Get service by ID"""
    result = db.execute(select(Service).filter(Service.id == service_id))
    return result.scalar_one_or_none()


def get_service_by_name(db: Session, name: str) -> Optional[Service]:
    """Get service by name"""
    result = db.execute(select(Service).filter(Service.name == name))
    return result.scalar_one_or_none()


def get_services(
    db: Session, skip: int = 0, limit: int = 100, active_only: bool = False
) -> List[Service]:
    """Get list of services"""
    query = select(Service)
    if active_only:
        query = query.filter(Service.is_active == True)
    query = query.offset(skip).limit(limit)
    result = db.execute(query)
    return list(result.scalars().all())


def create_service(db: Session, service: ServiceCreate) -> Service:
    """Create a new service"""
    db_service = Service(
        name=service.name,
        display_name=service.display_name,
        url=service.url,
        health_check_path=service.health_check_path,
        timeout_seconds=service.timeout_seconds,
        rate_limit_per_minute=service.rate_limit_per_minute,
        is_active=service.is_active,
        description=service.description,
        service_metadata=service.service_metadata,
    )
    db.add(db_service)
    db.commit()
    db.refresh(db_service)
    return db_service


def update_service(
    db: Session, service_id: int, service_update: ServiceUpdate
) -> Optional[Service]:
    """Update a service"""
    db_service = get_service_by_id(db, service_id)
    if not db_service:
        return None

    # Update only provided fields
    update_data = service_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_service, field, value)

    db.commit()
    db.refresh(db_service)
    return db_service


def delete_service(db: Session, service_id: int) -> bool:
    """Delete a service"""
    db_service = get_service_by_id(db, service_id)
    if not db_service:
        return False

    db.delete(db_service)
    db.commit()
    return True


def update_service_health(
    db: Session, service_id: int, health_status: str
) -> Optional[Service]:
    """Update service health status"""
    db_service = get_service_by_id(db, service_id)
    if not db_service:
        return None

    setattr(db_service, "health_status", health_status)
    setattr(db_service, "last_health_check", datetime.now())

    db.commit()
    db.refresh(db_service)
    return db_service


def get_service_stats(db: Session) -> ServiceStats:
    """Get service statistics"""
    # Total services
    total_result = db.execute(select(func.count(Service.id)))
    total_services = total_result.scalar() or 0

    # Active services
    active_result = db.execute(
        select(func.count(Service.id)).filter(Service.is_active == True)
    )
    active_services = active_result.scalar() or 0

    # Healthy services
    healthy_result = db.execute(
        select(func.count(Service.id)).filter(Service.health_status == "healthy")
    )
    healthy_services = healthy_result.scalar() or 0

    # Unhealthy services
    unhealthy_result = db.execute(
        select(func.count(Service.id)).filter(Service.health_status == "unhealthy")
    )
    unhealthy_services = unhealthy_result.scalar() or 0

    # Unknown services
    unknown_result = db.execute(
        select(func.count(Service.id)).filter(Service.health_status == "unknown")
    )
    unknown_services = unknown_result.scalar() or 0

    return ServiceStats(
        total_services=total_services,
        active_services=active_services,
        healthy_services=healthy_services,
        unhealthy_services=unhealthy_services,
        unknown_services=unknown_services,
    )
