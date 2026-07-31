"""Service accounts for Imbi's own services.

``imbi-scheduler`` runs every ``api``-target task as its own service
account -- per ADR 0002 there is no credential store, so a client
credential of its own is the only identity a system task can run as --
and ``imbi-gateway`` calls back into imbi-api with a bearer token to
patch projects and record releases. Neither is created by hand any more:
``imbi-api setup`` seeds both, and ``setup-service-accounts`` brings an
existing install up to date.

imbi-assistant, imbi-mcp, and imbi-slackbot deliberately have no entry
here. Each forwards the *caller's* token to imbi-api rather than acting
as itself, so an account for them would carry privileges nothing uses.

Credentials come from the environment when it supplies them, so a
deployment whose secret already lives in a Helm values file or an
``.env`` gets an account matching the value it already hands the
service. Otherwise one is generated and returned for the caller to
print once -- it cannot be read back afterwards.
"""

import asyncio
import logging
import os
import secrets
import typing

from imbi.api import models
from imbi.api.auth import password
from imbi.common import graph

LOGGER = logging.getLogger(__name__)

#: What ``seed_internal_services`` did with a service's credential.
#: ``supplied`` -- written to match the environment; ``generated`` -- a
#: new one was minted and must be emitted; ``unchanged`` -- a credential
#: was already present and was left alone.
Outcome = typing.Literal['supplied', 'generated', 'unchanged']


class InternalService(typing.NamedTuple):
    """One of Imbi's services, and how it authenticates to imbi-api."""

    slug: str
    display_name: str
    description: str
    role_slug: str
    #: ``client_credential`` mints a token per run through
    #: ``/auth/token``; ``api_key`` is a static bearer sent as-is.
    credential: typing.Literal['client_credential', 'api_key']
    #: Environment variable carrying the public half. ``None`` for API
    #: keys, whose ``ik_<id>_<secret>`` form carries both halves in
    #: ``secret_var``.
    client_id_var: str | None
    secret_var: str


INTERNAL_SERVICES: tuple[InternalService, ...] = (
    InternalService(
        slug='imbi-scheduler',
        display_name='Imbi Scheduler',
        description=(
            'Runs scheduled tasks that target the Imbi API (ADR 0002)'
        ),
        role_slug='imbi-scheduler',
        credential='client_credential',
        client_id_var='IMBI_SCHEDULER_SA_CLIENT_ID',
        secret_var='IMBI_SCHEDULER_SA_CLIENT_SECRET',
    ),
    InternalService(
        slug='imbi-gateway',
        display_name='Imbi Gateway',
        description=(
            'Attributes inbound webhook events and patches projects '
            'and releases on their behalf'
        ),
        role_slug='imbi-gateway',
        credential='api_key',
        client_id_var=None,
        secret_var='ACTIONS_IMBI_TOKEN',
    ),
)


class SeededService(typing.NamedTuple):
    """Result of seeding one :class:`InternalService`."""

    service: InternalService
    account_created: bool
    outcome: Outcome
    #: Environment assignments a deployment must adopt. Populated only
    #: when ``outcome`` is ``generated`` -- the values are unrecoverable
    #: once the caller discards them.
    env: dict[str, str]


class SeedError(Exception):
    """Seeding could not complete.

    Raised rather than logged so ``setup`` exits non-zero: a service
    account without its role grants nothing, and a malformed supplied
    credential authenticates nobody.
    """


async def seed_internal_services(
    db: graph.Graph,
    org_slug: str,
    environ: typing.Mapping[str, str] | None = None,
) -> list[SeededService]:
    """Seed a service account and credential for each internal service.

    Idempotent: an account that exists is left in place (including a
    role an operator has since widened, and an ``is_active`` they have
    since cleared), and an existing credential is never rotated. What
    the environment supplies is always written, so a values file stays
    the source of truth for its own secret.

    Args:
        db: Graph database connection.
        org_slug: Organization the accounts become members of.
        environ: Environment to read credentials from. Defaults to
            ``os.environ``.

    Returns:
        One :class:`SeededService` per :data:`INTERNAL_SERVICES`, in
        declaration order.

    Raises:
        SeedError: A role or the organization is missing, or a supplied
            credential is malformed.

    """
    env = os.environ if environ is None else environ
    results: list[SeededService] = []
    for service in INTERNAL_SERVICES:
        created = await _ensure_account(db, service, org_slug)
        if service.credential == 'client_credential':
            outcome, emit = await _ensure_client_credential(db, service, env)
        else:
            outcome, emit = await _ensure_api_key(db, service, env)
        LOGGER.info(
            'Service account %s: account %s, credential %s',
            service.slug,
            'created' if created else 'already existed',
            outcome,
        )
        results.append(SeededService(service, created, outcome, emit))
    return results


