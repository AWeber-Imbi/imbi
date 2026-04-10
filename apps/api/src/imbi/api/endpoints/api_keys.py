"""API key management endpoints (Phase 5).

This module provides CRUD operations for API keys that enable programmatic
access to the API. API keys support scoped permissions, expiration, rotation,
and usage tracking via ClickHouse.
"""

import datetime
import logging
import secrets
import typing

import fastapi
import pydantic
from imbi_common import graph

from imbi_api import models, settings
from imbi_api.auth import password, permissions

LOGGER = logging.getLogger(__name__)

api_keys_router = fastapi.APIRouter(prefix='/api-keys', tags=['API Keys'])


class APIKeyCreate(pydantic.BaseModel):
    """Request model for creating an API key."""

    name: str = pydantic.Field(
        ...,
        description='Human-readable name for the API key',
        min_length=1,
    )
    description: str | None = pydantic.Field(
        default=None,
        description='Optional description of key purpose',
    )
    scopes: list[str] = pydantic.Field(
        default_factory=list,
        description=('Permission scopes (empty list = all permissions)'),
    )
    expires_in_days: int | None = pydantic.Field(
        default=None,
        description='Days until expiration (None = never expires)',
        ge=1,
    )


class APIKeyResponse(pydantic.BaseModel):
    """Response model for API key metadata (without secret)."""

    key_id: str = pydantic.Field(..., description='API key identifier')
    name: str = pydantic.Field(..., description='Human-readable name')
    description: str | None = pydantic.Field(
        default=None, description='Optional description'
    )
    scopes: list[str] = pydantic.Field(
        default_factory=list, description='Permission scopes'
    )
    created_at: datetime.datetime = pydantic.Field(
        ..., description='Creation timestamp'
    )
    expires_at: datetime.datetime | None = pydantic.Field(
        default=None, description='Expiration timestamp'
    )
    last_used: datetime.datetime | None = pydantic.Field(
        default=None, description='Last usage timestamp'
    )
    last_rotated: datetime.datetime | None = pydantic.Field(
        default=None, description='Last rotation timestamp'
    )
    revoked: bool = pydantic.Field(..., description='Revocation status')


class APIKeyCreateResponse(pydantic.BaseModel):
    """Response model for API key creation (includes secret,
    shown once)."""

    key_id: str = pydantic.Field(..., description='API key identifier')
    key_secret: str = pydantic.Field(
        ...,
        description='Full API key secret (shown only once)',
    )
    name: str = pydantic.Field(..., description='Human-readable name')
    description: str | None = pydantic.Field(
        default=None, description='Optional description'
    )
    scopes: list[str] = pydantic.Field(
        default_factory=list, description='Permission scopes'
    )
    expires_at: datetime.datetime | None = pydantic.Field(
        default=None, description='Expiration timestamp'
    )


_parse_scopes = models.parse_scopes


@api_keys_router.post('', response_model=APIKeyCreateResponse, status_code=201)
async def create_api_key(
    key_request: APIKeyCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.get_current_user),
    ],
) -> APIKeyCreateResponse:
    """Create a new API key for the authenticated user.

    The API key secret is returned only once during creation.
    Store it securely as it cannot be retrieved later. The key
    format is: ik_<16chars>_<32chars>

    Args:
        key_request: API key creation parameters
        auth: Current authenticated user context

    Returns:
        APIKeyCreateResponse with key_secret (shown only once)

    Raises:
        HTTPException: 400 if expiration exceeds maximum allowed

    """
    auth_settings = settings.get_auth_settings()

    # Generate key: format ik_<16chars>_<32chars>
    key_id = f'ik_{secrets.token_hex(16)}'
    key_secret = secrets.token_urlsafe(32)
    key_hash = password.hash_password(key_secret)

    # Validate expiration
    expires_at = None
    if key_request.expires_in_days:
        if (
            key_request.expires_in_days
            > auth_settings.api_key_max_lifetime_days
        ):
            raise fastapi.HTTPException(
                status_code=400,
                detail='Expiration exceeds maximum allowed'
                ' lifetime of'
                f' {auth_settings.api_key_max_lifetime_days}'
                ' days',
            )
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
            days=key_request.expires_in_days
        )

    # Create API key model
    api_key = models.APIKey(
        key_id=key_id,
        key_hash=key_hash,
        name=key_request.name,
        description=key_request.description,
        scopes=key_request.scopes,
        created_at=datetime.datetime.now(datetime.UTC),
        expires_at=expires_at,
        last_used=None,
        last_rotated=None,
        revoked=False,
        revoked_at=None,
        user=auth.require_user,
    )

    # Store in graph and create relationship
    await db.merge(api_key)

    rel_query: typing.LiteralString = """
    MATCH (k:APIKey {{key_id: {key_id}}})
    MATCH (u:User {{email: {email}}})
    MERGE (k)-[:OWNED_BY]->(u)
    """
    await db.execute(
        rel_query,
        {
            'key_id': key_id,
            'email': auth.require_user.email,
        },
    )

    LOGGER.info(
        'API key %s created for user %s (expires: %s)',
        key_id,
        auth.require_user.email,
        expires_at or 'never',
    )

    return APIKeyCreateResponse(
        key_id=key_id,
        key_secret=f'{key_id}_{key_secret}',  # Full key format
        name=key_request.name,
        description=key_request.description,
        scopes=key_request.scopes,
        expires_at=expires_at,
    )


