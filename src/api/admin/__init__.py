# --------------------------------------------------------------------------
# Admin API module
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
from fastapi import APIRouter

from .logs import router as logs_router
from .services import router as services_router
from .settings import router as settings_router
from .users import router as users_router

admin_router = APIRouter()

# Include all admin routers
admin_router.include_router(users_router, prefix="/users", tags=["admin-users"])
admin_router.include_router(
    services_router, prefix="/services", tags=["admin-services"]
)
admin_router.include_router(logs_router, prefix="/logs", tags=["admin-logs"])
admin_router.include_router(
    settings_router, prefix="/settings", tags=["admin-settings"]
)


@admin_router.get("/")
async def admin_root() -> dict:
    """Admin API root endpoint."""
    return {
        "message": "Welcome to Bifrost Admin API",
        "endpoints": {
            "users": "/admin/api/users",
            "services": "/admin/api/services",
            "logs": "/admin/api/logs",
            "settings": "/admin/api/settings",
        },
    }
