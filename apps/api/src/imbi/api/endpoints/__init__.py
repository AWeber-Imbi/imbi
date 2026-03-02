import fastapi

from .admin import admin_router
from .api_keys import api_keys_router
from .auth import auth_router
from .blueprints import blueprint_router
from .environments import environments_router
from .mfa import mfa_router
from .organizations import organizations_router
from .project_types import project_types_router
from .roles import roles_router
from .status import status_router
from .teams import teams_router
from .uploads import uploads_router
from .users import users_router

routers: list[fastapi.APIRouter] = [
    admin_router,
    api_keys_router,
    auth_router,
    blueprint_router,
    environments_router,
    mfa_router,
    organizations_router,
    project_types_router,
    roles_router,
    status_router,
    teams_router,
    uploads_router,
    users_router,
]

__all__ = ['routers']
