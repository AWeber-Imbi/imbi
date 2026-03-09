"""Authentication endpoints for login, token refresh, and logout."""

import datetime
import logging
import typing
from urllib import parse as urlparse

import fastapi
import httpx
import jwt
import pydantic
import pyotp
from imbi_common import neo4j
from imbi_common.auth import core, encryption

from imbi_api import models, settings
from imbi_api.auth import models as auth_models
from imbi_api.auth import oauth, permissions
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
    providers = []

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
    query = """
    MATCH (c:ClientCredential {client_id: $client_id})
          -[:OWNED_BY]->(s:ServiceAccount)
    RETURN c, s
    """
    async with neo4j.run(query, client_id=client_id) as result:
        records = await result.data()

    if not records:
        raise fastapi.HTTPException(
            status_code=401,
            detail='Invalid client credentials',
        )

    cred_data = neo4j.convert_neo4j_types(records[0]['c'])
    sa_data = neo4j.convert_neo4j_types(records[0]['s'])

    # Check revoked
    if cred_data.get('revoked', False):
        raise fastapi.HTTPException(
            status_code=401,
            detail='Client credential has been revoked',
        )

    # Check expired
    expires_at = cred_data.get('expires_at')
    if expires_at and expires_at < datetime.datetime.now(datetime.UTC):
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
    cred_scopes = set(cred_data.get('scopes', []))
    requested_scopes = set(scope.split()) if scope else set()
    if requested_scopes and cred_scopes:
        granted_scopes = requested_scopes & cred_scopes
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
    access_token = core.create_access_token(
        sa.slug,
        extra_claims=extra_claims,
        auth_settings=auth_settings,
    )
    access_claims = core.verify_token(access_token, auth_settings)

    refresh_token = core.create_refresh_token(
        sa.slug,
        extra_claims=extra_claims,
        auth_settings=auth_settings,
    )
    refresh_claims = core.verify_token(refresh_token, auth_settings)

    # Store token metadata (link to ServiceAccount)
    now = datetime.datetime.now(datetime.UTC)

    access_meta_query = """
    MATCH (s:ServiceAccount {slug: $slug})
    CREATE (t:TokenMetadata {
        jti: $jti,
        token_type: 'access',
        issued_at: datetime(),
        expires_at: datetime($expires_at),
        revoked: false
    })-[:ISSUED_TO]->(s)
    """
    async with neo4j.run(
        access_meta_query,
        jti=access_claims['jti'],
        expires_at=(
            now
            + datetime.timedelta(
                seconds=(auth_settings.access_token_expire_seconds)
            )
        ).isoformat(),
        slug=sa.slug,
    ) as result:
        await result.consume()

    refresh_meta_query = """
    MATCH (s:ServiceAccount {slug: $slug})
    CREATE (t:TokenMetadata {
        jti: $jti,
        token_type: 'refresh',
        issued_at: datetime(),
        expires_at: datetime($expires_at),
        revoked: false
    })-[:ISSUED_TO]->(s)
    """
    async with neo4j.run(
        refresh_meta_query,
        jti=refresh_claims['jti'],
        expires_at=(
            now
            + datetime.timedelta(
                seconds=(auth_settings.refresh_token_expire_seconds)
            )
        ).isoformat(),
        slug=sa.slug,
    ) as result:
        await result.consume()

    # Update last_used on credential, last_authenticated on SA
    update_query = """
    MATCH (c:ClientCredential {client_id: $client_id})
    SET c.last_used = datetime()
    WITH c
    MATCH (c)-[:OWNED_BY]->(s:ServiceAccount)
    SET s.last_authenticated = datetime()
    """
    async with neo4j.run(update_query, client_id=client_id) as result:
        await result.consume()

    LOGGER.info(
        'Client credentials token issued for service '
        'account %s (client_id=%s)',
        sa.slug,
        client_id,
    )

    scope_str = ' '.join(sorted(granted_scopes)) if granted_scopes else None

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
        HTTPException: 401 if credentials are invalid or MFA code required
            Returns X-MFA-Required: true header if MFA is required

    """
    # Fetch user from database
    user = await neo4j.fetch_node(models.User, {'email': email})

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
        await neo4j.upsert(user, {'email': user.email})
        LOGGER.info('Rehashed password for user %s', user.email)

    # Phase 5: Check if MFA is enabled
    totp_query = """
    MATCH (u:User {email: $email})<-[:MFA_FOR]-(t:TOTPSecret)
    RETURN t
    """
    async with neo4j.run(totp_query, email=user.email) as result:
        totp_records = await result.data()

    if totp_records:
        totp_data = totp_records[0]['t']

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
                    status_code=500, detail='Failed to decrypt MFA secret'
                ) from err

            totp = pyotp.TOTP(
                secret,
                interval=auth_settings.mfa_totp_period,
                digits=auth_settings.mfa_totp_digits,
            )

            # Try TOTP verification first (with clock skew tolerance)
            if totp.verify(mfa_code, valid_window=1):
                # Update last used timestamp
                update_query = """
                MATCH (u:User {email: $email})<-[:MFA_FOR]-(t:TOTPSecret)
                SET t.last_used = datetime()
                """
                async with neo4j.run(update_query, email=user.email) as result:
                    await result.consume()

                LOGGER.info('MFA verified via TOTP for user %s', user.email)
            else:
                # Try backup codes
                backup_codes = totp_data.get('backup_codes', [])
                valid_backup = False

                for i, hashed_code in enumerate(backup_codes):
                    if password_auth.verify_password(mfa_code, hashed_code):
                        # Remove used backup code
                        backup_codes.pop(i)
                        update_query = """
                        MATCH (u:User {email: $email})
                              <-[:MFA_FOR]-(t:TOTPSecret)
                        SET t.backup_codes = $backup_codes
                        """
                        async with neo4j.run(
                            update_query,
                            email=user.email,
                            backup_codes=backup_codes,
                        ) as result:
                            await result.consume()

                        valid_backup = True
                        LOGGER.info(
                            'MFA verified via backup code for user %s',
                            user.email,
                        )
                        break

                if not valid_backup:
                    raise fastapi.HTTPException(
                        status_code=401, detail='Invalid MFA code'
                    )

    # Create tokens
    auth_settings = settings.get_auth_settings()
    access_token = core.create_access_token(
        user.email, auth_settings=auth_settings
    )
    access_claims = core.verify_token(access_token, auth_settings)
    access_jti = access_claims['jti']

    refresh_token = core.create_refresh_token(
        user.email, auth_settings=auth_settings
    )
    refresh_claims = core.verify_token(refresh_token, auth_settings)
    refresh_jti = refresh_claims['jti']

    # Store token metadata for access token
    now = datetime.datetime.now(datetime.UTC)
    access_token_meta = models.TokenMetadata(
        jti=access_jti,
        token_type='access',
        issued_at=now,
        expires_at=now
        + datetime.timedelta(
            seconds=auth_settings.access_token_expire_seconds
        ),
        user=user,
    )
    await neo4j.create_node(access_token_meta)

    # Store token metadata for refresh token
    refresh_token_meta = models.TokenMetadata(
        jti=refresh_jti,
        token_type='refresh',
        issued_at=now,
        expires_at=now
        + datetime.timedelta(
            seconds=auth_settings.refresh_token_expire_seconds
        ),
        user=user,
    )
    await neo4j.create_node(refresh_token_meta)

    # Update last login timestamp
    user.last_login = now
    await neo4j.upsert(user, {'email': user.email})

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
    refresh_request: auth_models.TokenRefreshRequest,
) -> auth_models.TokenResponse:
    """Refresh access token and rotate refresh token (Phase 5).

    Phase 5 implements token rotation: the old refresh token is revoked
    and a new refresh token is issued alongside the new access token.
    This prevents refresh token reuse attacks.

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

    # Check if refresh token is revoked
    token_meta = await neo4j.fetch_node(
        models.TokenMetadata, {'jti': payload['jti']}
    )
    if not token_meta or token_meta.revoked:
        LOGGER.warning(
            'Token refresh failed: token revoked or not found (jti=%s)',
            payload['jti'],
        )
        raise fastapi.HTTPException(
            status_code=401, detail='Refresh token has been revoked'
        )

    # Phase 5: Revoke old refresh token (token rotation)
    token_meta.revoked = True
    token_meta.revoked_at = datetime.datetime.now(datetime.UTC)
    await neo4j.upsert(token_meta, {'jti': payload['jti']})

    # Resolve principal (user or service account)
    subject = payload['sub']
    auth_method = payload.get('auth_method')
    extra_claims: dict[str, typing.Any] = {}

    if auth_method == 'client_credentials':
        sa = await neo4j.fetch_node(models.ServiceAccount, {'slug': subject})
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
        principal_id = sa.slug
        extra_claims = {'auth_method': 'client_credentials'}
    else:
        user = await neo4j.fetch_node(models.User, {'email': subject})
        if not user or not user.is_active:
            LOGGER.warning(
                'Token refresh failed: user not found or inactive (%s)',
                subject,
            )
            raise fastapi.HTTPException(
                status_code=401,
                detail='User not found or inactive',
            )
        principal_id = user.email

    # Create new access token
    access_token = core.create_access_token(
        principal_id,
        extra_claims=extra_claims or None,
        auth_settings=auth_settings,
    )
    access_claims = core.verify_token(access_token, auth_settings)
    access_jti = access_claims['jti']

    # Create NEW refresh token (token rotation)
    new_refresh_token = core.create_refresh_token(
        principal_id,
        extra_claims=extra_claims or None,
        auth_settings=auth_settings,
    )
    new_refresh_claims = core.verify_token(new_refresh_token, auth_settings)
    new_refresh_jti = new_refresh_claims['jti']

    # Store new token metadata via Cypher (handles both
    # User and ServiceAccount via ISSUED_TO)
    now = datetime.datetime.now(datetime.UTC)

    if auth_method == 'client_credentials':
        # Link to ServiceAccount
        meta_query = """
        MATCH (s:ServiceAccount {slug: $subject})
        CREATE (at:TokenMetadata {
            jti: $access_jti,
            token_type: 'access',
            issued_at: datetime(),
            expires_at: datetime($access_exp),
            revoked: false
        })-[:ISSUED_TO]->(s)
        CREATE (rt:TokenMetadata {
            jti: $refresh_jti,
            token_type: 'refresh',
            issued_at: datetime(),
            expires_at: datetime($refresh_exp),
            revoked: false
        })-[:ISSUED_TO]->(s)
        """
    else:
        # Link to User
        meta_query = """
        MATCH (u:User {email: $subject})
        CREATE (at:TokenMetadata {
            jti: $access_jti,
            token_type: 'access',
            issued_at: datetime(),
            expires_at: datetime($access_exp),
            revoked: false
        })-[:ISSUED_TO]->(u)
        CREATE (rt:TokenMetadata {
            jti: $refresh_jti,
            token_type: 'refresh',
            issued_at: datetime(),
            expires_at: datetime($refresh_exp),
            revoked: false
        })-[:ISSUED_TO]->(u)
        """

    access_exp = (
        now
        + datetime.timedelta(seconds=auth_settings.access_token_expire_seconds)
    ).isoformat()
    refresh_exp = (
        now
        + datetime.timedelta(
            seconds=auth_settings.refresh_token_expire_seconds
        )
    ).isoformat()

    async with neo4j.run(
        meta_query,
        subject=subject,
        access_jti=access_jti,
        access_exp=access_exp,
        refresh_jti=new_refresh_jti,
        refresh_exp=refresh_exp,
    ) as result:
        await result.consume()

    LOGGER.info(
        'Token refreshed for %s (rotated refresh token)',
        principal_id,
    )

    return auth_models.TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,  # Phase 5: Return NEW token
        expires_in=auth_settings.access_token_expire_seconds,
    )


