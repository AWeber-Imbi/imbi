"""Authentication endpoints for login, token refresh, and logout."""

import asyncio
import datetime
import logging
import secrets
import typing
from urllib import parse as urlparse

import fastapi
import jwt
import pydantic
from imbi_common import graph
from imbi_common.auth import core
from imbi_common.plugins import errors as plugin_errors
from valkey import asyncio as valkey_module

from imbi_api import models, settings
from imbi_api.auth import (
    authorization_codes,
    local_auth,
    login_providers,
    oauth_clients,
    permissions,
    tokens,
)
from imbi_api.auth import models as auth_models
from imbi_api.auth import password as password_auth
from imbi_api.auth.totp import fetch_totp_secret, verify_totp_code
from imbi_api.endpoints import _request_urls
from imbi_api.identity import flows as identity_flows
from imbi_api.identity import repository as identity_repository
from imbi_api.middleware import rate_limit
from imbi_api.scoring import OptionalValkeyClient

LOGGER = logging.getLogger(__name__)

# Pre-computed dummy Argon2 hash used to keep login timing constant when
# the supplied email does not match an authenticable user. Without this,
# the existence of a user (vs. service-account, OAuth-only, or unknown
# email) could be inferred from the response time.
_DUMMY_PASSWORD_HASH = password_auth.hash_password(secrets.token_hex(32))


def _redact_email(email: str) -> str:
    """Return a log-safe representation of an email address.

    Preserves the domain and the first character of the local part so
    failures can still be triaged (e.g. all-from-one-domain scans) while
    keeping the local part — which is user-supplied PII on the failure
    path — out of the log stream.
    """
    if not email or '@' not in email:
        return '<redacted>'
    local, _, domain = email.partition('@')
    prefix = local[:1] if local else ''
    return f'{prefix}***@{domain}'


def _is_safe_redirect_uri(
    redirect_uri: str, allowed_origins: list[str]
) -> bool:
    """Return whether *redirect_uri* is a safe post-login destination.

    The OAuth callback hands freshly-minted tokens to this URI, so a
    caller-controlled value is an account-takeover vector (tokens
    exfiltrated to an attacker host). Only two shapes are allowed:

    * a same-origin relative path — a single leading ``/`` that is not a
      scheme-relative ``//host`` or a ``/\\`` backslash trick; and
    * an absolute ``http(s)`` URL whose ``scheme://host[:port]`` origin is
      in the configured CORS allow-list (the trusted front-ends).

    Everything else (arbitrary absolute URLs, ``javascript:``/``data:``
    schemes, embedded whitespace browsers may strip) is rejected.
    """
    if not redirect_uri or any(c.isspace() for c in redirect_uri):
        return False
    if redirect_uri.startswith('/'):
        return not redirect_uri.startswith(('//', '/\\'))
    parsed = urlparse.urlparse(redirect_uri)
    if parsed.scheme in ('http', 'https') and parsed.netloc:
        return f'{parsed.scheme}://{parsed.netloc}' in allowed_origins
    return False


_REFRESH_COOKIE = 'imbi_refresh_token'


def _refresh_cookie_path() -> str:
    """Browser-visible path the refresh cookie is scoped to.

    The auth router is mounted at ``/auth`` within the app, but the app is
    served behind the public ``IMBI_API_URL`` prefix (``/api`` in
    deployment, empty in dev-loopback). The cookie ``Path`` is matched by
    the browser against the public URL, so it must include that prefix or
    the cookie is never sent to ``{prefix}/auth/token/refresh``.
    """
    return f'{settings.get_server_config().api_prefix}/auth'


def _set_refresh_cookie(
    response: fastapi.Response, refresh_token: str
) -> None:
    """Store the refresh token in an HttpOnly cookie (C2).

    Keeps the long-lived refresh token out of JS-readable storage and out
    of the OAuth callback URL fragment (where it would otherwise leak via
    browser history, the Referer header, and logs). Scoped to the auth
    endpoints so it is only sent to token-refresh and logout. ``Secure``
    is set outside development; ``SameSite=Strict`` is safe because the UI
    and API are served from one origin behind the ingress.
    """
    auth_settings = settings.get_auth_settings()
    response.set_cookie(
        _REFRESH_COOKIE,
        refresh_token,
        max_age=auth_settings.refresh_token_expire_seconds,
        path=_refresh_cookie_path(),
        httponly=True,
        secure=settings.get_server_config().environment != 'development',
        samesite='strict',
    )


def _clear_refresh_cookie(response: fastapi.Response) -> None:
    """Remove the refresh-token cookie (logout)."""
    response.delete_cookie(_REFRESH_COOKIE, path=_refresh_cookie_path())


def _access_cookie_path() -> str:
    """Browser-visible path the access cookie is scoped to.

    Unlike the refresh cookie (scoped to ``/auth``), the access cookie must
    reach the upload-serving GET endpoints (``{prefix}/uploads/...``) so the
    browser includes it on ``<img>`` requests, which cannot carry an
    ``Authorization`` header. Scope it to the whole API prefix (``/`` in the
    dev-loopback case where the prefix is empty).
    """
    return settings.get_server_config().api_prefix or '/'


def _set_access_cookie(response: fastapi.Response, access_token: str) -> None:
    """Mirror the access token into a short-lived cookie.

    The SPA still sends the access token as a Bearer header on fetch/XHR;
    this cookie exists only so browser subresource requests (``<img src>``
    to the upload-serving endpoints) carry credentials. Its lifetime
    matches the access-token TTL and it is refreshed on every token
    rotation. ``Secure`` outside development; ``SameSite=Strict`` is safe
    because the UI and API share one origin behind the ingress.
    """
    auth_settings = settings.get_auth_settings()
    response.set_cookie(
        permissions.ACCESS_COOKIE_NAME,
        access_token,
        max_age=auth_settings.access_token_expire_seconds,
        path=_access_cookie_path(),
        httponly=True,
        secure=settings.get_server_config().environment != 'development',
        samesite='strict',
    )


def _clear_access_cookie(response: fastapi.Response) -> None:
    """Remove the access-token cookie (logout)."""
    response.delete_cookie(
        permissions.ACCESS_COOKIE_NAME, path=_access_cookie_path()
    )


