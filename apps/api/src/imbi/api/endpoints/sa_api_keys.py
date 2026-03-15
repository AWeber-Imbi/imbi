"""Service account API key management endpoints (Phase 6).

This module provides CRUD operations for API keys scoped to service
accounts. It mirrors the user API key endpoints but associates keys
with a ServiceAccount node instead of a User node.
"""

import datetime
import logging
import secrets
import typing

import fastapi
from imbi_common import neo4j

from imbi_api import settings
from imbi_api.auth import password, permissions
from imbi_api.endpoints import api_keys

LOGGER = logging.getLogger(__name__)

sa_api_keys_router = fastapi.APIRouter(
    prefix='/service-accounts/{slug}/api-keys',
    tags=['Service Account API Keys'],
)


async def _get_service_account(slug: str) -> dict[str, typing.Any]:
    """Fetch and validate a service account exists by slug.

    Args:
        slug: Service account slug identifier

    Returns:
        Service account record data

    Raises:
        HTTPException: 404 if service account not found

    """
    query = """
    MATCH (s:ServiceAccount {slug: $slug})
    RETURN s
    """
    async with neo4j.run(query, slug=slug) as result:
        records = await result.data()

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail='Service account not found',
        )
    sa_data: dict[str, typing.Any] = records[0]['s']
    return sa_data


@sa_api_keys_router.post(
    '',
    response_model=api_keys.APIKeyCreateResponse,
    status_code=201,
)
async def create_sa_api_key(
    slug: str,
    key_request: api_keys.APIKeyCreate,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:update')
        ),
    ],
) -> api_keys.APIKeyCreateResponse:
    """Create a new API key for a service account.

    The API key secret is returned only once during creation. Store it
    securely as it cannot be retrieved later. The key format is:
    ik_<16chars>_<32chars>

    Args:
        slug: Service account slug identifier
        key_request: API key creation parameters
        auth: Current authenticated user context

    Returns:
        APIKeyCreateResponse with key_secret (shown only once)

    Raises:
        HTTPException: 404 if service account not found
        HTTPException: 400 if expiration exceeds maximum allowed

    """
    await _get_service_account(slug)

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
                f' lifetime of'
                f' {auth_settings.api_key_max_lifetime_days}'
                ' days',
            )
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
            days=key_request.expires_in_days
        )

    # Create API key node in Neo4j
    query = """
    MATCH (s:ServiceAccount {slug: $slug})
    CREATE (k:APIKey {
        key_id: $key_id,
        key_hash: $key_hash,
        name: $name,
        description: $description,
        scopes: $scopes,
        created_at: datetime(),
        expires_at: $expires_at,
        revoked: false
    })-[:OWNED_BY]->(s)
    RETURN k
    """
    async with neo4j.run(
        query,
        slug=slug,
        key_id=key_id,
        key_hash=key_hash,
        name=key_request.name,
        description=key_request.description,
        scopes=key_request.scopes,
        expires_at=expires_at,
    ) as result:
        await result.consume()

    LOGGER.info(
        'API key created for service account %s (expires: %s)',
        slug,
        expires_at or 'never',
    )

    return api_keys.APIKeyCreateResponse(
        key_id=key_id,
        key_secret=f'{key_id}_{key_secret}',
        name=key_request.name,
        description=key_request.description,
        scopes=key_request.scopes,
        expires_at=expires_at,
    )


@sa_api_keys_router.get(
    '',
    response_model=list[api_keys.APIKeyResponse],
)
async def list_sa_api_keys(
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:read')
        ),
    ],
) -> list[api_keys.APIKeyResponse]:
    """List all API keys for a service account.

    Returns metadata for all API keys (active and revoked). Key
    secrets are not included in the response.

    Args:
        slug: Service account slug identifier
        auth: Current authenticated user context

    Returns:
        List of API key metadata

    """
    query = """
    MATCH (s:ServiceAccount {slug: $slug})
          <-[:OWNED_BY]-(k:APIKey)
    RETURN k ORDER BY k.created_at DESC
    """
    async with neo4j.run(query, slug=slug) as result:
        records = await result.data()

    keys = [
        api_keys.APIKeyResponse(**neo4j.convert_neo4j_types(record['k']))
        for record in records
    ]

    LOGGER.debug(
        'Listed %d API keys for service account %s',
        len(keys),
        slug,
    )

    return keys


