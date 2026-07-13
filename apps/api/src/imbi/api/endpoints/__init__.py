import fastapi

from imbi_api.identity.endpoints import me_identities_router

from . import (
    user_activity,  # pyright: ignore[reportUnusedImport]  # noqa: F401
)
from .admin import admin_router
from .admin_plugins import admin_plugins_router
from .api_keys import api_keys_router
from .auth import auth_router
from .auth_providers import auth_providers_router
from .blueprints import blueprint_router
from .client_credentials import client_credentials_router
from .dashboard import dashboard_router
from .events import events_router
from .graph_query import graph_query_router
from .local_auth import local_auth_router
from .mcp_servers import mcp_servers_router
from .mfa import mfa_router
from .oauth_metadata import oauth_metadata_router
from .operations_log import operations_log_router
from .organizations import organizations_router
from .plugin_entities import plugin_entities_router
from .plugins import plugins_router
from .project_integrations import project_integrations_router
from .project_plugins import project_plugins_router
from .roles import roles_router
from .sa_api_keys import sa_api_keys_router
from .scoring import scoring_router
from .scoring_policies import scoring_policies_router
from .service_accounts import service_accounts_router
from .status import status_router
from .uploads import uploads_router
from .users import users_router

prefixed_routers: list[fastapi.APIRouter] = [
    admin_plugins_router,
    admin_router,
    api_keys_router,
    auth_providers_router,
    auth_router,
    blueprint_router,
    client_credentials_router,
    dashboard_router,
    events_router,
    graph_query_router,
    local_auth_router,
    mcp_servers_router,
    me_identities_router,
    mfa_router,
    operations_log_router,
    organizations_router,
    plugin_entities_router,
    plugins_router,
    project_integrations_router,
    project_plugins_router,
    roles_router,
    sa_api_keys_router,
    scoring_policies_router,
    scoring_router,
    service_accounts_router,
    status_router,
    uploads_router,
    users_router,
]

unprefixed_routers: list[fastapi.APIRouter] = [
    oauth_metadata_router,
]

routers: list[fastapi.APIRouter] = prefixed_routers + unprefixed_routers

__all__ = ['prefixed_routers', 'routers', 'unprefixed_routers']