auth_router = fastapi.APIRouter(prefix='/auth', tags=['Authentication'])


@auth_router.get(
    '/providers', response_model=auth_models.AuthProvidersResponse
)
async def get_auth_providers(
    db: graph.Pool,
) -> auth_models.AuthProvidersResponse:
    """Get available authentication providers configuration.

    Returns a list of enabled authentication providers to allow the UI
    to dynamically configure the login interface.

    Returns:
        AuthProvidersResponse: List of providers with configuration

    """
    providers: list[auth_models.AuthProvider] = []

    # Local password authentication is a database-stored toggle.
    local_config = await local_auth.get_config(db)
    if local_config.enabled:
        providers.append(
            auth_models.AuthProvider(
                id='local',
                type='password',
                name='Email/Password',
                enabled=True,
                icon='lock',
            )
        )

    apps = await login_providers.list_login_apps(db, enabled_only=True)
    icon_for: dict[str, str] = {
        'google': 'si-google',
        'github': 'si-github',
        'oidc': 'key-round',
    }
    for app in apps:
        providers.append(
            auth_models.AuthProvider(
                id=app.slug,
                type='oauth',
                name=app.name,
                enabled=True,
                auth_url=f'/auth/oauth/{app.slug}',
                icon=icon_for.get(app.oauth_app_type, 'key-round'),
            )
        )

    return auth_models.AuthProvidersResponse(
        providers=providers,
        default_redirect='/dashboard',
    )


async def _authorization_code_grant(
    db: graph.Graph,
    valkey_client: valkey_module.Valkey | None,
    *,
    code: str | None,
    redirect_uri: str | None,
    client_id: str | None,
    code_verifier: str | None,
) -> models.OAuth2TokenResponse:
    """Exchange a PKCE authorization code for an Imbi token pair."""
    if not (code and redirect_uri and client_id and code_verifier):
        raise fastapi.HTTPException(
            status_code=400,
            detail='Missing authorization_code parameters',
        )
    if valkey_client is None:
        # Codes live in Valkey; without it single-use cannot be enforced,
        # so fail closed rather than trust an unverifiable code.
        raise fastapi.HTTPException(
            status_code=503,
            detail='Authorization code store unavailable',
        )
    client = await oauth_clients.get_client(db, client_id)
    if client is None:
        raise fastapi.HTTPException(
            status_code=401, detail='Invalid client_id'
        )
    payload = await authorization_codes.consume_code(valkey_client, code)
    if payload is None:
        raise fastapi.HTTPException(
            status_code=400, detail='Invalid or expired authorization code'
        )
    if (
        payload['client_id'] != client_id
        or payload['redirect_uri'] != redirect_uri
    ):
        raise fastapi.HTTPException(
            status_code=400, detail='Authorization code does not match request'
        )
    if not authorization_codes.verify_pkce(
        code_verifier, payload['code_challenge']
    ):
        raise fastapi.HTTPException(
            status_code=400, detail='PKCE verification failed'
        )

    auth_settings = settings.get_auth_settings()
    try:
        access_token, refresh_token_value, _ = await tokens.issue_token_pair(
            db,
            principal_type='user',
            principal_id=payload['principal_id'],
            auth_settings=auth_settings,
            extra_claims={'auth_method': 'oauth'},
        )
    except tokens.PrincipalNotFoundError as err:
        raise fastapi.HTTPException(
            status_code=400, detail='User no longer exists'
        ) from err
    LOGGER.info(
        'OAuth code exchanged for %s (client %s)',
        _redact_email(payload['principal_id']),
        client_id,
    )
    return models.OAuth2TokenResponse(
        access_token=access_token,
        token_type='bearer',
        expires_in=auth_settings.access_token_expire_seconds,
        scope=payload['scope'],
        refresh_token=refresh_token_value,
    )


async def _refresh_token_grant(
    db: graph.Graph,
    refresh_token_value: str | None,
) -> models.OAuth2TokenResponse:
    """Rotate a refresh token presented via the OAuth token endpoint."""
    if not refresh_token_value:
        raise fastapi.HTTPException(
            status_code=400, detail='Missing refresh_token'
        )
    auth_settings = settings.get_auth_settings()
    access_token, new_refresh_token = await _rotate_refresh_token(
        db, refresh_token_value, auth_settings
    )
    return models.OAuth2TokenResponse(
        access_token=access_token,
        token_type='bearer',
        expires_in=auth_settings.access_token_expire_seconds,
        refresh_token=new_refresh_token,
    )


