"""Multi-Factor Authentication (MFA) endpoints using TOTP (Phase 5).

This module provides TOTP-based two-factor authentication with authenticator
apps like Google Authenticator, Authy, 1Password, etc. Includes backup codes
for account recovery.
"""

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

from imbi import models, neo4j, settings
from imbi.auth import core, permissions
from imbi.auth.encryption import TokenEncryption

LOGGER = logging.getLogger(__name__)

mfa_router = fastapi.APIRouter(prefix='/mfa', tags=['MFA'])


class MFASetupResponse(pydantic.BaseModel):
    """Response model for MFA setup (includes secret and QR code)."""

    secret: str = pydantic.Field(
        ..., description='Base32-encoded TOTP secret (store securely)'
    )
    provisioning_uri: str = pydantic.Field(
        ..., description='TOTP provisioning URI for authenticator apps'
    )
    backup_codes: list[str] = pydantic.Field(
        ..., description='One-time backup codes for account recovery'
    )
    qr_code: str = pydantic.Field(
        ..., description='Base64-encoded PNG QR code image'
    )


class MFAVerifyRequest(pydantic.BaseModel):
    """Request model for MFA code verification."""

    code: str = pydantic.Field(
        ..., description='6-digit TOTP code or backup code', min_length=6
    )


class MFAStatusResponse(pydantic.BaseModel):
    """Response model for MFA status."""

    enabled: bool = pydantic.Field(..., description='Whether MFA is enabled')
    backup_codes_remaining: int = pydantic.Field(
        ..., description='Number of unused backup codes'
    )


@mfa_router.get('/status', response_model=MFAStatusResponse)
async def get_mfa_status(
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
) -> MFAStatusResponse:
    """Get MFA status for the authenticated user.

    Args:
        auth: Current authenticated user context

    Returns:
        MFA status including enabled flag and backup codes remaining

    """
    # Fetch TOTP secret from Neo4j
    query = """
    MATCH (u:User {username: $username})<-[:MFA_FOR]-(t:TOTPSecret)
    RETURN t
    """
    async with neo4j.run(query, username=auth.user.username) as result:
        records = await result.data()

    if not records:
        return MFAStatusResponse(enabled=False, backup_codes_remaining=0)

    totp_data = records[0]['t']

    if not totp_data.get('enabled', False):
        return MFAStatusResponse(enabled=False, backup_codes_remaining=0)

    backup_codes = totp_data.get('backup_codes', [])
    return MFAStatusResponse(
        enabled=True, backup_codes_remaining=len(backup_codes)
    )


