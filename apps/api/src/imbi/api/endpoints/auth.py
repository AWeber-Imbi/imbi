"""Authentication endpoints for login, token refresh, and logout."""

import datetime
import json
import logging
import typing
from urllib import parse as urlparse

import fastapi
import httpx
import jwt
import pydantic
import pyotp
from imbi_common import graph
from imbi_common.auth import core, encryption

from imbi_api import models, settings
from imbi_api.auth import models as auth_models
from imbi_api.auth import oauth, permissions, tokens
from imbi_api.auth import password as password_auth
from imbi_api.middleware import rate_limit

LOGGER = logging.getLogger(__name__)

auth_router = fastapi.APIRouter(prefix='/auth', tags=['Authentication'])


@auth_router.get(
    '/providers', response_model=auth_models.AuthProvidersResponse
)
async def get_auth_providers() -> auth_models.AuthProvidersResponse:
    """Get available authentication providers configuration.

    Returns a list of enabled authentication providers to allow the UI
    to dynamically configure the login interface.

    Returns:
        AuthProvidersResponse: List of providers with configuration

    """
    auth_settings = settings.get_auth_settings()
    providers: list[auth_models.AuthProvider] = []

    # Local password authentication
    if auth_settings.local_auth_enabled:
        providers.append(
            auth_models.AuthProvider(
                id='local',
                type='password',
                name='Email/Password',
                enabled=True,
                icon='lock',
            )
        )

    # Google OAuth
    if auth_settings.oauth_google_enabled:
        providers.append(
            auth_models.AuthProvider(
                id='google',
                type='oauth',
                name='Google',
                enabled=True,
                auth_url='/auth/oauth/google',
                icon='google',
            )
        )

    # GitHub OAuth
    if auth_settings.oauth_github_enabled:
        providers.append(
            auth_models.AuthProvider(
                id='github',
                type='oauth',
                name='GitHub',
                enabled=True,
                auth_url='/auth/oauth/github',
                icon='github',
            )
        )

    # Generic OIDC
    if auth_settings.oauth_oidc_enabled:
        providers.append(
            auth_models.AuthProvider(
                id='oidc',
                type='oauth',
                name=auth_settings.oauth_oidc_name,
                enabled=True,
                auth_url='/auth/oauth/oidc',
                icon='key',
            )
        )

    return auth_models.AuthProvidersResponse(
        providers=providers,
        default_redirect='/dashboard',
    )