@auth_router.post('/token', response_model=models.OAuth2TokenResponse)
@rate_limit.limiter.limit('10/minute')  # type: ignore[untyped-decorator]
async def token(
    request: fastapi.Request,
    db: graph.Pool,
    valkey_client: OptionalValkeyClient,
    grant_type: typing.Annotated[str, fastapi.Form()],
    client_id: typing.Annotated[str | None, fastapi.Form()] = None,
    client_secret: typing.Annotated[str | None, fastapi.Form()] = None,
    scope: typing.Annotated[str | None, fastapi.Form()] = None,
    code: typing.Annotated[str | None, fastapi.Form()] = None,
    redirect_uri: typing.Annotated[str | None, fastapi.Form()] = None,
    code_verifier: typing.Annotated[str | None, fastapi.Form()] = None,
    refresh_token: typing.Annotated[str | None, fastapi.Form()] = None,
) -> models.OAuth2TokenResponse:
    """OAuth2 token endpoint (RFC 6749), form-encoded.

    Dispatches on ``grant_type``:

    * ``authorization_code`` -- exchange a PKCE-protected code minted by
      ``/auth/authorize`` for an Imbi access+refresh pair (public client,
      no secret).
    * ``refresh_token`` -- rotate an Imbi refresh token.
    * ``client_credentials`` -- service-account machine-to-machine grant
      (requires ``client_id`` + ``client_secret``).

    Returns:
        OAuth2TokenResponse with access and (for code/refresh) refresh
        tokens.

    """
    if grant_type == 'authorization_code':
        return await _authorization_code_grant(
            db,
            valkey_client,
            code=code,
            redirect_uri=redirect_uri,
            client_id=client_id,
            code_verifier=code_verifier,
        )
    if grant_type == 'refresh_token':
        return await _refresh_token_grant(db, refresh_token)
    if grant_type != 'client_credentials':
        raise fastapi.HTTPException(
            status_code=400,
            detail='Unsupported grant_type',
        )
    if not client_id or not client_secret:
        raise fastapi.HTTPException(
            status_code=401,
            detail='Invalid client credentials',
        )

    # Fetch credential with owning service account
    query: typing.LiteralString = """
    MATCH (c:ClientCredential {{client_id: {client_id}}})
          -[:OWNED_BY]->(s:ServiceAccount)
    RETURN c, s
    """
    records = await db.execute(
        query,
        {'client_id': client_id},
        ['c', 's'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=401,
            detail='Invalid client credentials',
        )

    cred_data = graph.parse_agtype(records[0]['c'])
    sa_data = graph.parse_agtype(records[0]['s'])

    # Check revoked
    if cred_data.get('revoked', False):
        raise fastapi.HTTPException(
            status_code=401,
            detail='Client credential has been revoked',
        )

    # Check expired -- AGE stores datetime as ISO strings
    expires_at = cred_data.get('expires_at')
    if expires_at:
        if isinstance(expires_at, str):
            expires_at = datetime.datetime.fromisoformat(
                expires_at,
            )
        if expires_at < datetime.datetime.now(datetime.UTC):
            raise fastapi.HTTPException(
                status_code=401,
                detail='Client credential has expired',
            )

    # Verify secret
    if not await asyncio.to_thread(
        password_auth.verify_password,
        client_secret,
        cred_data['client_secret_hash'],
    ):
        raise fastapi.HTTPException(
            status_code=401,
            detail='Invalid client credentials',
        )

    # Check service account is active
    sa = models.ServiceAccount(**sa_data)
    if not sa.is_active:
        raise fastapi.HTTPException(
            status_code=401,
            detail='Service account is inactive',
        )

    # Resolve scopes
    cred_scopes: set[str] = set(
        models.parse_scopes(cred_data.get('scopes', []))
    )
    requested_scopes: set[str] = set(scope.split()) if scope else set()
    if requested_scopes and cred_scopes:
        granted_scopes: set[str] = requested_scopes & cred_scopes
    elif cred_scopes:
        granted_scopes = cred_scopes
    else:
        granted_scopes = requested_scopes

    # Create tokens
    auth_settings = settings.get_auth_settings()
    extra_claims: dict[str, typing.Any] = {
        'auth_method': 'client_credentials',
    }
    if granted_scopes:
        extra_claims['scope'] = ' '.join(sorted(granted_scopes))
    access_token, refresh_token, _ = await tokens.issue_token_pair(
        db,
        principal_type='service_account',
        principal_id=sa.slug,
        auth_settings=auth_settings,
        extra_claims=extra_claims,
    )

    # Update last_used on credential, last_authenticated on SA
    now_iso = datetime.datetime.now(datetime.UTC).isoformat()
    update_query: typing.LiteralString = """
    MATCH (c:ClientCredential {{client_id: {client_id}}})
    SET c.last_used = {now}
    WITH c
    MATCH (c)-[:OWNED_BY]->(s:ServiceAccount)
    SET s.last_authenticated = {now}
    """
    await db.execute(
        update_query,
        {
            'client_id': client_id,
            'now': now_iso,
        },
    )

    LOGGER.info(
        'Client credentials token issued for service '
        'account %s (client_id=%s)',
        sa.slug,
        client_id,
    )

    scope_str: str | None = (
        ' '.join(sorted(granted_scopes)) if granted_scopes else None
    )

    return models.OAuth2TokenResponse(
        access_token=access_token,
        token_type='bearer',
        expires_in=auth_settings.access_token_expire_seconds,
        scope=scope_str,
        refresh_token=refresh_token,
    )


def _principal_from_token(token: str) -> str | None:
    """Return the subject of a valid Imbi *access* token, else None."""
    try:
        payload = core.verify_token(token, settings.get_auth_settings())
    except jwt.InvalidTokenError:
        return None
    if payload.get('type') != 'access':
        return None
    sub = payload.get('sub')
    return sub if isinstance(sub, str) else None


def _authorize_request_principal(request: fastapi.Request) -> str | None:
    """Identify the logged-in Imbi user for an /authorize request.

    Prefers a Bearer access token, falling back to the access cookie the
    SPA sets after login. Returns the subject (email) or ``None`` when no
    valid access token is present.
    """
    authz = request.headers.get('authorization', '')
    if authz.lower().startswith('bearer '):
        principal = _principal_from_token(authz[7:].strip())
        if principal:
            return principal
    cookie = request.cookies.get(permissions.ACCESS_COOKIE_NAME)
    return _principal_from_token(cookie) if cookie else None


def _public_authorize_url(request: fastapi.Request) -> str:
    """Absolute, public URL of this /authorize request (for return_to)."""
    base = _request_urls.public_base_url_for_request(request)
    query = request.url.query
    suffix = f'?{query}' if query else ''
    return f'{base}/auth/authorize{suffix}'


def _login_redirect_url(request: fastapi.Request, return_to: str) -> str:
    """SPA login URL that returns to *return_to* after authentication.

    The login page is the SPA served on the same host as this request, so
    the redirect targets the request's trusted origin -- which keeps the
    login leg same-origin whether the deployment is fronted by one host or
    several. Falls back to ``ui_url`` (empty -> a relative ``/login`` the
    browser resolves against the current host) when the origin is untrusted.
    """
    base = _request_urls.request_origin(request)
    if base is None:
        base = settings.get_server_config().ui_url
    return f'{base}/login?{urlparse.urlencode({"return_to": return_to})}'


@auth_router.get('/authorize')
@rate_limit.limiter.limit('20/minute')  # type: ignore[untyped-decorator]
async def authorize(
    request: fastapi.Request,
    db: graph.Pool,
    valkey_client: OptionalValkeyClient,
    response_type: str = fastapi.Query(default=''),
    client_id: str = fastapi.Query(default=''),
    redirect_uri: str = fastapi.Query(default=''),
    code_challenge: str = fastapi.Query(default=''),
    code_challenge_method: str = fastapi.Query(default=''),
    scope: str | None = fastapi.Query(default=None),
    state: str | None = fastapi.Query(default=None),
) -> fastapi.responses.RedirectResponse:
    """OAuth2 authorization endpoint (authorization_code + PKCE).

    Validates the client and redirect URI, requires an authenticated
    Imbi user (bouncing through the SPA login if absent), then issues a
    single-use authorization code bound to the PKCE challenge and the
    user. The Imbi login may itself delegate to an upstream IdP — that
    is transparent here; only the resulting Imbi session matters.
    """
    client = (
        await oauth_clients.get_client(db, client_id) if client_id else None
    )
    if client is None:
        raise fastapi.HTTPException(
            status_code=400, detail='Unknown client_id'
        )
    if redirect_uri not in client.redirect_uris:
        raise fastapi.HTTPException(
            status_code=400,
            detail='redirect_uri not registered for this client',
        )

    # redirect_uri is trusted from here, so protocol errors are reported
    # back to it (RFC 6749 §4.1.2.1) rather than surfaced to the user.
    def _redirect_error(error: str) -> fastapi.responses.RedirectResponse:
        params = {'error': error}
        if state:
            params['state'] = state
        sep = '&' if '?' in redirect_uri else '?'
        return fastapi.responses.RedirectResponse(
            url=f'{redirect_uri}{sep}{urlparse.urlencode(params)}',
            status_code=302,
        )

    if response_type != 'code':
        return _redirect_error('unsupported_response_type')
    if code_challenge_method != 'S256' or not code_challenge:
        return _redirect_error('invalid_request')

    principal = _authorize_request_principal(request)
    if principal is None:
        # Not logged in to Imbi: bounce through the SPA login and return
        # here via a full-page navigation so the access cookie is sent.
        return fastapi.responses.RedirectResponse(
            url=_login_redirect_url(request, _public_authorize_url(request)),
            status_code=302,
        )

    if valkey_client is None:
        raise fastapi.HTTPException(
            status_code=503, detail='Authorization code store unavailable'
        )
    code = await authorization_codes.issue_code(
        valkey_client,
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        principal_id=principal,
        scope=scope,
    )
    LOGGER.info(
        'Issued authorization code for client %s to %s',
        client_id,
        _redact_email(principal),
    )
    params = {'code': code}
    if state:
        params['state'] = state
    sep = '&' if '?' in redirect_uri else '?'
    return fastapi.responses.RedirectResponse(
        url=f'{redirect_uri}{sep}{urlparse.urlencode(params)}',
        status_code=302,
    )


@auth_router.post(
    '/register',
    response_model=models.OAuthClientRegistrationResponse,
    status_code=201,
)
@rate_limit.limiter.limit('10/minute')  # type: ignore[untyped-decorator]
async def register_oauth_client(
    request: fastapi.Request,
    db: graph.Pool,
    body: models.OAuthClientRegistrationRequest,
) -> models.OAuthClientRegistrationResponse:
    """Dynamic Client Registration (RFC 7591) for public OAuth clients."""
    auth_settings = settings.get_auth_settings()
    if not auth_settings.dcr_enabled:
        raise fastapi.HTTPException(
            status_code=403,
            detail='Dynamic client registration is disabled',
        )
    if not body.redirect_uris:
        raise fastapi.HTTPException(
            status_code=400, detail='redirect_uris is required'
        )
    for uri in body.redirect_uris:
        if not oauth_clients.is_valid_redirect_uri(uri):
            raise fastapi.HTTPException(
                status_code=400, detail=f'Invalid redirect_uri: {uri}'
            )
    if set(body.grant_types) != {'authorization_code', 'refresh_token'}:
        raise fastapi.HTTPException(
            status_code=400,
            detail='Only authorization_code and refresh_token grants '
            'are supported',
        )
    if body.response_types != ['code']:
        raise fastapi.HTTPException(
            status_code=400,
            detail="Only response_types=['code'] is supported",
        )
    if body.token_endpoint_auth_method != 'none':
        raise fastapi.HTTPException(
            status_code=400,
            detail='Only public clients '
            '(token_endpoint_auth_method=none) are supported',
        )
    client = await oauth_clients.register_client(
        db,
        redirect_uris=body.redirect_uris,
        client_name=body.client_name,
        grant_types=body.grant_types,
        response_types=body.response_types,
        token_endpoint_auth_method=body.token_endpoint_auth_method,
        scope=body.scope,
    )
    return models.OAuthClientRegistrationResponse(
        client_id=client.client_id,
        client_name=client.client_name,
        redirect_uris=client.redirect_uris,
        grant_types=client.grant_types,
        response_types=client.response_types,
        token_endpoint_auth_method=client.token_endpoint_auth_method,
        scope=client.scope,
        client_id_issued_at=int(client.created_at.timestamp()),
    )


@auth_router.post('/login', response_model=auth_models.TokenResponse)
@rate_limit.limiter.limit('5/minute')  # type: ignore[untyped-decorator]
async def login(
    request: fastapi.Request,
    response: fastapi.Response,
    db: graph.Pool,
    email: typing.Annotated[pydantic.EmailStr, fastapi.Body()],
    password: typing.Annotated[str, fastapi.Body()],
    mfa_code: typing.Annotated[str | None, fastapi.Body()] = None,
) -> auth_models.TokenResponse:
    """Login with email and password (Phase 5: with optional MFA).

    Phase 5 adds MFA support. If the user has MFA enabled, they must
    provide a valid TOTP code or backup code via the mfa_code parameter.

    Args:
        email: User email address
        password: User password
        mfa_code: Optional MFA code (6-digit TOTP or backup code)

    Returns:
        JWT tokens (access and refresh)

    Raises:
        HTTPException: 401 if credentials are invalid or MFA code
            required. Returns X-MFA-Required: true header if MFA
            is required.

    """
    # Fetch user from database
    results = await db.match(models.User, {'email': email})
    user = results[0] if results else None

    # Always run Argon2 verification — against the real hash if the user
    # is eligible for password login, otherwise against a fixed dummy
    # hash. This collapses every failure mode (unknown email, inactive,
    # service-account, OAuth-only, wrong password) to the same generic
    # 401 with constant timing, eliminating the user-enumeration oracle.
    eligible = bool(
        user
        and user.is_active
        and not user.is_service_account
        and user.password_hash
    )
    hash_to_check = (
        user.password_hash
        if eligible and user is not None and user.password_hash
        else _DUMMY_PASSWORD_HASH
    )
    password_valid = await asyncio.to_thread(
        password_auth.verify_password, password, hash_to_check
    )

    if not eligible or not password_valid or user is None:
        LOGGER.warning('Login failed for email %s', _redact_email(email))
        raise fastapi.HTTPException(
            status_code=401,
            detail='Invalid credentials',
        )

    user_hash = typing.cast(str, user.password_hash)

    # Check if password needs rehashing
    if await asyncio.to_thread(password_auth.needs_rehash, user_hash):
        user.password_hash = await asyncio.to_thread(
            password_auth.hash_password, password
        )
        await db.merge(user, match_on=['email'])
        LOGGER.info('Rehashed password for user %s', _redact_email(user.email))

    # Phase 5: Check if MFA is enabled
    totp_data = await fetch_totp_secret(db, user.email)

    if totp_data and totp_data.get('enabled', False):
        # MFA is enabled - code is required
        if not mfa_code:
            raise fastapi.HTTPException(
                status_code=401,
                detail='MFA code required',
                headers={'X-MFA-Required': 'true'},
            )

        auth_settings = settings.get_auth_settings()
        is_valid, matched_backup_hash = await verify_totp_code(
            totp_data,
            mfa_code,
            period=auth_settings.mfa_totp_period,
            digits=auth_settings.mfa_totp_digits,
        )
        if not is_valid:
            raise fastapi.HTTPException(
                status_code=401,
                detail='Invalid MFA code',
            )

        now_str = datetime.datetime.now(datetime.UTC).isoformat()
        if matched_backup_hash is None:
            # TOTP path: refresh last_used.
            update_q: typing.LiteralString = """
            MATCH (u:User {{email: {email}}})
                  <-[:MFA_FOR]-(t:TOTPSecret)
            SET t.last_used = {now}
            """
            await db.execute(
                update_q,
                {'email': user.email, 'now': now_str},
            )
            LOGGER.info(
                'MFA verified via TOTP for user %s',
                _redact_email(user.email),
            )
        else:
            # Backup-code path: atomically remove the used code. The
            # ``WHERE {used_hash} IN t.backup_codes`` guard + list
            # comprehension is the H6 race fix -- if a parallel login
            # already consumed this hash the SET never fires; the empty
            # result is detected and we fail closed with a 401 (a
            # submitted code matches at most one hash, so there is no
            # other code to fall through to).
            update_q2: typing.LiteralString = """
            MATCH (u:User {{email: {email}}})
                  <-[:MFA_FOR]-(t:TOTPSecret)
            WHERE {used_hash} IN t.backup_codes
            SET t.backup_codes =
                [c IN t.backup_codes WHERE c <> {used_hash}]
            RETURN size(t.backup_codes) AS remaining
            """
            update_records = await db.execute(
                update_q2,
                {'email': user.email, 'used_hash': matched_backup_hash},
                columns=['remaining'],
            )
            if not update_records:
                LOGGER.warning(
                    'MFA backup code already consumed for user %s (race)',
                    _redact_email(user.email),
                )
                raise fastapi.HTTPException(
                    status_code=401,
                    detail='Invalid MFA code',
                )
            LOGGER.info(
                'MFA verified via backup code for user %s',
                _redact_email(user.email),
            )

    # Create tokens
    auth_settings = settings.get_auth_settings()
    access_token, refresh_token, meta = await tokens.issue_token_pair(
        db,
        principal_type='user',
        principal_id=user.email,
        auth_settings=auth_settings,
    )

    # Update last login timestamp
    user.last_login = meta['issued_at']
    await db.merge(user, match_on=['email'])

    LOGGER.info('User %s logged in successfully', _redact_email(user.email))

    _set_refresh_cookie(response, refresh_token)
    _set_access_cookie(response, access_token)
    return auth_models.TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=auth_settings.access_token_expire_seconds,
    )


