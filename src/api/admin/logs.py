# --------------------------------------------------------------------------
# Admin Logs API - Log viewing and querying
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from src.core.permissions import require_admin

router = APIRouter()


class LogEntry(BaseModel):
    """Log entry model."""

    timestamp: str
    level: str
    service: str
    message: str


class LogsResponse(BaseModel):
    """Response model for logs."""

    total: int
    logs: list[LogEntry]


@router.get("/", response_model=LogsResponse)
@require_admin
async def get_logs(
    request: Request,
    service: str | None = Query(None, description="Filter by service name"),
    level: str | None = Query(None, description="Filter by log level"),
    limit: int = Query(100, description="Maximum number of logs to return"),
) -> LogsResponse:
    """Get system logs (admin only).

    Args:
        request: FastAPI Request object
        service: Optional service name filter
        level: Optional log level filter (INFO, WARNING, ERROR)
        limit: Maximum number of logs to return

    Returns:
        LogsResponse: List of log entries
    """
    # TODO: Fetch actual logs from Loki
    return LogsResponse(
        total=3,
        logs=[
            LogEntry(
                timestamp="2025-10-24T10:30:00Z",
                level="INFO",
                service="gateway",
                message="Request processed successfully",
            ),
            LogEntry(
                timestamp="2025-10-24T10:29:55Z",
                level="WARNING",
                service="auth-server",
                message="Slow query detected",
            ),
            LogEntry(
                timestamp="2025-10-24T10:29:50Z",
                level="ERROR",
                service="wegis-server",
                message="Connection timeout",
            ),
        ],
    )


@router.get("/audit")
@require_admin
async def get_audit_logs(request: Request, limit: int = 100) -> dict:
    """Get audit logs of admin activities (admin only).

    Args:
        request: FastAPI Request object
        limit: Maximum number of logs to return

    Returns:
        dict: Audit log entries
    """
    # TODO: Implement audit log retrieval
    return {
        "total": 2,
        "logs": [
            {
                "timestamp": "2025-10-24T10:25:00Z",
                "admin_user": "admin@bnbong.xyz",
                "action": "USER_DELETE",
                "resource": "users/5",
                "result": "success",
            },
            {
                "timestamp": "2025-10-24T10:20:00Z",
                "admin_user": "admin@bnbong.xyz",
                "action": "SERVICE_RESTART",
                "resource": "services/auth-server",
                "result": "success",
            },
        ],
    }
