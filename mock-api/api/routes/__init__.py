from .auth import router as auth_router
from .projects import router as projects_router
from .commits_versions import router as commits_versions_router
from .jobs import router as jobs_router
from .documents import router as documents_router
from .team import router as team_router
from .compare import router as compare_router
from .functions import router as functions_router
from .notifications import router as notifications_router
from .repositories import router as repositories_router
from .users import router as users_router

__all__ = [
    "auth_router", "projects_router", "commits_versions_router",
    "jobs_router", "documents_router", "team_router",
    "compare_router", "functions_router", "notifications_router",
    "repositories_router", "users_router",
]