async def _handle_refresh_reuse(
    db: graph.Graph, *, jti: str, revoked_at_iso: str
) -> None:
    """Detect and respond to refresh-token reuse.

    Called from the refresh handler when the atomic ``MATCH ... WHERE
    revoked = false ... SET revoked = true`` returned no rows. Two
    cases:

    1. The token doesn't exist — forged or expired-and-pruned jti.
       Nothing to revoke; log and return.
    2. The token exists with ``revoked = true`` — canonical
       refresh-reuse signal. Revoke every un-revoked
       ``TokenMetadata`` sharing the same ``family_id`` so an
       attacker who already rotated tokens is logged out alongside
       the victim.
    """
    lookup: typing.LiteralString = (
        'MATCH (n:TokenMetadata {{jti: {jti}}}) '
        'RETURN n.revoked AS revoked, n.family_id AS family_id'
    )
    rows = await db.execute(
        lookup, {'jti': jti}, columns=['revoked', 'family_id']
    )
    if not rows:
        LOGGER.warning('Token refresh failed: token not found (jti=%s)', jti)
        return
    revoked_val = graph.parse_agtype(rows[0].get('revoked'))
    family_id_val = graph.parse_agtype(rows[0].get('family_id'))
    if not revoked_val:
        # Lost the race for some non-revoked reason (e.g. wrong
        # token_type). Caller already logs; no cascade to fire.
        return
    if not isinstance(family_id_val, str) or not family_id_val:
        # Legacy token issued before family_id existed. Without a
        # family we can't trace the chain — log the reuse but skip
        # the cascade so we never accidentally revoke unrelated
        # tokens.
        LOGGER.error(
            'Refresh-token reuse detected for legacy token (no '
            'family_id, jti=%s)',
            jti,
        )
        return
    cascade: typing.LiteralString = (
        'MATCH (t:TokenMetadata {{family_id: {family_id}}}) '
        'WHERE t.revoked = false '
        'SET t.revoked = true, t.revoked_at = {revoked_at} '
        'RETURN count(t) AS revoked_count'
    )
    cascade_rows = await db.execute(
        cascade,
        {'family_id': family_id_val, 'revoked_at': revoked_at_iso},
        columns=['revoked_count'],
    )
    cascaded = 0
    if cascade_rows:
        raw = graph.parse_agtype(cascade_rows[0].get('revoked_count'))
        cascaded = int(raw or 0)
    LOGGER.error(
        'Refresh-token reuse detected (jti=%s, family_id=%s); '
        'revoked %d sibling tokens',
        jti,
        family_id_val,
        cascaded,
    )


