from app.api.routes.auth import router as auth_router
from app.api.routes.businesses import router as businesses_router
from app.api.routes.intake import router as intake_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.leads import router as leads_router
from app.api.routes.seo import router as seo_router
from app.api.routes.seo import router_v1 as seo_v1_router

__all__ = ["auth_router", "businesses_router", "intake_router", "jobs_router", "leads_router", "seo_router", "seo_v1_router"]