@auth_router.post('/logout', status_code=204)
async def logout(
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
    revoke_all_sessions: bool = fastapi.Query(default=False),
) -> None:
    """Logout and revoke current token and session (Phase 5).

    Args:
        auth: Current authenticated user context
        revoke_all_sessions: If True, revoke all user tokens and delete all
            sessions. If False, revoke only current token and associated
            refresh token.

    """
    # Revoke current access token
    query = """
    MATCH (t:TokenMetadata {jti: $jti})
    SET t.revoked = true, t.revoked_at = datetime()
    """
    async with neo4j.run(query, jti=auth.session_id) as result:
        await result.consume()

    if revoke_all_sessions:
        if auth.service_account:
            # Revoke all service account tokens
            query = """
            MATCH (s:ServiceAccount {slug: $slug})
                  <-[:ISSUED_TO]-(t:TokenMetadata)
            WHERE t.revoked = false
            SET t.revoked = true,
                t.revoked_at = datetime()
            """
            async with neo4j.run(
                query, slug=auth.service_account.slug
            ) as result:
                await result.consume()
        elif auth.user:
            # Revoke all user tokens
            query = """
            MATCH (u:User {email: $email})
                  <-[:ISSUED_TO]-(t:TokenMetadata)
            WHERE t.revoked = false
            SET t.revoked = true,
                t.revoked_at = datetime()
            """
            async with neo4j.run(query, email=auth.user.email) as result:
                await result.consume()

            # Delete all sessions
            query = """
            MATCH (u:User {email: $email})
                  <-[:SESSION_FOR]-(s:Session)
            DETACH DELETE s
            """
            async with neo4j.run(query, email=auth.user.email) as result:
                await result.consume()
    else:
        # Revoke only associated refresh token
        query = """
        MATCH (t:TokenMetadata {jti: $jti})
        RETURN t.issued_at as issued_at
        """
        async with neo4j.run(query, jti=auth.session_id) as result:
            records = await result.data()

        if records:
            issued_at = records[0]['issued_at']
            # Use generic ISSUED_TO traversal
            revoke_query = """
            MATCH (t:TokenMetadata {jti: $jti})
                  -[:ISSUED_TO]->(principal)
            MATCH (principal)
                  <-[:ISSUED_TO]-(rt:TokenMetadata)
            WHERE rt.token_type = 'refresh'
              AND rt.revoked = false
              AND abs(duration.inSeconds(
                  rt.issued_at, $issued_at
              ).seconds) < 5
            SET rt.revoked = true,
                rt.revoked_at = datetime()
            """
            async with neo4j.run(
                revoke_query,
                jti=auth.session_id,
                issued_at=issued_at,
            ) as result:
                await result.consume()

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
            status_code=400, detail=f'Invalid provider: {provider}'
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

    # Build authorization URL based on provider with proper URL encoding
    if provider == 'google':
        params = {
            'client_id': auth_settings.oauth_google_client_id or '',
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
            'client_id': auth_settings.oauth_github_client_id or '',
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
            'client_id': auth_settings.oauth_oidc_client_id or '',
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
    provider: str,
    code: str | None = fastapi.Query(default=None),
    state: str | None = fastapi.Query(default=None),
    error: str | None = fastapi.Query(default=None),
    error_description: str | None = fastapi.Query(default=None),
) -> fastapi.responses.RedirectResponse:
    """Handle OAuth provider callback.

    After user authorizes on OAuth provider, they're redirected here with
    an authorization code. We exchange it for tokens and create/login user.

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
            'OAuth callback error: %s - %s', error, error_description
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
            provider, token_response['access_token'], auth_settings
        )

        # Find or create OAuth identity
        oauth_identity = await find_or_create_oauth_identity(
            provider, profile, token_response, auth_settings
        )

        # Get associated user
        await neo4j.refresh_relationship(oauth_identity, 'user')
        user = oauth_identity.user

        if user.is_service_account:
            raise ValueError(
                'Service accounts cannot use OAuth authentication'
            )

        # Create JWT tokens (reusing existing token creation logic)
        access_token = core.create_access_token(
            user.email, auth_settings=auth_settings
        )
        access_claims = core.verify_token(access_token, auth_settings)
        access_jti = access_claims['jti']

        refresh_token = core.create_refresh_token(
            user.email, auth_settings=auth_settings
        )
        refresh_claims = core.verify_token(refresh_token, auth_settings)
        refresh_jti = refresh_claims['jti']

        # Store token metadata
        now = datetime.datetime.now(datetime.UTC)
        access_token_meta = models.TokenMetadata(
            jti=access_jti,
            token_type='access',
            issued_at=now,
            expires_at=now
            + datetime.timedelta(
                seconds=auth_settings.access_token_expire_seconds
            ),
            user=user,
        )
        await neo4j.create_node(access_token_meta)

        refresh_token_meta = models.TokenMetadata(
            jti=refresh_jti,
            token_type='refresh',
            issued_at=now,
            expires_at=now
            + datetime.timedelta(
                seconds=auth_settings.refresh_token_expire_seconds
            ),
            user=user,
        )
        await neo4j.create_node(refresh_token_meta)

        # Update user last_login
        user.last_login = now
        await neo4j.upsert(user, {'email': user.email})

        # Update OAuth identity last_used
        oauth_identity.last_used = now
        await neo4j.upsert(
            oauth_identity,
            {'provider': provider, 'provider_user_id': profile['id']},
        )

        LOGGER.info(
            'OAuth login successful for user %s via %s',
            user.email,
            provider,
        )

        # Redirect to frontend with tokens in URL fragment (not sent to server)
        # Using fragments prevents tokens from appearing in server logs,
        # browser history, or Referer headers
        redirect_url = (
            f'{state_data.redirect_uri}#'
            f'access_token={access_token}&'
            f'refresh_token={refresh_token}&'
            f'token_type=bearer&'
            f'expires_in={auth_settings.access_token_expire_seconds}'
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
    provider: str,
    profile: dict[str, typing.Any],
    token_response: dict[str, typing.Any],
    auth_settings: settings.Auth,
) -> models.OAuthIdentity:
    """Find existing or create new OAuth identity and user.

    Logic:
    1. Check if OAuth identity exists (by provider + provider_user_id)
    2. If exists, return it (with updated tokens)
    3. If not exists:
       a. Check if auto-link by email is enabled and user exists
       b. Otherwise create new user
       c. Create OAuth identity linked to user

    Args:
        provider: OAuth provider identifier
        profile: Normalized user profile from OAuth provider
        token_response: Token response from OAuth provider
        auth_settings: Auth settings instance

    Returns:
        OAuthIdentity with linked user

    Raises:
        ValueError: If user auto-creation disabled and no user found
        ValueError: If email domain not in allowed list (Google OAuth)

    """
    # Enforce domain restrictions for Google OAuth
    if provider == 'google' and auth_settings.oauth_google_allowed_domains:
        email_domain = profile['email'].split('@')[1].lower()
        allowed = [
            d.lower() for d in auth_settings.oauth_google_allowed_domains
        ]
        if email_domain not in allowed:
            raise ValueError(
                f'Email domain {email_domain} not in allowed domains: '
                f'{", ".join(auth_settings.oauth_google_allowed_domains)}'
            )

    # Try to find existing OAuth identity
    identity = await neo4j.fetch_node(
        models.OAuthIdentity,
        {'provider': provider, 'provider_user_id': profile['id']},
    )

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
        await neo4j.upsert(
            identity, {'provider': provider, 'provider_user_id': profile['id']}
        )

        return identity  # type: ignore[no-any-return]

    # OAuth identity doesn't exist - need to create it

    # Check if we should auto-link to existing user by email
    user = None
    if auth_settings.oauth_auto_link_by_email:
        user = await neo4j.fetch_node(models.User, {'email': profile['email']})

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

        await neo4j.create_node(user)
        LOGGER.info('Created new user %s via OAuth %s', user.email, provider)

    # Create OAuth identity (Phase 5: with encrypted tokens)
    now = datetime.datetime.now(datetime.UTC)
    identity = models.OAuthIdentity(
        provider=typing.cast(
            typing.Literal['google', 'github', 'oidc'], provider
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

    await neo4j.create_node(identity)
    await neo4j.create_relationship(identity, user, rel_type='OAUTH_IDENTITY')

    LOGGER.info(
        'Created OAuth identity for user %s via %s', user.email, provider
    )

    return identity