async def _rotate_refresh_token(
    db: graph.Graph,
    token_str: str,
    auth_settings: settings.Auth,
) -> tuple[str, str]:
    """Validate a refresh token and mint a rotated access+refresh pair.

    Shared by the cookie-based ``/auth/token/refresh`` endpoint and the
    ``refresh_token`` grant of ``/auth/token``. The presented refresh
    token is revoked atomically; reuse of an already-revoked token
    revokes the whole family. Returns ``(access_token,
    new_refresh_token)``.

    Raises:
        fastapi.HTTPException: 401 if the token is invalid, expired, the
            wrong type, or has been revoked/reused.
    """
    try:
        payload = core.verify_token(token_str, auth_settings)
    except jwt.ExpiredSignatureError as err:
        LOGGER.warning('Token refresh failed: token expired')
        raise fastapi.HTTPException(
            status_code=401, detail='Refresh token expired'
        ) from err
    except jwt.InvalidTokenError as err:
        LOGGER.warning('Token refresh failed: invalid token - %s', err)
        raise fastapi.HTTPException(
            status_code=401, detail='Invalid refresh token'
        ) from err

    if payload.get('type') != 'refresh':
        LOGGER.warning('Token refresh failed: wrong token type')
        raise fastapi.HTTPException(
            status_code=401, detail='Invalid token type'
        )

    # Atomically revoke the refresh token AND capture its family_id
    # for the rotated pair. Matching on ``revoked = false`` in the
    # same statement as the SET closes the TOCTOU gap between the
    # check and the write: when two refreshes race on the same token
    # only the first matches; the second gets an empty result and
    # falls through to the reuse-detect branch below.
    revoked_at_iso = datetime.datetime.now(datetime.UTC).isoformat()
    revoke_query: typing.LiteralString = (
        'MATCH (n:TokenMetadata {{jti: {jti}}}) '
        "WHERE n.revoked = false AND n.token_type = 'refresh' "
        'SET n.revoked = true, n.revoked_at = {revoked_at} '
        'RETURN n.family_id AS family_id'
    )
    revoke_records = await db.execute(
        revoke_query,
        {
            'jti': payload['jti'],
            'revoked_at': revoked_at_iso,
        },
        columns=['family_id'],
    )
    if not revoke_records:
        # Either the token doesn't exist, was already revoked, or has
        # the wrong token_type. If it exists and was already revoked,
        # that's refresh-token reuse — the canonical signal of a
        # leaked/stolen refresh. Kill every un-revoked token in the
        # same family so an attacker who already rotated tokens is
        # logged out alongside the victim.
        await _handle_refresh_reuse(
            db, jti=payload['jti'], revoked_at_iso=revoked_at_iso
        )
        raise fastapi.HTTPException(
            status_code=401,
            detail='Refresh token has been revoked',
        )
    family_id_raw = graph.parse_agtype(revoke_records[0].get('family_id'))
    parent_family_id = (
        family_id_raw if isinstance(family_id_raw, str) else None
    )

    # Resolve principal (user or service account)
    subject = payload['sub']
    auth_method = payload.get('auth_method')
    principal_type: tokens.PrincipalType
    extra_claims: dict[str, typing.Any] | None = None

    if auth_method == 'client_credentials':
        sa_results = await db.match(models.ServiceAccount, {'slug': subject})
        sa = sa_results[0] if sa_results else None
        if not sa or not sa.is_active:
            LOGGER.warning(
                'Token refresh failed: service account '
                'not found or inactive (%s)',
                subject,
            )
            raise fastapi.HTTPException(
                status_code=401,
                detail='Service account not found or inactive',
            )
        principal_type = 'service_account'
        principal_id = sa.slug
        extra_claims = {'auth_method': 'client_credentials'}
    else:
        user_results = await db.match(models.User, {'email': subject})
        user = user_results[0] if user_results else None
        if not user or not user.is_active:
            LOGGER.warning(
                'Token refresh failed: user not found or inactive (%s)',
                subject,
            )
            raise fastapi.HTTPException(
                status_code=401,
                detail='User not found or inactive',
            )
        principal_type = 'user'
        principal_id = user.email

    # Mint rotated access+refresh pair, inheriting the parent's
    # family_id so a future reuse of any token in this chain can be
    # detected and the whole chain revoked.
    access_token, new_refresh_token, _ = await tokens.issue_token_pair(
        db,
        principal_type=principal_type,
        principal_id=principal_id,
        auth_settings=auth_settings,
        extra_claims=extra_claims,
        family_id=parent_family_id,
    )

    LOGGER.info(
        'Token refreshed for %s (rotated refresh token)',
        principal_id,
    )
    return access_token, new_refresh_token


