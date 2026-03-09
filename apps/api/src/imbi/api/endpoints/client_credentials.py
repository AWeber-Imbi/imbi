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
from imbi_common import neo4j

from imbi_api import models, settings
from imbi_api.auth import password, permissions

LOGGER = logging.getLogger(__name__)

client_credentials_router = fastapi.APIRouter(
    prefix='/service-accounts/{slug}/client-credentials',
    tags=['Client Credentials'],
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


@client_credentials_router.post(
    '',
    response_model=models.ClientCredentialCreateResponse,
    status_code=201,
)
async def create_client_credential(
    slug: str,
    credential_request: models.ClientCredentialCreate,
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
        ClientCredentialCreateResponse with client_secret (shown once)

    Raises:
        HTTPException: 404 if service account not found
        HTTPException: 400 if expiration exceeds maximum allowed

    """
    await _get_service_account(slug)

    auth_settings = settings.get_auth_settings()

    # Generate client_id and secret
    client_id = f'cc_{secrets.token_urlsafe(16)}'
    client_secret = secrets.token_urlsafe(32)
    secret_hash = password.hash_password(client_secret)

    # Validate expiration
    expires_at = None
    if credential_request.expires_in_days:
        if (
            credential_request.expires_in_days
            > auth_settings.api_key_max_lifetime_days
        ):
            raise fastapi.HTTPException(
                status_code=400,
                detail='Expiration exceeds maximum allowed lifetime'
                f' of {auth_settings.api_key_max_lifetime_days}'
                ' days',
            )
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
            days=credential_request.expires_in_days
        )

    # Create ClientCredential model
    credential = models.ClientCredential(
        client_id=client_id,
        client_secret_hash=secret_hash,
        name=credential_request.name,
        description=credential_request.description,
        scopes=credential_request.scopes,
        created_at=datetime.datetime.now(datetime.UTC),
        expires_at=expires_at,
        last_used=None,
        last_rotated=None,
        revoked=False,
        revoked_at=None,
    )

    # Store in Neo4j with relationship to ServiceAccount (atomic)
    query = """
    MATCH (s:ServiceAccount {slug: $slug})
    CREATE (c:ClientCredential $props)-[:OWNED_BY]->(s)
    RETURN elementId(c) AS element_id
    """
    props = credential.model_dump(mode='json')
    async with neo4j.run(query, slug=slug, props=props) as result:
        record = await result.single()
        if not record:
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
    query = """
    MATCH (s:ServiceAccount {slug: $slug})
          <-[:OWNED_BY]-(c:ClientCredential)
    RETURN c ORDER BY c.created_at DESC
    """
    async with neo4j.run(query, slug=slug) as result:
        records = await result.data()

    credentials = [
        models.ClientCredentialResponse(
            **neo4j.convert_neo4j_types(record['c'])
        )
        for record in records
    ]

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
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:update')
        ),
    ],
) -> None:
    """Revoke a client credential (soft delete).

    Revoked credentials can no longer be used for authentication but
    remain in the database for audit purposes.

    Args:
        slug: Service account slug identifier
        client_id: Client credential identifier to revoke
        auth: Current authenticated user context

    Raises:
        HTTPException: 404 if credential not found or not owned by
            the service account

    """
    # Verify ownership and revoke atomically
    query = """
    MATCH (s:ServiceAccount {slug: $slug})
          <-[:OWNED_BY]-(c:ClientCredential {client_id: $client_id})
    SET c.revoked = true, c.revoked_at = datetime()
    RETURN c
    """
    async with neo4j.run(query, slug=slug, client_id=client_id) as result:
        records = await result.data()

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
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:update')
        ),
    ],
) -> models.ClientCredentialCreateResponse:
    """Rotate a client credential secret.

    Generates a new secret while keeping the same client_id and
    metadata. The old secret is immediately invalidated and the new
    secret is returned (shown only once).

    Args:
        slug: Service account slug identifier
        client_id: Client credential identifier to rotate
        auth: Current authenticated user context

    Returns:
        ClientCredentialCreateResponse with new client_secret

    Raises:
        HTTPException: 404 if credential not found or not owned by
            the service account
        HTTPException: 400 if credential is already revoked

    """
    # Verify ownership and fetch credential
    query = """
    MATCH (s:ServiceAccount {slug: $slug})
          <-[:OWNED_BY]-(c:ClientCredential {client_id: $client_id})
    RETURN c
    """
    async with neo4j.run(query, slug=slug, client_id=client_id) as result:
        records = await result.data()

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail='Client credential not found or not owned'
            ' by this service account',
        )

    credential_data = records[0]['c']

    if credential_data.get('revoked', False):
        raise fastapi.HTTPException(
            status_code=400,
            detail='Cannot rotate revoked client credential',
        )

    # Generate new secret and update atomically with ownership check
    new_secret = secrets.token_urlsafe(32)
    new_hash = password.hash_password(new_secret)

    query = """
    MATCH (s:ServiceAccount {slug: $slug})
          <-[:OWNED_BY]-(c:ClientCredential {client_id: $client_id})
    WHERE c.revoked = false
    SET c.client_secret_hash = $secret_hash,
        c.last_rotated = datetime()
    RETURN c
    """
    async with neo4j.run(
        query,
        slug=slug,
        client_id=client_id,
        secret_hash=new_hash,
    ) as result:
        await result.consume()

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
        scopes=credential_data.get('scopes', []),
        expires_at=credential_data.get('expires_at'),
    )