async def _ensure_account(
    db: graph.Graph,
    service: InternalService,
    org_slug: str,
) -> bool:
    """Create the ``ServiceAccount`` node and its membership.

    Returns True when the account was newly created.
    """
    existing = await db.match(models.ServiceAccount, {'slug': service.slug})
    created = not existing
    if created:
        await db.create(
            models.ServiceAccount(
                slug=service.slug,
                display_name=service.display_name,
                description=service.description,
                is_active=True,
            )
        )
    await _ensure_membership(db, service, org_slug)
    return created


async def _ensure_membership(
    db: graph.Graph,
    service: InternalService,
    org_slug: str,
) -> None:
    """Give the account its role in *org_slug*, once.

    The role is set on the edge only when the edge is new. Re-seeding
    must not undo a role an operator widened deliberately -- silently
    narrowing a running service's privileges is the kind of failure
    that surfaces as a 403 in an unrelated scheduled task hours later.
    """
    edge = await db.execute(
        'MATCH (s:ServiceAccount {{slug: {slug}}})'
        '-[m:MEMBER_OF]->(o:Organization {{slug: {org_slug}}})'
        ' RETURN m.role AS role',
        {'slug': service.slug, 'org_slug': org_slug},
        ['role'],
    )
    if edge:
        return
    records = await db.execute(
        'MATCH (s:ServiceAccount {{slug: {slug}}})'
        ' MATCH (o:Organization {{slug: {org_slug}}})'
        ' MATCH (r:Role {{slug: {role_slug}}})'
        ' MERGE (s)-[m:MEMBER_OF]->(o)'
        ' SET m.role = {role_slug}'
        ' RETURN m',
        {
            'slug': service.slug,
            'org_slug': org_slug,
            'role_slug': service.role_slug,
        },
        ['m'],
    )
    if not records:
        # Empty result means the MATCH did not bind, so no edge was
        # written. An account with no membership resolves to an empty
        # permission set, which reads as a plain 403 at the far end.
        raise SeedError(
            f'Cannot grant {service.slug!r} the {service.role_slug!r} '
            f'role in organization {org_slug!r}: role or organization '
            f'not found'
        )


async def _ensure_client_credential(
    db: graph.Graph,
    service: InternalService,
    env: typing.Mapping[str, str],
) -> tuple[Outcome, dict[str, str]]:
    """Ensure the account owns a usable ``ClientCredential``.

    Both halves are required to adopt an environment-supplied
    credential: a client id without its secret cannot be verified, and a
    secret without its id names nothing to verify it against.
    """
    id_var = service.client_id_var
    client_id = env.get(id_var) if id_var else None
    secret = env.get(service.secret_var)
    if client_id and secret:
        await _write_client_credential(db, service, client_id, secret)
        return 'supplied', {}
    if await _has_credential(db, service.slug, 'ClientCredential'):
        return 'unchanged', {}
    client_id = f'cc_{secrets.token_urlsafe(16)}'
    secret = secrets.token_urlsafe(32)
    await _write_client_credential(db, service, client_id, secret)
    emit = {service.secret_var: secret}
    if id_var:
        emit[id_var] = client_id
    return 'generated', emit


async def _write_client_credential(
    db: graph.Graph,
    service: InternalService,
    client_id: str,
    secret: str,
) -> None:
    """Create the credential, or point an existing one at *secret*.

    Rewriting the hash of a credential the environment names is not a
    rotation: the plaintext the deployment holds is unchanged, and the
    stored hash is what has to follow it.
    """
    secret_hash = await asyncio.to_thread(password.hash_password, secret)
    updated = await db.execute(
        'MATCH (c:ClientCredential {{client_id: {client_id}}})'
        '-[:OWNED_BY]->(s:ServiceAccount {{slug: {slug}}})'
        ' SET c.client_secret_hash = {secret_hash}, c.revoked = false'
        ' RETURN c',
        {
            'client_id': client_id,
            'slug': service.slug,
            'secret_hash': secret_hash,
        },
        ['c'],
    )
    if updated:
        return
    credential = models.ClientCredential(
        client_id=client_id,
        client_secret_hash=secret_hash,
        name=f'{service.display_name} (seeded)',
        description=(
            f'Seeded by imbi-api setup for {service.slug}. '
            f'Supplied via {service.secret_var}.'
        ),
    )
    props = credential.model_dump(mode='json')
    props.pop('service_account', None)
    await _create_owned_node(db, 'ClientCredential', props, service.slug)


