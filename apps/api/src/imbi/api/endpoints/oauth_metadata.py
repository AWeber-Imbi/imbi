"""OAuth2 Authorization Server metadata (:rfc:`8414`).

Served unprefixed at the host root so the document lives at
``https://<host>/.well-known/oauth-authorization-server`` regardless of
the API's ``/api`` path prefix. MCP clients discover this from the
imbi-mcp protected-resource metadata and use it to drive the
authorization-code + PKCE flow.
"""

from urllib import parse as urlparse

import fastapi

from imbi_api import settings

oauth_metadata_router = fastapi.APIRouter(tags=['Authentication'])


@oauth_metadata_router.get(
    '/.well-known/oauth-authorization-server',
    include_in_schema=False,
)
async def authorization_server_metadata() -> dict[str, object]:
    """Return RFC 8414 Authorization Server metadata."""
    base = settings.get_server_config().public_base_url
    parsed = urlparse.urlparse(base)
    issuer = f'{parsed.scheme}://{parsed.netloc}'
    return {
        'issuer': issuer,
        'authorization_endpoint': f'{base}/auth/authorize',
        'token_endpoint': f'{base}/auth/token',
        'registration_endpoint': f'{base}/auth/register',
        'response_types_supported': ['code'],
        'grant_types_supported': [
            'authorization_code',
            'refresh_token',
            'client_credentials',
        ],
        'code_challenge_methods_supported': ['S256'],
        'token_endpoint_auth_methods_supported': [
            'none',
            'client_secret_post',
        ],
        'scopes_supported': ['imbi'],
    }
