import fastapi

from .admin import admin_router
from .api_keys import api_keys_router
from .auth import auth_router
from .blueprints import blueprint_router
from .client_credentials import client_credentials_router
from .mfa import mfa_router
from .operations_log import operations_log_router
from .organizations import organizations_router
from .roles import roles_router
from .sa_api_keys import sa_api_keys_router
from .service_accounts import service_accounts_router
from .status import status_router
from .uploads import uploads_router
from .users import users_router

routers: list[fastapi.APIRouter] = [
    admin_router,
    api_keys_router,
    auth_router,
    blueprint_router,
    client_credentials_router,
    mfa_router,
    operations_log_router,
    organizations_router,
    roles_router,
    sa_api_keys_router,
    service_accounts_router,
    status_router,
    uploads_router,
    users_router,
]

__all__ = ['routers']