async def _ensure_api_key(
    db: graph.Graph,
    service: InternalService,
    env: typing.Mapping[str, str],
) -> tuple[Outcome, dict[str, str]]:
    """Ensure the account owns a usable ``APIKey``."""
    supplied = env.get(service.secret_var)
    if supplied:
        parsed = _parse_api_key(supplied)
        if parsed is None:
            raise SeedError(
                f'{service.secret_var} is not a valid Imbi API key: '
                f'expected the ik_<id>_<secret> form issued by '
                f'POST /service-accounts/{service.slug}/api-keys'
            )
        key_id, secret = parsed
        await _write_api_key(db, service, key_id, secret)
        return 'supplied', {}
    if await _has_credential(db, service.slug, 'APIKey'):
        return 'unchanged', {}
    key_id = f'ik_{secrets.token_hex(16)}'
    secret = secrets.token_urlsafe(32)
    await _write_api_key(db, service, key_id, secret)
    return 'generated', {service.secret_var: f'{key_id}_{secret}'}


def _parse_api_key(value: str) -> tuple[str, str] | None:
    """Split ``ik_<id>_<secret>`` into ``(key_id, secret)``.

    Mirrors the split in ``imbi.common.auth.permissions``
    ``authenticate_api_key``; anything it would reject at request time
    is rejected here instead of being seeded and never working.
    """
    parts = value.split('_', 2)
    if len(parts) != 3 or parts[0] != 'ik' or not parts[1] or not parts[2]:
        return None
    return f'ik_{parts[1]}', parts[2]


async def _write_api_key(
    db: graph.Graph,
    service: InternalService,
    key_id: str,
    secret: str,
) -> None:
    """Create the API key, or point an existing one at *secret*."""
    key_hash = await asyncio.to_thread(password.hash_password, secret)
    updated = await db.execute(
        'MATCH (k:APIKey {{key_id: {key_id}}})'
        '-[:OWNED_BY]->(s:ServiceAccount {{slug: {slug}}})'
        ' SET k.key_hash = {key_hash}, k.revoked = false'
        ' RETURN k',
        {
            'key_id': key_id,
            'slug': service.slug,
            'key_hash': key_hash,
        },
        ['k'],
    )
    if updated:
        return
    api_key = models.APIKey(
        key_id=key_id,
        key_hash=key_hash,
        name=f'{service.display_name} (seeded)',
        description=(
            f'Seeded by imbi-api setup for {service.slug}. '
            f'Supplied via {service.secret_var}.'
        ),
    )
    props = api_key.model_dump(mode='json')
    props.pop('user', None)
    await _create_owned_node(db, 'APIKey', props, service.slug)


async def _has_credential(
    db: graph.Graph,
    slug: str,
    label: typing.Literal['ClientCredential', 'APIKey'],
) -> bool:
    """Report whether *slug* already owns a live credential.

    Revoked credentials do not count: one left behind by an operator
    would otherwise suppress seeding forever, leaving the service with
    nothing it can authenticate with.
    """
    records = await db.execute(
        f'MATCH (c:{label})-[:OWNED_BY]->'
        '(s:ServiceAccount {{slug: {slug}}})'
        ' WHERE c.revoked = false'
        ' RETURN count(c) AS live',
        {'slug': slug},
        ['live'],
    )
    if not records:
        return False
    return bool(graph.parse_agtype(records[0].get('live')))


async def _create_owned_node(
    db: graph.Graph,
    label: typing.Literal['ClientCredential', 'APIKey'],
    props: dict[str, typing.Any],
    slug: str,
) -> None:
    """``CREATE`` *label* wired to the ``ServiceAccount`` *slug*."""
    prop_map = ', '.join(f'{key}: {{{key}}}' for key in props)
    records = await db.execute(
        f'MATCH (s:ServiceAccount {{{{slug: {{slug}}}}}})'
        f' CREATE (n:{label} {{{{{prop_map}}}}})'
        f'-[:OWNED_BY]->(s) RETURN n',
        {**props, 'slug': slug},
        ['n'],
    )
    if not records:
        raise SeedError(
            f'Cannot create {label} for service account {slug!r}: '
            f'account not found'
        )
