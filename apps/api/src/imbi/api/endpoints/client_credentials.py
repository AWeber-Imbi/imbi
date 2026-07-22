"""Client credentials CRUD endpoints (Phase 4).

This module provides CRUD operations for OAuth2 client credentials
that enable service accounts to authenticate using the client
credentials grant flow.
"""

import datetime
import logging
import secrets
import typing

import fastapi

from imbi.api import models, settings
from imbi.api.auth import permissions
from imbi.api.endpoints._credentials import (
    compute_expires_at,
    create_service_account_owned_node,
    generate_secret,
)
from imbi.common import graph

LOGGER = logging.getLogger(__name__)

client_credentials_router = fastapi.APIRouter(
    prefix='/service-accounts/{slug}/client-credentials',
    tags=['Client Credentials'],
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


@client_credentials_router.post(
    '',
    response_model=models.ClientCredentialCreateResponse,
    status_code=201,
)
async def create_client_credential(
    slug: str,
    credential_request: models.ClientCredentialCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:update')
        ),
    ],
) -> models.ClientCredentialCreateResponse:
    """Create a new client credential for a service account.

    The client secret is returned only once during creation. Store it
    securely as it cannot be retrieved later.

    Args:
        slug: Service account slug identifier
        credential_request: Client credential creation parameters
        auth: Current authenticated user context

    Returns:
        ClientCredentialCreateResponse with client_secret
        (shown once)

    Raises:
        HTTPException: 404 if service account not found
        HTTPException: 400 if expiration exceeds maximum allowed

    """
    await _get_service_account(db, slug)

    auth_settings = settings.get_auth_settings()

    # L27: reject bogus scopes at write time so audit logs and the
    # client-credentials UI never show typos that silently grant nothing.
    await permissions.validate_scopes(db, credential_request.scopes)

    # Generate client_id and secret
    client_id = f'cc_{secrets.token_urlsafe(16)}'
    client_secret, secret_hash = await generate_secret()

    expires_at = compute_expires_at(
        credential_request.expires_in_days,
        auth_settings.api_key_max_lifetime_days,
    )

    # Create ClientCredential model
    credential = models.ClientCredential(
        client_id=client_id,
        client_secret_hash=secret_hash,
        name=credential_request.name,
        description=credential_request.description,
        scopes=credential_request.scopes,
        expires_at=expires_at,
        last_used=None,
        last_rotated=None,
        revoked=False,
        revoked_at=None,
    )

    # Store in graph with relationship to ServiceAccount.
    # scopes stays as a list — _cypher_param handles list
    # serialization for Cypher.
    props = credential.model_dump(mode='json')
    props.pop('service_account', None)
    created = await create_service_account_owned_node(
        db, label='ClientCredential', props=props, slug=slug
    )
    if not created:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Service account {slug!r} not found',
        )

    LOGGER.info(
        'Client credential %s created for service account %s (expires: %s)',
        client_id,
        slug,
        expires_at or 'never',
    )

    return models.ClientCredentialCreateResponse(
        client_id=client_id,
        client_secret=client_secret,
        name=credential_request.name,
        description=credential_request.description,
        scopes=credential_request.scopes,
        expires_at=expires_at,
    )


@client_credentials_router.get(
    '',
    response_model=list[models.ClientCredentialResponse],
)
async def list_client_credentials(
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:read')
        ),
    ],
) -> list[models.ClientCredentialResponse]:
    """List all client credentials for a service account.

    Returns metadata for all credentials (active and revoked).
    Client secrets are not included in the response.

    Args:
        slug: Service account slug identifier
        auth: Current authenticated user context

    Returns:
        List of client credential metadata

    """
    query: typing.LiteralString = """
    MATCH (s:ServiceAccount {{slug: {slug}}})
          <-[:OWNED_BY]-(c:ClientCredential)
    RETURN c ORDER BY c.created_at DESC
    """
    records = await db.execute(
        query,
        {'slug': slug},
        ['c'],
    )

    credentials: list[models.ClientCredentialResponse] = []
    for record in records:
        data = graph.parse_agtype(record['c'])
        data['scopes'] = models.parse_scopes(data.get('scopes', []))
        credentials.append(models.ClientCredentialResponse(**data))

    LOGGER.debug(
        'Listed %d client credentials for service account %s',
        len(credentials),
        slug,
    )

    return credentials