@auth_router.post('/token', response_model=models.OAuth2TokenResponse)
@rate_limit.limiter.limit('10/minute')  # type: ignore[untyped-decorator]
async def token(
    request: fastapi.Request,
    db: graph.Pool,
    grant_type: typing.Annotated[str, fastapi.Form()],
    client_id: typing.Annotated[str, fastapi.Form()],
    client_secret: typing.Annotated[str, fastapi.Form()],
    scope: typing.Annotated[str | None, fastapi.Form()] = None,
) -> models.OAuth2TokenResponse:
    """OAuth2 token endpoint for client credentials grant.

    Accepts form-encoded parameters per RFC 6749.

    Args:
        grant_type: Must be 'client_credentials'
        client_id: Client credential ID (cc_...)
        client_secret: Client secret
        scope: Optional space-separated scopes

    Returns:
        OAuth2TokenResponse with access and refresh tokens

    """
    if grant_type != 'client_credentials':
        raise fastapi.HTTPException(
            status_code=400,
            detail='Unsupported grant_type; use client_credentials',
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
    if not password_auth.verify_password(
        client_secret, cred_data['client_secret_hash']
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


@auth_router.post('/login', response_model=auth_models.TokenResponse)
@rate_limit.limiter.limit('5/minute')  # type: ignore[untyped-decorator]
async def login(
    request: fastapi.Request,
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

    if not user or not user.is_active:
        LOGGER.warning(
            'Login failed for email %s: user not found or inactive',
            email,
        )
        raise fastapi.HTTPException(
            status_code=401,
            detail='Invalid credentials',
        )

    if user.is_service_account:
        LOGGER.warning(
            'Login failed for email %s: service accounts '
            'cannot use password login',
            email,
        )
        raise fastapi.HTTPException(
            status_code=403,
            detail='Service accounts cannot use password login',
        )

    # Check if user has password authentication enabled
    if not user.password_hash:
        LOGGER.warning(
            'Login failed for email %s: password authentication not enabled',
            email,
        )
        raise fastapi.HTTPException(
            status_code=401,
            detail='Password authentication not available for this account',
        )

    # Verify password
    if not password_auth.verify_password(password, user.password_hash):
        LOGGER.warning('Login failed for email %s: invalid password', email)
        raise fastapi.HTTPException(
            status_code=401,
            detail='Invalid credentials',
        )

    # Check if password needs rehashing
    if password_auth.needs_rehash(user.password_hash):
        user.password_hash = password_auth.hash_password(password)
        await db.merge(user, match_on=['email'])
        LOGGER.info('Rehashed password for user %s', user.email)

    # Phase 5: Check if MFA is enabled
    totp_query: typing.LiteralString = """
    MATCH (u:User {{email: {email}}})
          <-[:MFA_FOR]-(t:TOTPSecret)
    RETURN t AS n
    """
    totp_records = await db.execute(
        totp_query,
        {'email': user.email},
    )

    if totp_records:
        totp_data = graph.parse_agtype(totp_records[0]['n'])

        if totp_data.get('enabled', False):
            # MFA is enabled - code is required
            if not mfa_code:
                raise fastapi.HTTPException(
                    status_code=401,
                    detail='MFA code required',
                    headers={'X-MFA-Required': 'true'},
                )

            auth_settings = settings.get_auth_settings()

            # Decrypt TOTP secret
            encryptor = encryption.TokenEncryption.get_instance()
            try:
                secret = encryptor.decrypt(totp_data['secret'])
                if secret is None:
                    raise ValueError('Decryption returned None')
            except (ValueError, TypeError) as err:
                LOGGER.error('Failed to decrypt TOTP secret: %s', err)
                raise fastapi.HTTPException(
                    status_code=500,
                    detail='Failed to decrypt MFA secret',
                ) from err

            totp = pyotp.TOTP(
                secret,
                interval=auth_settings.mfa_totp_period,
                digits=auth_settings.mfa_totp_digits,
            )

            # Try TOTP verification first (with clock skew)
            if totp.verify(mfa_code, valid_window=1):
                # Update last used timestamp
                now_str = datetime.datetime.now(datetime.UTC).isoformat()
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
                    user.email,
                )
            else:
                # Try backup codes
                backup_codes = totp_data.get('backup_codes', [])
                valid_backup = False

                for i, hashed_code in enumerate(backup_codes):
                    if password_auth.verify_password(mfa_code, hashed_code):
                        # Remove used backup code
                        backup_codes.pop(i)
                        update_q2: typing.LiteralString = """
                        MATCH (u:User {{email: {email}}})
                              <-[:MFA_FOR]-(t:TOTPSecret)
                        SET t.backup_codes = {backup_codes}
                        """
                        await db.execute(
                            update_q2,
                            {
                                'email': user.email,
                                'backup_codes': json.dumps(backup_codes),
                            },
                        )

                        valid_backup = True
                        LOGGER.info(
                            'MFA verified via backup code for user %s',
                            user.email,
                        )
                        break

                if not valid_backup:
                    raise fastapi.HTTPException(
                        status_code=401,
                        detail='Invalid MFA code',
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

    LOGGER.info('User %s logged in successfully', user.email)

    return auth_models.TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=auth_settings.access_token_expire_seconds,
    )


@auth_router.post('/token/refresh', response_model=auth_models.TokenResponse)
@rate_limit.limiter.limit('10/minute')  # type: ignore[untyped-decorator]
async def refresh_token(
    request: fastapi.Request,
    db: graph.Pool,
    refresh_request: auth_models.TokenRefreshRequest,
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

    # Decode and validate refresh token
    try:
        payload = core.verify_token(
            refresh_request.refresh_token, auth_settings
        )
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

    # Verify token type
    if payload.get('type') != 'refresh':
        LOGGER.warning('Token refresh failed: wrong token type')
        raise fastapi.HTTPException(
            status_code=401, detail='Invalid token type'
        )

    # Atomically revoke the refresh token. Matching on
    # ``revoked = false`` in the same statement as the SET closes
    # the TOCTOU gap between the check and the write: when two
    # refreshes race on the same token, only the first matches, so
    # the second gets ``revoked_count = 0`` and a clean 401 instead
    # of AGE raising ``Entity failed to be updated: 3`` on the
    # concurrently-updated vertex.
    revoke_query: typing.LiteralString = (
        'MATCH (n:TokenMetadata {{jti: {jti}}}) '
        "WHERE n.revoked = false AND n.token_type = 'refresh' "
        'SET n.revoked = true, n.revoked_at = {revoked_at} '
        'RETURN count(n) AS revoked_count'
    )
    revoke_records = await db.execute(
        revoke_query,
        {
            'jti': payload['jti'],
            'revoked_at': datetime.datetime.now(datetime.UTC).isoformat(),
        },
        columns=['revoked_count'],
    )
    revoked = 0
    if revoke_records:
        raw = graph.parse_agtype(revoke_records[0].get('revoked_count'))
        revoked = int(raw or 0)
    if revoked == 0:
        LOGGER.warning(
            'Token refresh failed: token revoked or not found (jti=%s)',
            payload['jti'],
        )
        raise fastapi.HTTPException(
            status_code=401,
            detail='Refresh token has been revoked',
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

    # Mint rotated access+refresh pair
    access_token, new_refresh_token, _ = await tokens.issue_token_pair(
        db,
        principal_type=principal_type,
        principal_id=principal_id,
        auth_settings=auth_settings,
        extra_claims=extra_claims,
    )

    LOGGER.info(
        'Token refreshed for %s (rotated refresh token)',
        principal_id,
    )

    return auth_models.TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,  # Phase 5: Return NEW
        expires_in=auth_settings.access_token_expire_seconds,
    )


@auth_router.post('/logout', status_code=204)
async def logout(
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
    provider: str,
    redirect_uri: str = fastapi.Query(default='/dashboard'),
) -> fastapi.responses.RedirectResponse:
    """Initiate OAuth login flow.

    Args:
        provider: OAuth provider ('google', 'github', 'oidc')
        redirect_uri: Where to redirect after successful auth

    Returns:
        Redirect to OAuth provider's authorization page

    Raises:
        HTTPException: 400 if provider not enabled or invalid

    """
    auth_settings = settings.get_auth_settings()

    # Validate provider is enabled
    if provider not in ['google', 'github', 'oidc']:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Invalid provider: {provider}',
        )

    if provider == 'google' and not auth_settings.oauth_google_enabled:
        raise fastapi.HTTPException(
            status_code=400, detail='Google OAuth not enabled'
        )
    elif provider == 'github' and not auth_settings.oauth_github_enabled:
        raise fastapi.HTTPException(
            status_code=400, detail='GitHub OAuth not enabled'
        )
    elif provider == 'oidc' and not auth_settings.oauth_oidc_enabled:
        raise fastapi.HTTPException(
            status_code=400, detail='OIDC OAuth not enabled'
        )

    # Generate OAuth state for CSRF protection
    state_token, _ = oauth.generate_oauth_state(
        provider, redirect_uri, auth_settings
    )

    # Build callback URL
    base_url = auth_settings.oauth_callback_base_url
    callback_url = f'{base_url}/auth/oauth/{provider}/callback'

    # Build authorization URL based on provider
    auth_url = ''
    if provider == 'google':
        params = {
            'client_id': (auth_settings.oauth_google_client_id or ''),
            'redirect_uri': callback_url,
            'response_type': 'code',
            'scope': 'openid email profile',
            'state': state_token,
        }
        auth_url = (
            'https://accounts.google.com/o/oauth2/v2/auth?'
            + urlparse.urlencode(params)
        )
    elif provider == 'github':
        params = {
            'client_id': (auth_settings.oauth_github_client_id or ''),
            'redirect_uri': callback_url,
            'scope': 'read:user user:email',
            'state': state_token,
        }
        auth_url = (
            'https://github.com/login/oauth/authorize?'
            + urlparse.urlencode(params)
        )
    elif provider == 'oidc':
        issuer = (auth_settings.oauth_oidc_issuer_url or '').rstrip('/')
        params = {
            'client_id': (auth_settings.oauth_oidc_client_id or ''),
            'redirect_uri': callback_url,
            'response_type': 'code',
            'scope': 'openid email profile',
            'state': state_token,
        }
        auth_url = (
            f'{issuer}/protocol/openid-connect/auth?'
            + urlparse.urlencode(params)
        )

    LOGGER.info('OAuth login initiated for provider %s', provider)
    return fastapi.responses.RedirectResponse(url=auth_url)


@auth_router.get('/oauth/{provider}/callback')
async def oauth_callback(
    db: graph.Pool,
    provider: str,
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

        # Verify state parameter
        state_data = oauth.verify_oauth_state(state, auth_settings)

        if state_data.provider != provider:
            raise ValueError('Provider mismatch')

        # Exchange code for tokens
        base_url = auth_settings.oauth_callback_base_url
        callback_url = f'{base_url}/auth/oauth/{provider}/callback'
        token_response = await oauth.exchange_oauth_code(
            provider, code, callback_url, auth_settings
        )

        # Fetch user profile
        profile = await oauth.fetch_oauth_profile(
            provider,
            token_response['access_token'],
            auth_settings,
        )

        # Find or create OAuth identity
        oauth_identity = await find_or_create_oauth_identity(
            db, provider, profile, token_response, auth_settings
        )

        # Get associated user — fetch via graph query
        user_q: typing.LiteralString = """
        MATCH (oi:OAuthIdentity {{
            provider: {provider},
            provider_user_id: {provider_user_id}
        }})-[:OAUTH_IDENTITY]->(u:User)
        RETURN u
        """
        user_records = await db.execute(
            user_q,
            {
                'provider': provider,
                'provider_user_id': profile['id'],
            },
            ['u'],
        )
        if not user_records:
            raise ValueError('No user linked to OAuth identity')
        user_data = graph.parse_agtype(user_records[0]['u'])
        user = models.User(**user_data)

        if user.is_service_account:
            raise ValueError(
                'Service accounts cannot use OAuth authentication'
            )

        # Create JWT tokens
        at, rt, meta = await tokens.issue_token_pair(
            db,
            principal_type='user',
            principal_id=user.email,
            auth_settings=auth_settings,
        )
        now = meta['issued_at']

        # Update user last_login
        user.last_login = now
        await db.merge(user, match_on=['email'])

        # Update OAuth identity last_used
        oauth_identity.last_used = now
        await db.merge(
            oauth_identity,
            match_on=['provider', 'provider_user_id'],
        )

        LOGGER.info(
            'OAuth login successful for user %s via %s',
            user.email,
            provider,
        )

        # Redirect to frontend with tokens in URL fragment
        redirect_url = (
            f'{state_data.redirect_uri}#'
            f'access_token={at}&'
            f'refresh_token={rt}&'
            f'token_type=bearer&'
            f'expires_in='
            f'{auth_settings.access_token_expire_seconds}'
        )
        return fastapi.responses.RedirectResponse(url=redirect_url)

    except (
        ValueError,
        KeyError,
        jwt.InvalidTokenError,
        httpx.HTTPError,
        fastapi.HTTPException,
    ) as err:
        LOGGER.exception('OAuth callback failed: %s', err)
        return fastapi.responses.RedirectResponse(
            url='/auth/callback?error=authentication_failed'
        )


async def find_or_create_oauth_identity(
    db: graph.Graph,
    provider: str,
    profile: dict[str, typing.Any],
    token_response: dict[str, typing.Any],
    auth_settings: settings.Auth,
) -> models.OAuthIdentity:
    """Find existing or create new OAuth identity and user.

    Logic:
    1. Check if OAuth identity exists (by provider +
       provider_user_id)
    2. If exists, return it (with updated tokens)
    3. If not exists:
       a. Check if auto-link by email is enabled and user exists
       b. Otherwise create new user
       c. Create OAuth identity linked to user

    Args:
        db: Graph database instance
        provider: OAuth provider identifier
        profile: Normalized user profile from OAuth provider
        token_response: Token response from OAuth provider
        auth_settings: Auth settings instance

    Returns:
        OAuthIdentity with linked user

    Raises:
        ValueError: If user auto-creation disabled and no user
            found
        ValueError: If email domain not in allowed list (Google
            OAuth)

    """
    # Enforce domain restrictions for Google OAuth
    if provider == 'google' and auth_settings.oauth_google_allowed_domains:
        email_domain = profile['email'].split('@')[1].lower()
        allowed = [
            d.lower() for d in auth_settings.oauth_google_allowed_domains
        ]
        if email_domain not in allowed:
            raise ValueError(
                f'Email domain {email_domain} not in allowed'
                f' domains: '
                + ', '.join(auth_settings.oauth_google_allowed_domains)
            )

    # Try to find existing OAuth identity
    identity_results = await db.match(
        models.OAuthIdentity,
        {
            'provider': provider,
            'provider_user_id': profile['id'],
        },
    )
    identity = identity_results[0] if identity_results else None

    if identity:
        # Phase 5: Encrypt and update tokens
        encryptor = encryption.TokenEncryption.get_instance()
        identity.set_encrypted_tokens(
            token_response['access_token'],
            token_response.get('refresh_token'),
            encryptor,
        )
        identity.token_expires_at = datetime.datetime.now(
            datetime.UTC
        ) + datetime.timedelta(seconds=token_response.get('expires_in', 3600))
        await db.merge(
            identity,
            match_on=['provider', 'provider_user_id'],
        )

        return identity  # type: ignore[no-any-return]

    # OAuth identity doesn't exist - need to create it

    # Check if we should auto-link to existing user by email
    user = None
    if auth_settings.oauth_auto_link_by_email:
        user_results = await db.match(models.User, {'email': profile['email']})
        user = user_results[0] if user_results else None

    # Create new user if doesn't exist
    if not user:
        if not auth_settings.oauth_auto_create_users:
            raise ValueError('User auto-creation disabled')

        # Create user from OAuth profile
        user = models.User(
            email=profile['email'],
            display_name=profile['name'],
            password_hash=None,  # OAuth-only user
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
            avatar_url=profile.get('avatar_url'),
        )

        await db.merge(user)
        LOGGER.info(
            'Created new user %s via OAuth %s',
            user.email,
            provider,
        )

    # Create OAuth identity (Phase 5: with encrypted tokens)
    now = datetime.datetime.now(datetime.UTC)
    identity = models.OAuthIdentity(
        provider=typing.cast(
            typing.Literal['google', 'github', 'oidc'],
            provider,
        ),
        provider_user_id=profile['id'],
        email=profile['email'],
        display_name=profile['name'],
        avatar_url=profile.get('avatar_url'),
        access_token=None,  # Set encrypted tokens below
        refresh_token=None,  # Set encrypted tokens below
        token_expires_at=now
        + datetime.timedelta(seconds=token_response.get('expires_in', 3600)),
        linked_at=now,
        last_used=now,
        raw_profile=profile,
        user=user,
    )

    # Phase 5: Encrypt tokens before storing
    encryptor = encryption.TokenEncryption.get_instance()
    identity.set_encrypted_tokens(
        token_response['access_token'],
        token_response.get('refresh_token'),
        encryptor,
    )

    await db.merge(identity)

    # Create relationship via Cypher
    rel_query: typing.LiteralString = """
    MATCH (oi:OAuthIdentity {{
        provider: {provider},
        provider_user_id: {provider_user_id}
    }})
    MATCH (u:User {{email: {email}}})
    MERGE (oi)-[:OAUTH_IDENTITY]->(u)
    """
    await db.execute(
        rel_query,
        {
            'provider': provider,
            'provider_user_id': profile['id'],
            'email': user.email,
        },
    )

    LOGGER.info(
        'Created OAuth identity for user %s via %s',
        user.email,
        provider,
    )

    return identity