@auth_router.post('/token/refresh', response_model=auth_models.TokenResponse)
@rate_limit.limiter.limit('10/minute')  # type: ignore[untyped-decorator]
async def refresh_token(
    request: fastapi.Request,
    response: fastapi.Response,
    db: graph.Pool,
    refresh_request: auth_models.TokenRefreshRequest | None = None,
) -> auth_models.TokenResponse:
    """Refresh access token and rotate refresh token (Phase 5).

    Phase 5 implements token rotation: the old refresh token is
    revoked and a new refresh token is issued alongside the new
    access token. This prevents refresh token reuse attacks.

    Args:
        refresh_request: Refresh token
        request: FastAPI request object

    Returns:
        New JWT access token and NEW refresh token (rotated)

    Raises:
        HTTPException: 401 if refresh token is invalid or revoked

    """
    auth_settings = settings.get_auth_settings()

    # The browser flow sends the refresh token as an HttpOnly cookie (C2);
    # programmatic clients (e.g. the /auth/token grant) may still send it
    # in the request body. Prefer the cookie, fall back to the body.
    token_str = request.cookies.get(_REFRESH_COOKIE) or (
        refresh_request.refresh_token if refresh_request else None
    )
    if not token_str:
        raise fastapi.HTTPException(
            status_code=401, detail='Missing refresh token'
        )

    access_token, new_refresh_token = await _rotate_refresh_token(
        db, token_str, auth_settings
    )

    _set_refresh_cookie(response, new_refresh_token)
    _set_access_cookie(response, access_token)
    return auth_models.TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,  # Phase 5: Return NEW
        expires_in=auth_settings.access_token_expire_seconds,
    )


