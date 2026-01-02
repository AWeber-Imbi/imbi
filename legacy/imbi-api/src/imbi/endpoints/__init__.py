import fastapi

from .api_keys import api_keys_router
from .auth import auth_router
from .blueprints import blueprint_router
from .groups import groups_router
from .mfa import mfa_router
from .roles import roles_router
from .status import status_router
from .users import users_router

routers: list[fastapi.APIRouter] = [
    api_keys_router,
    auth_router,
    blueprint_router,
    groups_router,
    mfa_router,
    roles_router,
    status_router,
    users_router,
]

__all__ = ['routers']