@mfa_router.post('/setup', response_model=MFASetupResponse)
async def setup_mfa(
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
) -> MFASetupResponse:
    """Setup MFA for the authenticated user (not enabled until verified).

    Generates a TOTP secret, QR code, and backup codes. MFA is not enabled
    until the user verifies a code using the /mfa/verify endpoint.

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
        name=auth.user.email or auth.user.username,
        issuer_name=auth_settings.mfa_issuer_name,
    )

    # Generate QR code image
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)

    img = qr.make_image(fill_color='black', back_color='white')
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    qr_code_base64 = base64.b64encode(buffer.getvalue()).decode('ascii')

    # Generate 10 backup codes (8-character hex strings)
    backup_codes = [secrets.token_hex(4) for _ in range(10)]
    hashed_backup_codes = [core.hash_password(code) for code in backup_codes]

    # Store TOTP secret in Neo4j (encrypted, not enabled yet)
    # First, delete any existing TOTP secret
    delete_query = """
    MATCH (u:User {username: $username})<-[:MFA_FOR]-(t:TOTPSecret)
    DETACH DELETE t
    """
    async with neo4j.run(delete_query, username=auth.user.username) as result:
        await result.consume()

    # Encrypt TOTP secret before storage
    encryptor = TokenEncryption.get_instance()
    totp_secret = models.TOTPSecret(
        secret='',  # Will be set via encryption helper
        enabled=False,  # Not enabled until verified
        backup_codes=hashed_backup_codes,
        created_at=datetime.datetime.now(datetime.UTC),
        last_used=None,
        user=auth.user,
    )
    totp_secret.set_encrypted_secret(secret, encryptor)

    await neo4j.create_node(totp_secret)
    # Relationship created automatically by create_node via model annotation

    LOGGER.info('MFA setup initiated for user %s', auth.user.username)

    return MFASetupResponse(
        secret=secret,
        provisioning_uri=provisioning_uri,
        backup_codes=backup_codes,  # Plaintext codes (shown only once)
        qr_code=qr_code_base64,
    )


@mfa_router.post('/verify', status_code=204)
async def verify_and_enable_mfa(
    verify_request: MFAVerifyRequest,
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
) -> None:
    """Verify TOTP code and enable MFA for the authenticated user.

    This endpoint must be called after /mfa/setup to enable MFA. The user
    must provide a valid TOTP code from their authenticator app to prove
    they have successfully configured it.

    Args:
        verify_request: TOTP code to verify
        auth: Current authenticated user context

    Raises:
        HTTPException: 404 if MFA not setup, 401 if code is invalid

    """
    auth_settings = settings.get_auth_settings()

    # Fetch TOTP secret from Neo4j
    query = """
    MATCH (u:User {username: $username})<-[:MFA_FOR]-(t:TOTPSecret)
    RETURN t
    """
    async with neo4j.run(query, username=auth.user.username) as result:
        records = await result.data()

    if not records:
        raise fastapi.HTTPException(
            status_code=404, detail='MFA not setup for this user'
        )

    totp_data = records[0]['t']
    encrypted_secret = totp_data['secret']

    # Decrypt TOTP secret
    encryptor = TokenEncryption.get_instance()
    try:
        secret = encryptor.decrypt(encrypted_secret)
        if secret is None:
            raise ValueError('Decryption returned None')
    except (ValueError, TypeError) as err:
        LOGGER.error('Failed to decrypt TOTP secret: %s', err)
        raise fastapi.HTTPException(
            status_code=500, detail='Failed to decrypt MFA secret'
        ) from err

    # Verify TOTP code or backup code
    totp = pyotp.TOTP(
        secret,
        interval=auth_settings.mfa_totp_period,
        digits=auth_settings.mfa_totp_digits,
    )

    is_valid = False
    used_backup_code = False

    # First try TOTP verification (allow 1 time step before/after for skew)
    if totp.verify(verify_request.code, valid_window=1):
        is_valid = True
    else:
        # Try backup codes
        backup_codes = totp_data.get('backup_codes', [])
        for backup_hash in backup_codes:
            if core.verify_password(verify_request.code, backup_hash):
                is_valid = True
                used_backup_code = True
                # Remove used backup code
                backup_codes.remove(backup_hash)
                break

    if not is_valid:
        raise fastapi.HTTPException(status_code=401, detail='Invalid MFA code')

    # Enable MFA and update backup codes if one was used
    if used_backup_code:
        update_query = """
        MATCH (u:User {username: $username})<-[:MFA_FOR]-(t:TOTPSecret)
        SET t.enabled = true,
            t.last_used = datetime(),
            t.backup_codes = $backup_codes
        """
        async with neo4j.run(
            update_query,
            username=auth.user.username,
            backup_codes=backup_codes,
        ) as result:
            await result.consume()
        LOGGER.info(
            'MFA enabled for user %s (used backup code)', auth.user.username
        )
    else:
        update_query = """
        MATCH (u:User {username: $username})<-[:MFA_FOR]-(t:TOTPSecret)
        SET t.enabled = true, t.last_used = datetime()
        """
        async with neo4j.run(
            update_query, username=auth.user.username
        ) as result:
            await result.consume()
        LOGGER.info('MFA enabled for user %s', auth.user.username)


@mfa_router.delete('/disable', status_code=204)
async def disable_mfa(
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
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
        current_password: User's current password (for password-based users)
        mfa_code: MFA code (for OAuth-only users without password)

    Raises:
        HTTPException: 401 if verification fails or neither credential provided

    """
    auth_settings = settings.get_auth_settings()

    # Verify identity based on account type
    if auth.user.password_hash:
        # Password-based user - require password
        if not current_password:
            raise fastapi.HTTPException(
                status_code=401,
                detail='Password required to disable MFA',
            )
        if not core.verify_password(current_password, auth.user.password_hash):
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

        # Fetch and verify MFA code
        totp_query = """
        MATCH (u:User {username: $username})<-[:MFA_FOR]-(t:TOTPSecret)
        RETURN t
        """
        async with neo4j.run(
            totp_query, username=auth.user.username
        ) as result:
            totp_records = await result.data()

        if not totp_records:
            raise fastapi.HTTPException(
                status_code=404, detail='MFA not enabled'
            )

        totp_data = totp_records[0]['t']

        # Decrypt TOTP secret
        encryptor = TokenEncryption.get_instance()
        try:
            secret = encryptor.decrypt(totp_data['secret'])
            if secret is None:
                raise ValueError('Decryption returned None')
        except (ValueError, TypeError) as err:
            LOGGER.error('Failed to decrypt TOTP secret: %s', err)
            raise fastapi.HTTPException(
                status_code=500, detail='Failed to decrypt MFA secret'
            ) from err

        # Verify MFA code
        totp = pyotp.TOTP(
            secret,
            interval=auth_settings.mfa_totp_period,
            digits=auth_settings.mfa_totp_digits,
        )

        is_valid = False

        # Try TOTP first
        if totp.verify(mfa_code, valid_window=1):
            is_valid = True
        else:
            # Try backup codes
            backup_codes = totp_data.get('backup_codes', [])
            for backup_hash in backup_codes:
                if core.verify_password(mfa_code, backup_hash):
                    is_valid = True
                    break

        if not is_valid:
            raise fastapi.HTTPException(
                status_code=401, detail='Invalid MFA code'
            )

    # Delete TOTP secret
    query = """
    MATCH (u:User {username: $username})<-[:MFA_FOR]-(t:TOTPSecret)
    DETACH DELETE t
    """
    async with neo4j.run(query, username=auth.user.username) as result:
        await result.consume()

    LOGGER.info('MFA disabled for user %s', auth.user.username)
