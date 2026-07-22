"""Multi-Factor Authentication (MFA) endpoints using TOTP (Phase 5).

This module provides TOTP-based two-factor authentication with authenticator
apps like Google Authenticator, Authy, 1Password, etc. Includes backup codes
for account recovery.
"""

import asyncio
import base64
import datetime
import io
import logging
import secrets
import typing

import fastapi
import pydantic
import pyotp
import qrcode
from imbi_common import graph
from imbi_common.auth import encryption

from imbi_api import models, settings
from imbi_api.auth import password, permissions
from imbi_api.auth.totp import fetch_totp_secret, verify_totp_code
from imbi_api.middleware import rate_limit

LOGGER = logging.getLogger(__name__)

mfa_router = fastapi.APIRouter(prefix='/mfa', tags=['MFA'])


class MFASetupResponse(pydantic.BaseModel):
    """Response model for MFA setup (includes secret and QR code)."""

    secret: str = pydantic.Field(
        ..., description='Base32-encoded TOTP secret (store securely)'
    )
    provisioning_uri: str = pydantic.Field(
        ...,
        description=('TOTP provisioning URI for authenticator apps'),
    )
    backup_codes: list[str] = pydantic.Field(
        ...,
        description='One-time backup codes for account recovery',
    )
    qr_code: str = pydantic.Field(
        ..., description='Base64-encoded PNG QR code image'
    )


class MFAVerifyRequest(pydantic.BaseModel):
    """Request model for MFA code verification."""

    code: str = pydantic.Field(
        ...,
        description='6-digit TOTP code or backup code',
        min_length=6,
    )


class MFAStatusResponse(pydantic.BaseModel):
    """Response model for MFA status."""

    enabled: bool = pydantic.Field(..., description='Whether MFA is enabled')
    backup_codes_remaining: int = pydantic.Field(
        ..., description='Number of unused backup codes'
    )


@mfa_router.get('/status', response_model=MFAStatusResponse)
async def get_mfa_status(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.get_current_user),
    ],
) -> MFAStatusResponse:
    """Get MFA status for the authenticated user.

    Args:
        auth: Current authenticated user context

    Returns:
        MFA status including enabled flag and backup codes remaining

    """
    # Fetch TOTP secret from graph
    query: typing.LiteralString = """
    MATCH (u:User {{email: {email}}})
          <-[:MFA_FOR]-(t:TOTPSecret)
    RETURN t AS n
    """
    records = await db.execute(
        query,
        {'email': auth.require_user.email},
    )

    if not records:
        return MFAStatusResponse(enabled=False, backup_codes_remaining=0)

    totp_data = graph.parse_agtype(records[0]['n'])

    if not totp_data.get('enabled', False):
        return MFAStatusResponse(enabled=False, backup_codes_remaining=0)

    backup_codes = totp_data.get('backup_codes', [])
    return MFAStatusResponse(
        enabled=True,
        backup_codes_remaining=len(backup_codes),
    )


@mfa_router.post('/setup', response_model=MFASetupResponse)
async def setup_mfa(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.get_current_user),
    ],
) -> MFASetupResponse:
    """Setup MFA for the authenticated user (not enabled until
    verified).

    Generates a TOTP secret, QR code, and backup codes. MFA is not
    enabled until the user verifies a code using the /mfa/verify
    endpoint.

    Args:
        auth: Current authenticated user context

    Returns:
        MFA setup data including secret, QR code, and backup codes
        (shown only once)

    """
    auth_settings = settings.get_auth_settings()

    # Generate TOTP secret (base32-encoded)
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(
        secret,
        issuer=auth_settings.mfa_issuer_name,
        interval=auth_settings.mfa_totp_period,
        digits=auth_settings.mfa_totp_digits,
    )

    # Generate provisioning URI for authenticator apps
    provisioning_uri = totp.provisioning_uri(
        name=auth.require_user.email,
        issuer_name=auth_settings.mfa_issuer_name,
    )

    # Generate QR code image
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)

    img = qr.make_image(fill_color='black', back_color='white')
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')  # pyright: ignore[reportCallIssue]
    qr_code_base64 = base64.b64encode(buffer.getvalue()).decode('ascii')

    # Generate 10 backup codes (8-character hex strings)
    backup_codes = [secrets.token_hex(4) for _ in range(10)]
    hashed_backup_codes = await asyncio.gather(
        *(
            asyncio.to_thread(password.hash_password, code)
            for code in backup_codes
        )
    )

    # First, delete any existing TOTP secret
    delete_query: typing.LiteralString = """
    MATCH (u:User {{email: {email}}})
          <-[:MFA_FOR]-(t:TOTPSecret)
    DETACH DELETE t
    """
    await db.execute(
        delete_query,
        {'email': auth.require_user.email},
    )

    # Encrypt TOTP secret before storage
    encryptor = encryption.TokenEncryption.get_instance()
    totp_secret = models.TOTPSecret(
        secret='',  # Will be set via encryption helper
        enabled=False,  # Not enabled until verified
        backup_codes=hashed_backup_codes,
        created_at=datetime.datetime.now(datetime.UTC),
        last_used=None,
        user=auth.require_user,
    )
    totp_secret.set_encrypted_secret(secret, encryptor)

    await db.merge(totp_secret)
    # Relationship created automatically by merge via model
    # annotation

    LOGGER.info(
        'MFA setup initiated for user %s',
        auth.require_user.email,
    )

    return MFASetupResponse(
        secret=secret,
        provisioning_uri=provisioning_uri,
        backup_codes=backup_codes,  # Plaintext (shown once)
        qr_code=qr_code_base64,
    )


