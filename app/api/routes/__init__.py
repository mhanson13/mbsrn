from app.api.routes.admin_runtime import router as admin_runtime_router
from app.api.routes.auth import router as auth_router
from app.api.routes.businesses import router as businesses_router
from app.api.routes.integrations import router as integrations_router
from app.api.routes.intake import router as intake_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.leads import router as leads_router
from app.api.routes.seo import router as seo_router
from app.api.routes.seo import router_v1 as seo_v1_router
from app.api.routes.seo_migration import router as seo_migration_router

__all__ = [
    "admin_runtime_router",
    "auth_router",
    "businesses_router",
    "integrations_router",
    "intake_router",
    "jobs_router",
    "leads_router",
    "seo_migration_router",
    "seo_router",
    "seo_v1_router",
]