@client_credentials_router.delete('/{client_id}', status_code=204)
async def revoke_client_credential(
    slug: str,
    client_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:update')
        ),
    ],
) -> None:
    """Revoke a client credential (soft delete).

    Revoked credentials can no longer be used for authentication
    but remain in the database for audit purposes.

    Args:
        slug: Service account slug identifier
        client_id: Client credential identifier to revoke
        auth: Current authenticated user context

    Raises:
        HTTPException: 404 if credential not found or not owned
            by the service account

    """
    now_str = datetime.datetime.now(datetime.UTC).isoformat()
    # Verify ownership and revoke atomically
    query: typing.LiteralString = """
    MATCH (s:ServiceAccount {{slug: {slug}}})
          <-[:OWNED_BY]-(c:ClientCredential
                         {{client_id: {client_id}}})
    SET c.revoked = true, c.revoked_at = {now}
    RETURN c
    """
    records = await db.execute(
        query,
        {
            'slug': slug,
            'client_id': client_id,
            'now': now_str,
        },
        ['c'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail='Client credential not found or not owned'
            ' by this service account',
        )

    LOGGER.info(
        'Client credential %s revoked for service account %s by %s',
        client_id,
        slug,
        auth.principal_name,
    )


@client_credentials_router.post(
    '/{client_id}/rotate',
    response_model=models.ClientCredentialCreateResponse,
)
async def rotate_client_credential(
    slug: str,
    client_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:update')
        ),
    ],
) -> models.ClientCredentialCreateResponse:
    """Rotate a client credential secret.

    Generates a new secret while keeping the same client_id and
    metadata. The old secret is immediately invalidated and the
    new secret is returned (shown only once).

    Args:
        slug: Service account slug identifier
        client_id: Client credential identifier to rotate
        auth: Current authenticated user context

    Returns:
        ClientCredentialCreateResponse with new client_secret

    Raises:
        HTTPException: 404 if credential not found or not owned
            by the service account
        HTTPException: 400 if credential is already revoked

    """
    # Verify ownership and fetch credential
    query: typing.LiteralString = """
    MATCH (s:ServiceAccount {{slug: {slug}}})
          <-[:OWNED_BY]-(c:ClientCredential
                         {{client_id: {client_id}}})
    RETURN c
    """
    records = await db.execute(
        query,
        {'slug': slug, 'client_id': client_id},
        ['c'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail='Client credential not found or not owned'
            ' by this service account',
        )

    credential_data = graph.parse_agtype(records[0]['c'])

    if credential_data.get('revoked', False):
        raise fastapi.HTTPException(
            status_code=400,
            detail='Cannot rotate revoked client credential',
        )

    # Generate new secret and update atomically with ownership
    new_secret, new_hash = await generate_secret()
    now_str = datetime.datetime.now(datetime.UTC).isoformat()

    update_query: typing.LiteralString = """
    MATCH (s:ServiceAccount {{slug: {slug}}})
          <-[:OWNED_BY]-(c:ClientCredential
                         {{client_id: {client_id}}})
    WHERE c.revoked = false
    SET c.client_secret_hash = {secret_hash},
        c.last_rotated = {now}
    RETURN c
    """
    updated = await db.execute(
        update_query,
        {
            'slug': slug,
            'client_id': client_id,
            'secret_hash': new_hash,
            'now': now_str,
        },
        ['c'],
    )
    if not updated:
        raise fastapi.HTTPException(
            status_code=409,
            detail='Client credential was modified during rotation',
        )

    LOGGER.info(
        'Client credential %s rotated for service account %s by user %s',
        client_id,
        slug,
        auth.principal_name,
    )

    return models.ClientCredentialCreateResponse(
        client_id=client_id,
        client_secret=new_secret,
        name=credential_data['name'],
        description=credential_data.get('description'),
        scopes=models.parse_scopes(credential_data.get('scopes', [])),
        expires_at=credential_data.get('expires_at'),
    )