@sa_api_keys_router.delete('/{key_id}', status_code=204)
async def revoke_sa_api_key(
    slug: str,
    key_id: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:update')
        ),
    ],
) -> None:
    """Revoke an API key for a service account (soft delete).

    Revoked keys can no longer be used for authentication but remain
    in the database for audit purposes.

    Args:
        slug: Service account slug identifier
        key_id: API key identifier to revoke
        auth: Current authenticated user context

    Raises:
        HTTPException: 404 if key not found or not owned by the
            service account

    """
    # Verify ownership and revoke atomically
    query = """
    MATCH (s:ServiceAccount {slug: $slug})
          <-[:OWNED_BY]-(k:APIKey {key_id: $key_id})
    SET k.revoked = true, k.revoked_at = datetime()
    RETURN k
    """
    async with neo4j.run(query, slug=slug, key_id=key_id) as result:
        records = await result.data()

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail='API key not found or not owned by this service account',
        )

    LOGGER.info(
        'API key %s revoked for service account %s by %s',
        key_id,
        slug,
        auth.principal_name,
    )


@sa_api_keys_router.post(
    '/{key_id}/rotate',
    response_model=api_keys.APIKeyCreateResponse,
)
async def rotate_sa_api_key(
    slug: str,
    key_id: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:update')
        ),
    ],
) -> api_keys.APIKeyCreateResponse:
    """Rotate an API key secret for a service account.

    Generates a new secret while keeping the same key_id and metadata.
    The old secret is immediately invalidated and the new secret is
    returned (shown only once).

    Args:
        slug: Service account slug identifier
        key_id: API key identifier to rotate
        auth: Current authenticated user context

    Returns:
        APIKeyCreateResponse with new key_secret (shown only once)

    Raises:
        HTTPException: 404 if key not found or not owned by the
            service account
        HTTPException: 400 if key is already revoked

    """
    # Verify ownership and fetch key
    query = """
    MATCH (s:ServiceAccount {slug: $slug})
          <-[:OWNED_BY]-(k:APIKey {key_id: $key_id})
    RETURN k
    """
    async with neo4j.run(query, slug=slug, key_id=key_id) as result:
        records = await result.data()

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail='API key not found or not owned by this service account',
        )

    api_key_data = records[0]['k']

    if api_key_data.get('revoked', False):
        raise fastapi.HTTPException(
            status_code=400,
            detail='Cannot rotate revoked API key',
        )

    # Generate new secret and update atomically with ownership check
    new_secret = secrets.token_urlsafe(32)
    new_key_hash = password.hash_password(new_secret)

    query = """
    MATCH (s:ServiceAccount {slug: $slug})
          <-[:OWNED_BY]-(k:APIKey {key_id: $key_id})
    WHERE k.revoked = false
    SET k.key_hash = $key_hash, k.last_rotated = datetime()
    RETURN k
    """
    async with neo4j.run(
        query, slug=slug, key_id=key_id, key_hash=new_key_hash
    ) as result:
        await result.consume()

    LOGGER.info(
        'API key %s rotated for service account %s by %s',
        key_id,
        slug,
        auth.principal_name,
    )

    return api_keys.APIKeyCreateResponse(
        key_id=key_id,
        key_secret=f'{key_id}_{new_secret}',
        name=api_key_data['name'],
        description=api_key_data.get('description'),
        scopes=api_key_data.get('scopes', []),
        expires_at=api_key_data.get('expires_at'),
    )
