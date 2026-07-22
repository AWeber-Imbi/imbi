"""OAuth2 Authorization Server metadata (:rfc:`8414`).

Served unprefixed at the host root so the document lives at
``https://<host>/.well-known/oauth-authorization-server`` regardless of
the API's ``/api`` path prefix. MCP clients discover this from the
imbi-mcp protected-resource metadata and use it to drive the
authorization-code + PKCE flow.
"""

from urllib import parse as urlparse

import fastapi

from imbi_api.endpoints import _request_urls

oauth_metadata_router = fastapi.APIRouter(tags=['Authentication'])


@oauth_metadata_router.get(
    '/.well-known/oauth-authorization-server',
    include_in_schema=False,
)
async def authorization_server_metadata(
    request: fastapi.Request,
) -> dict[str, object]:
    """Return RFC 8414 Authorization Server metadata.

    The issuer and endpoints name the (trusted) host the client reached,
    so discovery validates whether the deployment is fronted by one host
    or several. See :mod:`imbi_api.endpoints._request_urls`.
    """
    base = _request_urls.public_base_url_for_request(request)
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
        # Dynamic client registration only provisions public clients, so
        # advertise ``none`` alone. Advertising ``client_secret_post`` led
        # spec-compliant clients (e.g. Claude's connector) to self-register
        # as confidential clients, which /auth/register then rejected --
        # breaking OAuth login. Confidential service accounts do authenticate
        # at the token endpoint with a secret, but they are provisioned
        # out-of-band and do not rely on this discovery document.
        'token_endpoint_auth_methods_supported': ['none'],
        'scopes_supported': ['imbi'],
    }
