# --------------------------------------------------------------------------
# Admin Logs API - Log viewing and querying
#
# @author bnbong bbbong9@gmail.com
#
# Logs are shipped to Loki and read through Grafana. Bifrost stores no log
# index, so these endpoints report 501 instead of returning sample data.
# --------------------------------------------------------------------------
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status

from src.core.permissions import require_admin

router = APIRouter()


@router.get("/")
@require_admin
async def get_logs(
    request: Request,
    service: Optional[str] = Query(None, description="Filter by service name"),
    level: Optional[str] = Query(None, description="Filter by log level"),
    limit: int = Query(100, description="Maximum number of logs to return"),
) -> Dict[str, Any]:
    """Not implemented. Query the log backend directly."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "Log search is not implemented in Bifrost. "
            "Query the log backend (Loki via Grafana) directly."
        ),
    )


@router.get("/audit")
@require_admin
async def get_audit_logs(request: Request, limit: int = 100) -> Dict[str, Any]:
    """Not implemented. No audit log store exists yet."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "Audit logs are not implemented. Admin actions are written to the "
            "structured application log only."
        ),
    )