@mfa_router.post('/verify', status_code=204)
@rate_limit.limiter.limit('5/minute')  # type: ignore[untyped-decorator]
async def verify_and_enable_mfa(
    request: fastapi.Request,
    verify_request: MFAVerifyRequest,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.get_current_user),
    ],
) -> None:
    """Verify TOTP code and enable MFA for the authenticated user.

    This endpoint must be called after /mfa/setup to enable MFA.
    The user must provide a valid TOTP code from their authenticator
    app to prove they have successfully configured it.

    Args:
        verify_request: TOTP code to verify
        auth: Current authenticated user context

    Raises:
        HTTPException: 404 if MFA not setup, 401 if code is invalid

    """
    auth_settings = settings.get_auth_settings()

    totp_data = await fetch_totp_secret(db, auth.require_user.email)
    if totp_data is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail='MFA not setup for this user',
        )

    is_valid, matched_backup_hash = await verify_totp_code(
        totp_data,
        verify_request.code,
        period=auth_settings.mfa_totp_period,
        digits=auth_settings.mfa_totp_digits,
    )
    if not is_valid:
        raise fastapi.HTTPException(status_code=401, detail='Invalid MFA code')

    now_str = datetime.datetime.now(datetime.UTC).isoformat()

    # Enable MFA and atomically remove the used backup code. The
    # ``WHERE {used_hash} IN t.backup_codes`` + list-comprehension
    # filter is the race fix (H6): if a parallel verify already
    # consumed this code, the WHERE rejects this query so the SET
    # never fires and the hash can't be reused. We detect that case
    # via the empty result set and surface it as a 401, matching the
    # behavior the user would have seen if they'd raced themselves.
    if matched_backup_hash is not None:
        update_query: typing.LiteralString = """
        MATCH (u:User {{email: {email}}})
              <-[:MFA_FOR]-(t:TOTPSecret)
        WHERE {used_hash} IN t.backup_codes
        SET t.enabled = true,
            t.last_used = {now},
            t.backup_codes = [c IN t.backup_codes WHERE c <> {used_hash}]
        RETURN size(t.backup_codes) AS remaining
        """
        records = await db.execute(
            update_query,
            {
                'email': auth.require_user.email,
                'used_hash': matched_backup_hash,
                'now': now_str,
            },
            columns=['remaining'],
        )
        if not records:
            LOGGER.warning(
                'MFA backup code already consumed for user %s (race)',
                auth.require_user.email,
            )
            raise fastapi.HTTPException(
                status_code=401, detail='Invalid MFA code'
            )
        LOGGER.info(
            'MFA enabled for user %s (used backup code)',
            auth.require_user.email,
        )
    else:
        update_query2: typing.LiteralString = """
        MATCH (u:User {{email: {email}}})
              <-[:MFA_FOR]-(t:TOTPSecret)
        SET t.enabled = true, t.last_used = {now}
        """
        await db.execute(
            update_query2,
            {
                'email': auth.require_user.email,
                'now': now_str,
            },
        )
        LOGGER.info(
            'MFA enabled for user %s',
            auth.require_user.email,
        )


@mfa_router.delete('/disable', status_code=204)
async def disable_mfa(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.get_current_user),
    ],
    current_password: str | None = fastapi.Body(default=None, embed=True),
    mfa_code: str | None = fastapi.Body(default=None, embed=True),
) -> None:
    """Disable MFA for the authenticated user.

    Disabling MFA requires identity verification:
    - For password-based users: provide current_password
    - For OAuth-only users: provide mfa_code (TOTP or backup code)

    This permanently deletes the TOTP secret and backup codes.

    Args:
        auth: Current authenticated user context
        current_password: User's current password (for
            password-based users)
        mfa_code: MFA code (for OAuth-only users without password)

    Raises:
        HTTPException: 401 if verification fails or neither
            credential provided

    """
    # MFA must actually be enabled to disable it. Checked once, ahead of
    # both verification paths, so the password and OAuth-only flows agree
    # (and so the OAuth path can reuse this fetch).
    totp_data = await fetch_totp_secret(db, auth.require_user.email)
    if totp_data is None or not totp_data.get('enabled', False):
        raise fastapi.HTTPException(status_code=404, detail='MFA not enabled')

    # Verify identity based on account type
    if auth.require_user.password_hash:
        # Password-based user - require password
        if not current_password:
            raise fastapi.HTTPException(
                status_code=401,
                detail='Password required to disable MFA',
            )
        if not await asyncio.to_thread(
            password.verify_password,
            current_password,
            auth.require_user.password_hash,
        ):
            raise fastapi.HTTPException(
                status_code=401, detail='Invalid password'
            )
    else:
        # OAuth-only user - require MFA code as proof of identity
        if not mfa_code:
            raise fastapi.HTTPException(
                status_code=401,
                detail='MFA code required to disable MFA (OAuth-only account)',
            )

        auth_settings = settings.get_auth_settings()
        is_valid, _ = await verify_totp_code(
            totp_data,
            mfa_code,
            period=auth_settings.mfa_totp_period,
            digits=auth_settings.mfa_totp_digits,
        )
        if not is_valid:
            raise fastapi.HTTPException(
                status_code=401, detail='Invalid MFA code'
            )

    # Delete TOTP secret
    query: typing.LiteralString = """
    MATCH (u:User {{email: {email}}})
          <-[:MFA_FOR]-(t:TOTPSecret)
    DETACH DELETE t
    """
    await db.execute(
        query,
        {'email': auth.require_user.email},
    )

    LOGGER.info('MFA disabled for user %s', auth.require_user.email)