@auth_router.post('/logout', status_code=204)
@rate_limit.limiter.limit('30/minute')  # type: ignore[untyped-decorator]
async def logout(
    request: fastapi.Request,
    response: fastapi.Response,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.get_current_user),
    ],
    revoke_all_sessions: bool = fastapi.Query(default=False),
) -> None:
    """Logout and revoke current token and session (Phase 5).

    Args:
        auth: Current authenticated user context
        revoke_all_sessions: If True, revoke all user tokens and
            delete all sessions. If False, revoke only current
            token and associated refresh token.

    """
    now_str = datetime.datetime.now(datetime.UTC).isoformat()

    # Clear the browser refresh + access cookies regardless of revoke scope.
    _clear_refresh_cookie(response)
    _clear_access_cookie(response)

    # Revoke current access token
    query: typing.LiteralString = """
    MATCH (t:TokenMetadata {{jti: {jti}}})
    SET t.revoked = true, t.revoked_at = {now}
    """
    await db.execute(
        query,
        {'jti': auth.session_id, 'now': now_str},
    )

    if revoke_all_sessions:
        if auth.service_account:
            # Revoke all service account tokens
            revoke_q: typing.LiteralString = """
            MATCH (s:ServiceAccount {{slug: {slug}}})
                  <-[:ISSUED_TO]-(t:TokenMetadata)
            WHERE t.revoked = false
            SET t.revoked = true,
                t.revoked_at = {now}
            """
            await db.execute(
                revoke_q,
                {
                    'slug': auth.service_account.slug,
                    'now': now_str,
                },
            )
        elif auth.user:
            # Revoke all user tokens
            revoke_q2: typing.LiteralString = """
            MATCH (u:User {{email: {email}}})
                  <-[:ISSUED_TO]-(t:TokenMetadata)
            WHERE t.revoked = false
            SET t.revoked = true,
                t.revoked_at = {now}
            """
            await db.execute(
                revoke_q2,
                {
                    'email': auth.user.email,
                    'now': now_str,
                },
            )

            # Delete all sessions
            del_q: typing.LiteralString = """
            MATCH (u:User {{email: {email}}})
                  <-[:SESSION_FOR]-(s:Session)
            DETACH DELETE s
            """
            await db.execute(
                del_q,
                {'email': auth.user.email},
            )
    else:
        # Revoke only associated refresh token
        issued_q: typing.LiteralString = """
        MATCH (t:TokenMetadata {{jti: {jti}}})
        RETURN t.issued_at as issued_at
        """
        records = await db.execute(
            issued_q,
            {'jti': auth.session_id},
            ['issued_at'],
        )

        if records:
            issued_at = graph.parse_agtype(records[0]['issued_at'])
            # Use generic ISSUED_TO traversal
            revoke_query: typing.LiteralString = """
            MATCH (t:TokenMetadata {{jti: {jti}}})
                  -[:ISSUED_TO]->(principal)
            MATCH (principal)
                  <-[:ISSUED_TO]-(rt:TokenMetadata)
            WHERE rt.token_type = 'refresh'
              AND rt.revoked = false
              AND rt.issued_at = {issued_at}
            SET rt.revoked = true,
                rt.revoked_at = {now}
            """
            await db.execute(
                revoke_query,
                {
                    'jti': auth.session_id,
                    'issued_at': issued_at,
                    'now': now_str,
                },
            )

    LOGGER.info(
        '%s logged out (revoke_all=%s)',
        auth.principal_name,
        revoke_all_sessions,
    )


@auth_router.get('/oauth/{provider}')
@rate_limit.limiter.limit('3/minute')  # type: ignore[untyped-decorator]
async def oauth_login(
    request: fastapi.Request,
    db: graph.Pool,
    provider: str,
    redirect_uri: str = fastapi.Query(default='/dashboard'),
) -> fastapi.responses.RedirectResponse:
    """Initiate OAuth login flow.

    Every login provider is now a login-capable ``Integration`` whose
    plugin implements the ``identity`` capability; the authorization
    URL and token exchange are owned entirely by that plugin's
    handler via :mod:`imbi_api.identity.flows`.

    Args:
        provider: Login-Integration slug
        redirect_uri: Where to redirect after successful auth

    Returns:
        Redirect to the provider's authorization page

    Raises:
        HTTPException: 404 if provider not enabled or invalid, 503 if
            its plugin isn't loaded

    """
    # Provider is an arbitrary slug. Resolve via login_providers.
    app = await login_providers.get_login_app(db, provider)
    if app is None or app.status != 'active':
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Invalid provider: {provider}',
        )

    # Enforce the redirect-URI allow-list before it is signed into the
    # OAuth state: the callback delivers tokens to this destination, so an
    # off-origin value would exfiltrate them (C2). The SPA sends an
    # absolute same-origin callback (``window.location.origin/auth/callback``)
    # and UI+API share a host behind the ingress, so the API's own public
    # origin must be trusted alongside any configured CORS origins.
    server_config = settings.get_server_config()
    allowed_origins = list(server_config.cors_allowed_origins)
    own = urlparse.urlparse(server_config.public_base_url)
    if own.scheme and own.netloc:
        allowed_origins.append(f'{own.scheme}://{own.netloc}')
    # On a multi-host deployment the SPA's same-origin callback is on the
    # host this request reached, not public_base_url's, so trust that
    # origin too (it is validated against the configured trusted set).
    request_base = _request_urls.public_base_url_for_request(request)
    request_own = _request_urls.request_origin(request)
    if request_own is not None:
        allowed_origins.append(request_own)
    if not _is_safe_redirect_uri(redirect_uri, allowed_origins):
        raise fastapi.HTTPException(
            status_code=400,
            detail='Invalid redirect_uri',
        )

    callback_url = settings.oauth_callback_url(provider, base_url=request_base)
    try:
        url, _state, _polling = await identity_flows.start_flow(
            db,
            integration_id=app.integration_id,
            redirect_uri=callback_url,
            actor_user_id=None,
            return_to=redirect_uri,
            intent='login',
        )
    except plugin_errors.PluginNotFoundError as exc:
        raise fastapi.HTTPException(
            status_code=503,
            detail=f'Login provider {provider!r} not loaded',
        ) from exc
    LOGGER.info(
        'Login flow initiated for provider %s (integration_id=%s)',
        provider,
        app.integration_id,
    )
    return fastapi.responses.RedirectResponse(url=url)