@api_keys_router.get('', response_model=list[APIKeyResponse])
async def list_api_keys(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.get_current_user),
    ],
) -> list[APIKeyResponse]:
    """List all API keys for the authenticated user.

    Returns metadata for all API keys (active and revoked). The
    key secrets are not included in the response.

    Args:
        auth: Current authenticated user context

    Returns:
        List of API key metadata

    """
    query: typing.LiteralString = """
    MATCH (u:User {{email: {email}}})
          <-[:OWNED_BY]-(k:APIKey)
    RETURN k ORDER BY k.created_at DESC
    """
    records = await db.execute(
        query,
        {'email': auth.require_user.email},
        ['k'],
    )

    api_keys = [
        APIKeyResponse(
            key_id=k['key_id'],
            name=k['name'],
            description=k.get('description'),
            scopes=_parse_scopes(k.get('scopes', [])),
            created_at=k['created_at'],
            expires_at=k.get('expires_at'),
            last_used=k.get('last_used'),
            last_rotated=k.get('last_rotated'),
            revoked=k.get('revoked', False),
        )
        for record in records
        for k in [graph.parse_agtype(record['k'])]
    ]

    LOGGER.debug(
        'Listed %d API keys for user %s',
        len(api_keys),
        auth.require_user.email,
    )

    return api_keys


@api_keys_router.delete('/{key_id}', status_code=204)
async def revoke_api_key(
    key_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.get_current_user),
    ],
) -> None:
    """Revoke an API key (soft delete).

    Revoked keys can no longer be used for authentication but
    remain in the database for audit purposes.

    Args:
        key_id: API key identifier to revoke
        auth: Current authenticated user context

    Raises:
        HTTPException: 404 if key not found or not owned by user

    """
    # Verify ownership
    query: typing.LiteralString = """
    MATCH (u:User {{email: {email}}})
          <-[:OWNED_BY]-(k:APIKey {{key_id: {key_id}}})
    RETURN k
    """
    records = await db.execute(
        query,
        {
            'email': auth.require_user.email,
            'key_id': key_id,
        },
        ['k'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail='API key not found or not owned by user',
        )

    # Revoke key
    now_str = datetime.datetime.now(datetime.UTC).isoformat()
    revoke_query: typing.LiteralString = """
    MATCH (k:APIKey {{key_id: {key_id}}})
    SET k.revoked = true, k.revoked_at = {now}
    """
    await db.execute(
        revoke_query,
        {'key_id': key_id, 'now': now_str},
    )

    LOGGER.info(
        'API key %s revoked by user %s',
        key_id,
        auth.require_user.email,
    )


@api_keys_router.post('/{key_id}/rotate', response_model=APIKeyCreateResponse)
async def rotate_api_key(
    key_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.get_current_user),
    ],
) -> APIKeyCreateResponse:
    """Rotate an API key secret (keep same key_id, generate new
    secret).

    This allows updating the key secret without changing the
    key_id or other metadata. The old secret is immediately
    invalidated and the new secret is returned (shown only once).

    Args:
        key_id: API key identifier to rotate
        auth: Current authenticated user context

    Returns:
        APIKeyCreateResponse with new key_secret (shown only once)

    Raises:
        HTTPException: 404 if key not found or not owned by user
        HTTPException: 400 if key is already revoked

    """
    # Verify ownership and fetch key
    query: typing.LiteralString = """
    MATCH (u:User {{email: {email}}})
          <-[:OWNED_BY]-(k:APIKey {{key_id: {key_id}}})
    RETURN k
    """
    records = await db.execute(
        query,
        {
            'email': auth.require_user.email,
            'key_id': key_id,
        },
        ['k'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail='API key not found or not owned by user',
        )

    api_key_data = graph.parse_agtype(records[0]['k'])

    if api_key_data.get('revoked', False):
        raise fastapi.HTTPException(
            status_code=400,
            detail='Cannot rotate revoked API key',
        )

    # Generate new secret
    new_secret = secrets.token_urlsafe(32)
    new_key_hash = password.hash_password(new_secret)
    now_str = datetime.datetime.now(datetime.UTC).isoformat()

    # Update key in graph
    update_query: typing.LiteralString = """
    MATCH (k:APIKey {{key_id: {key_id}}})
    SET k.key_hash = {key_hash}, k.last_rotated = {now}
    RETURN k
    """
    await db.execute(
        update_query,
        {
            'key_id': key_id,
            'key_hash': new_key_hash,
            'now': now_str,
        },
        ['k'],
    )

    LOGGER.info(
        'API key %s rotated by user %s',
        key_id,
        auth.require_user.email,
    )

    return APIKeyCreateResponse(
        key_id=key_id,
        key_secret=f'{key_id}_{new_secret}',  # Full key format
        name=api_key_data['name'],
        description=api_key_data.get('description'),
        scopes=_parse_scopes(api_key_data.get('scopes', [])),
        expires_at=api_key_data.get('expires_at'),
    )
