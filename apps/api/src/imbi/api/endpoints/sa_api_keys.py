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

from imbi.api import models, settings
from imbi.api.auth import permissions
from imbi.api.endpoints import api_keys
from imbi.api.endpoints._credentials import (
    compute_expires_at,
    create_service_account_owned_node,
    generate_secret,
)
from imbi.common import graph

LOGGER = logging.getLogger(__name__)

sa_api_keys_router = fastapi.APIRouter(
    prefix='/service-accounts/{slug}/api-keys',
    tags=['Service Account API Keys'],
)


async def _get_service_account(
    db: graph.Graph,
    slug: str,
) -> dict[str, typing.Any]:
    """Fetch and validate a service account exists by slug.

    Args:
        db: Graph database instance
        slug: Service account slug identifier

    Returns:
        Service account record data

    Raises:
        HTTPException: 404 if service account not found

    """
    query: typing.LiteralString = """
    MATCH (s:ServiceAccount {{slug: {slug}}})
    RETURN s
    """
    records = await db.execute(
        query,
        {'slug': slug},
        ['s'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail='Service account not found',
        )
    sa_data: dict[str, typing.Any] = graph.parse_agtype(records[0]['s'])
    return sa_data


@sa_api_keys_router.post(
    '',
    response_model=api_keys.APIKeyCreateResponse,
    status_code=201,
)
async def create_sa_api_key(
    slug: str,
    key_request: api_keys.APIKeyCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:update')
        ),
    ],
) -> api_keys.APIKeyCreateResponse:
    """Create a new API key for a service account.

    The API key secret is returned only once during creation.
    Store it securely as it cannot be retrieved later. The key
    format is: ik_<16chars>_<32chars>

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
    await _get_service_account(db, slug)

    auth_settings = settings.get_auth_settings()

    # L27: reject bogus scopes at write time so audit logs and the
    # SA key UI never show typos that silently grant nothing.
    await permissions.validate_scopes(db, key_request.scopes)

    # Generate key: format ik_<16chars>_<32chars>
    key_id = f'ik_{secrets.token_hex(16)}'
    key_secret, key_hash = await generate_secret()

    expires_at = compute_expires_at(
        key_request.expires_in_days,
        auth_settings.api_key_max_lifetime_days,
    )

    # Create API key model
    api_key = models.APIKey(
        key_id=key_id,
        key_hash=key_hash,
        name=key_request.name,
        description=key_request.description,
        scopes=key_request.scopes,
        expires_at=expires_at,
        revoked=False,
    )

    # Create API key node with relationship to ServiceAccount.
    # scopes stays as a list — _cypher_param handles list
    # serialization for Cypher.
    props = api_key.model_dump(mode='json')
    props.pop('user', None)
    created = await create_service_account_owned_node(
        db, label='APIKey', props=props, slug=slug
    )
    if not created:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Service account {slug!r} not found',
        )

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
    db: graph.Pool,
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
    query: typing.LiteralString = """
    MATCH (s:ServiceAccount {{slug: {slug}}})
          <-[:OWNED_BY]-(k:APIKey)
    RETURN k ORDER BY k.created_at DESC
    """
    records = await db.execute(
        query,
        {'slug': slug},
        ['k'],
    )

    keys: list[api_keys.APIKeyResponse] = []
    for record in records:
        data = graph.parse_agtype(record['k'])
        data['scopes'] = models.parse_scopes(
            data.get('scopes', []),
        )
        keys.append(api_keys.APIKeyResponse(**data))

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
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:update')
        ),
    ],
) -> None:
    """Revoke an API key for a service account (soft delete).

    Revoked keys can no longer be used for authentication but
    remain in the database for audit purposes.

    Args:
        slug: Service account slug identifier
        key_id: API key identifier to revoke
        auth: Current authenticated user context

    Raises:
        HTTPException: 404 if key not found or not owned by the
            service account

    """
    now_str = datetime.datetime.now(datetime.UTC).isoformat()
    # Verify ownership and revoke atomically
    query: typing.LiteralString = """
    MATCH (s:ServiceAccount {{slug: {slug}}})
          <-[:OWNED_BY]-(k:APIKey {{key_id: {key_id}}})
    SET k.revoked = true, k.revoked_at = {now}
    RETURN k
    """
    records = await db.execute(
        query,
        {'slug': slug, 'key_id': key_id, 'now': now_str},
        ['k'],
    )

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
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:update')
        ),
    ],
) -> api_keys.APIKeyCreateResponse:
    """Rotate an API key secret for a service account.

    Generates a new secret while keeping the same key_id and
    metadata. The old secret is immediately invalidated and the
    new secret is returned (shown only once).

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
    query: typing.LiteralString = """
    MATCH (s:ServiceAccount {{slug: {slug}}})
          <-[:OWNED_BY]-(k:APIKey {{key_id: {key_id}}})
    RETURN k
    """
    records = await db.execute(
        query,
        {'slug': slug, 'key_id': key_id},
        ['k'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail='API key not found or not owned by this service account',
        )

    api_key_data = graph.parse_agtype(records[0]['k'])

    if api_key_data.get('revoked', False):
        raise fastapi.HTTPException(
            status_code=400,
            detail='Cannot rotate revoked API key',
        )

    # Generate new secret and update atomically
    new_secret, new_key_hash = await generate_secret()
    now_str = datetime.datetime.now(datetime.UTC).isoformat()

    update_query: typing.LiteralString = """
    MATCH (s:ServiceAccount {{slug: {slug}}})
          <-[:OWNED_BY]-(k:APIKey {{key_id: {key_id}}})
    WHERE k.revoked = false
    SET k.key_hash = {key_hash}, k.last_rotated = {now}
    RETURN k
    """
    updated = await db.execute(
        update_query,
        {
            'slug': slug,
            'key_id': key_id,
            'key_hash': new_key_hash,
            'now': now_str,
        },
        ['k'],
    )
    if not updated:
        raise fastapi.HTTPException(
            status_code=409,
            detail='API key was modified during rotation',
        )

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
        scopes=models.parse_scopes(
            api_key_data.get('scopes', []),
        ),
        expires_at=api_key_data.get('expires_at'),
    )