@auth_router.get('/oauth/{provider}/callback')
@rate_limit.limiter.limit('10/minute')  # type: ignore[untyped-decorator]
async def oauth_callback(
    request: fastapi.Request,
    db: graph.Pool,
    provider: str,
    valkey_client: OptionalValkeyClient,
    code: str | None = fastapi.Query(default=None),
    state: str | None = fastapi.Query(default=None),
    error: str | None = fastapi.Query(default=None),
    error_description: str | None = fastapi.Query(default=None),
) -> fastapi.responses.RedirectResponse:
    """Handle OAuth provider callback.

    After user authorizes on OAuth provider, they're redirected
    here with an authorization code. We exchange it for tokens
    and create/login user.

    Args:
        provider: OAuth provider
        code: Authorization code from provider
        state: State parameter for CSRF protection
        error: Error code if auth failed
        error_description: Human-readable error description

    Returns:
        Redirect to frontend with token or error

    """
    auth_settings = settings.get_auth_settings()

    # Handle OAuth errors
    if error:
        LOGGER.warning(
            'OAuth callback error: %s - %s',
            error,
            error_description,
        )
        return fastapi.responses.RedirectResponse(
            url=f'/auth/callback?error={error}'
        )

    try:
        # Validate required parameters
        if not code or not state:
            raise ValueError('Missing required parameters: code and state')
        return await _login_callback(
            db,
            provider,
            code,
            state,
            auth_settings,
            valkey_client,
        )
    except (
        ValueError,
        KeyError,
        jwt.InvalidTokenError,
        fastapi.HTTPException,
        # complete_login_flow raises RuntimeError when the Valkey replay-
        # protection backend is unavailable; surface that as the normal
        # auth-failed redirect so a missing dependency doesn't return a
        # bare 500.
        RuntimeError,
    ) as err:
        LOGGER.exception('OAuth callback failed: %s', err)
        return fastapi.responses.RedirectResponse(
            url='/auth/callback?error=authentication_failed'
        )


async def _login_callback(
    db: graph.Graph,
    provider: str,
    code: str,
    state: str,
    auth_settings: settings.Auth,
    valkey_client: valkey_module.Valkey | None,
) -> fastapi.responses.RedirectResponse:
    """Complete a login-intent flow handled by a login-Integration's plugin.

    Every login provider is a login-capable ``Integration``; the
    authorization-code exchange is owned by the plugin's identity
    capability handler via :func:`identity_flows.complete_login_flow`.
    Persists an :class:`imbi_common.models.IdentityConnection` once the
    local user has been resolved / provisioned.
    """
    (
        profile,
        credentials,
        integration_id,
        return_to,
    ) = await identity_flows.complete_login_flow(
        db,
        code=code,
        state_token=state,
        valkey_client=valkey_client,
    )
    if not profile.email:
        raise ValueError(
            'Login provider returned no email; cannot establish a session'
        )

    user_results = await db.match(models.User, {'email': profile.email})
    existing = user_results[0] if user_results else None

    if existing is not None:
        if not auth_settings.oauth_auto_link_by_email:
            raise ValueError(
                f'A user with email {profile.email} already exists. '
                'OAuth auto-link by email is disabled.'
            )
        if not profile.email_verified:
            raise ValueError(
                'Refusing to auto-link login to existing '
                f'user {profile.email}: provider did not assert '
                'email_verified=true.'
            )
        user = existing
        LOGGER.info(
            'Linked login provider %s to existing user %s',
            provider,
            user.email,
        )
    else:
        if not auth_settings.oauth_auto_create_users:
            raise ValueError('User auto-creation disabled')
        user = models.User(
            email=profile.email,
            display_name=profile.name or profile.email,
            password_hash=None,
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
            avatar_url=(
                pydantic.HttpUrl(profile.avatar_url)
                if profile.avatar_url
                else None
            ),
        )
        await db.merge(user, ['email'])
        LOGGER.info(
            'Created new user %s via login provider %s',
            user.email,
            provider,
        )

    if user.is_service_account:
        raise ValueError('Service accounts cannot use login providers')

    # Persist the IdentityConnection now that we have a user_id.
    await identity_repository.upsert_connection(
        db,
        integration_id,
        user.id,
        profile,
        credentials,
    )

    at, rt, meta = await tokens.issue_token_pair(
        db,
        principal_type='user',
        principal_id=user.email,
        auth_settings=auth_settings,
    )
    user.last_login = meta['issued_at']
    await db.merge(user, match_on=['email'])

    # Access token via the URL fragment; refresh token via an HttpOnly
    # cookie (C2) so it is never exposed in the fragment.
    target = return_to or '/dashboard'
    redirect_url = (
        f'{target}#'
        f'access_token={at}&'
        f'token_type=bearer&'
        f'expires_in='
        f'{auth_settings.access_token_expire_seconds}'
    )
    redirect = fastapi.responses.RedirectResponse(url=redirect_url)
    _set_refresh_cookie(redirect, rt)
    _set_access_cookie(redirect, at)
    return redirect
