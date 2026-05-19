"""Graph CRUD for ``IdentityConnection`` nodes.

Encryption boundary: this module is the *only* place that touches the
:class:`imbi_common.auth.encryption.TokenEncryption` singleton for
identity tokens.  Plaintext credentials enter via ``upsert_connection``
and leave via :class:`IdentityCredentialsInternal` from
``load_connection``; the rest of the API code path never handles
ciphertext directly.
"""

import datetime
import json
import logging
import typing

import nanoid
from imbi_common import graph
from imbi_common.auth.encryption import TokenEncryption
from imbi_common.plugins.base import IdentityCredentials, IdentityProfile

from imbi_api.identity.models import IdentityCredentialsInternal

LOGGER = logging.getLogger(__name__)


def _parse_metadata(raw: typing.Any) -> dict[str, typing.Any]:
    """Decode the ``metadata`` agtype value into a dict.

    ``imbi_common.graph.client`` JSON-encodes dict parameters and stores
    them as Cypher string literals, so round-tripping an empty dict
    yields the literal string ``'{}'``.  Accept dicts (in case the
    storage layer changes), and JSON-decode strings; fall back to an
    empty dict on anything malformed rather than 500ing a list response.
    """
    if raw is None:
        return {}
    parsed = graph.parse_agtype(raw)
    if isinstance(parsed, dict):
        return typing.cast('dict[str, typing.Any]', parsed)
    if isinstance(parsed, str):
        if not parsed:
            return {}
        try:
            decoded = json.loads(parsed)
        except (json.JSONDecodeError, TypeError):
            return {}
        if isinstance(decoded, dict):
            return typing.cast('dict[str, typing.Any]', decoded)
        return {}
    return {}


def _decrypt(value: typing.Any) -> str | None:
    if value is None:
        return None
    raw = graph.parse_agtype(value) if not isinstance(value, str) else value
    if not raw:
        return None
    return TokenEncryption.get_instance().decrypt(raw)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


async def upsert_connection(
    db: graph.Graph,
    plugin_id: str,
    user_id: str,
    profile: IdentityProfile,
    credentials: IdentityCredentials,
    *,
    metadata: dict[str, typing.Any] | None = None,
) -> str:
    """MERGE the user's connection for this plugin and persist tokens.

    Returns the connection's nano-ID.  Sets ``status='active'``,
    ``last_used_at=now()``.
    """
    encryption = TokenEncryption.get_instance()
    enc_access = encryption.encrypt(credentials.access_token)
    enc_refresh = (
        encryption.encrypt(credentials.refresh_token)
        if credentials.refresh_token
        else None
    )
    enc_claims = (
        encryption.encrypt(json.dumps(profile.raw_claims))
        if profile.raw_claims
        else None
    )

    expires_at = (
        credentials.expires_at.isoformat() if credentials.expires_at else None
    )

    new_id = nanoid.generate()
    now = _now_iso()

    # Propagate the provider login (e.g. GitHub's ``login`` claim) into
    # plain-text metadata so callers can use it for filtering without
    # having to decrypt the claims ciphertext.  Caller-supplied metadata
    # takes precedence; we only set the key when it is absent.
    effective_metadata: dict[str, typing.Any] = dict(metadata or {})
    raw_login = profile.raw_claims.get('login') if profile.raw_claims else None
    if raw_login and 'login' not in effective_metadata:
        effective_metadata['login'] = str(raw_login)

    # AGE doesn't implement ON CREATE SET, so the MERGE below uses
    # coalesce() to preserve ``id`` and ``created_at`` on the existing
    # row while every other field is overwritten.
    query: typing.LiteralString = """
    MERGE (c:IdentityConnection {{plugin_id: {plugin_id},
                                  user_id: {user_id}}})
    SET c.id = coalesce(c.id, {new_id}),
        c.created_at = coalesce(c.created_at, {now}),
        c.subject = {subject},
        c.access_token_encrypted = {access},
        c.refresh_token_encrypted = {refresh},
        c.id_token_claims_encrypted = {claims},
        c.expires_at = {expires_at},
        c.scopes = {scopes},
        c.status = 'active',
        c.last_used_at = {now},
        c.updated_at = {now},
        c.metadata = {metadata}
    WITH c
    MATCH (u:User {{id: {user_id}}}), (p:Plugin {{id: {plugin_id}}})
    MERGE (u)-[:HAS_IDENTITY]->(c)
    MERGE (c)-[:USES_PLUGIN]->(p)
    RETURN c.id AS id
    """
    params = {
        'plugin_id': plugin_id,
        'user_id': user_id,
        'new_id': new_id,
        'now': now,
        'subject': profile.subject,
        'access': enc_access,
        'refresh': enc_refresh,
        'claims': enc_claims,
        'expires_at': expires_at,
        'scopes': credentials.scopes,
        'metadata': effective_metadata,
    }

    try:
        records = await db.execute(query, params, ['id'])
    except Exception:
        LOGGER.exception(
            'Failed to upsert IdentityConnection plugin_id=%s user_id=%s',
            plugin_id,
            user_id,
        )
        raise
    if not records:
        raise RuntimeError('upsert_connection returned no rows')
    return str(graph.parse_agtype(records[0]['id']))


async def load_connection(
    db: graph.Graph,
    plugin_id: str,
    user_id: str,
) -> IdentityCredentialsInternal | None:
    """Load and decrypt the actor's connection for ``plugin_id``."""
    query: typing.LiteralString = """
    MATCH (c:IdentityConnection {{plugin_id: {plugin_id},
                                  user_id: {user_id}}})
    RETURN c.id AS id,
           c.subject AS subject,
           c.access_token_encrypted AS access,
           c.refresh_token_encrypted AS refresh,
           c.expires_at AS expires_at,
           c.scopes AS scopes,
           c.status AS status,
           c.metadata AS metadata
    LIMIT 1
    """
    records = await db.execute(
        query,
        {'plugin_id': plugin_id, 'user_id': user_id},
        [
            'id',
            'subject',
            'access',
            'refresh',
            'expires_at',
            'scopes',
            'status',
            'metadata',
        ],
    )
    if not records:
        return None
    row = records[0]
    access = _decrypt(row.get('access'))
    if access is None:
        LOGGER.warning(
            'IdentityConnection plugin_id=%s user_id=%s missing access token',
            plugin_id,
            user_id,
        )
        return None
    refresh = _decrypt(row.get('refresh'))

    expires_raw = (
        graph.parse_agtype(row['expires_at'])
        if row.get('expires_at') is not None
        else None
    )
    expires_at = (
        datetime.datetime.fromisoformat(expires_raw) if expires_raw else None
    )

    scopes_raw: typing.Any = (
        graph.parse_agtype(row['scopes']) if row.get('scopes') else []
    )
    scopes: list[str] = list(scopes_raw or [])

    return IdentityCredentialsInternal(
        connection_id=graph.parse_agtype(row['id']),
        plugin_id=plugin_id,
        user_id=user_id,
        subject=graph.parse_agtype(row['subject']),
        access_token=access,
        refresh_token=refresh,
        expires_at=expires_at,
        scopes=scopes,
        status=graph.parse_agtype(row['status']),
        metadata=_parse_metadata(row.get('metadata')),
    )


async def mark_status(
    db: graph.Graph,
    connection_id: str,
    status: typing.Literal['active', 'revoked', 'expired'],
) -> None:
    """Update the ``status`` field on a connection."""
    query: typing.LiteralString = """
    MATCH (c:IdentityConnection {{id: {id}}})
    SET c.status = {status}, c.updated_at = {now}
    """
    await db.execute(
        query,
        {'id': connection_id, 'status': status, 'now': _now_iso()},
        [],
    )


async def connection_status(
    db: graph.Graph,
    plugin_id: str,
    user_id: str,
) -> str | None:
    """Return the connection's current ``status`` field (or ``None``).

    Distinct from :func:`load_connection`, which short-circuits to
    ``None`` once the access token has been cleared — that conflates
    "no connection" with "connection exists but was revoked", and the
    revoke / forget UI needs to tell those apart.
    """
    query: typing.LiteralString = """
    MATCH (c:IdentityConnection {{plugin_id: {plugin_id},
                                  user_id: {user_id}}})
    RETURN c.status AS status
    LIMIT 1
    """
    rows = await db.execute(
        query, {'plugin_id': plugin_id, 'user_id': user_id}, ['status']
    )
    if not rows:
        return None
    raw = rows[0].get('status')
    return graph.parse_agtype(raw) if raw is not None else None


async def delete_connection(
    db: graph.Graph,
    plugin_id: str,
    user_id: str,
) -> None:
    """Hard-delete the user's connection node and its edges."""
    query: typing.LiteralString = """
    MATCH (c:IdentityConnection {{plugin_id: {plugin_id},
                                  user_id: {user_id}}})
    DETACH DELETE c
    """
    await db.execute(query, {'plugin_id': plugin_id, 'user_id': user_id}, [])


async def revoke(
    db: graph.Graph,
    plugin_id: str,
    user_id: str,
) -> None:
    """Mark the user's connection revoked and clear tokens."""
    query: typing.LiteralString = """
    MATCH (c:IdentityConnection {{plugin_id: {plugin_id},
                                  user_id: {user_id}}})
    SET c.status = 'revoked',
        c.access_token_encrypted = null,
        c.refresh_token_encrypted = null,
        c.id_token_claims_encrypted = null,
        c.updated_at = {now}
    """
    await db.execute(
        query,
        {'plugin_id': plugin_id, 'user_id': user_id, 'now': _now_iso()},
        [],
    )


async def list_for_user(
    db: graph.Graph,
    user_id: str,
) -> list[dict[str, typing.Any]]:
    """Return raw connection rows for the actor (for admin / settings UI)."""
    query: typing.LiteralString = """
    MATCH (u:User {{id: {user_id}}})-[:HAS_IDENTITY]->(c:IdentityConnection)
    OPTIONAL MATCH (c)-[:USES_PLUGIN]->(p:Plugin)
    RETURN c.id AS id,
           c.plugin_id AS plugin_id,
           p.plugin_slug AS plugin_slug,
           p.label AS plugin_label,
           p.connects_users_to AS connects_users_to,
           c.subject AS subject,
           c.status AS status,
           c.expires_at AS expires_at,
           c.scopes AS scopes,
           c.last_used_at AS last_used_at,
           c.metadata AS metadata,
           c.id_token_claims_encrypted AS claims_enc
    """
    records = await db.execute(
        query,
        {'user_id': user_id},
        [
            'id',
            'plugin_id',
            'plugin_slug',
            'plugin_label',
            'connects_users_to',
            'subject',
            'status',
            'expires_at',
            'scopes',
            'last_used_at',
            'metadata',
            'claims_enc',
        ],
    )
    out: list[dict[str, typing.Any]] = []
    for row in records:
        decoded = {k: graph.parse_agtype(v) for k, v in row.items()}
        meta = _parse_metadata(row.get('metadata'))
        # Backfill ``login`` for connections created before the metadata
        # propagation fix — decrypt the claims ciphertext and extract it.
        if 'login' not in meta:
            claims_plain = _decrypt(row.get('claims_enc'))
            if claims_plain:
                try:
                    claims = json.loads(claims_plain)
                    if isinstance(claims, dict) and claims.get('login'):
                        meta['login'] = str(claims['login'])
                except (json.JSONDecodeError, TypeError):
                    pass
        decoded['metadata'] = meta
        # Don't leak the ciphertext to callers.
        decoded.pop('claims_enc', None)
        out.append(decoded)
    return out


async def find_user_by_subject(
    db: graph.Graph,
    plugin_slug: str,
    subject: str,
) -> str | None:
    """Return the Imbi user_id whose active connection has this subject.

    ``subject`` is the external provider's unique ID — for GitHub plugins
    this is the numeric user ID as a string (e.g. ``"12345"``), which is
    what :func:`imbi_plugin_github.plugin._build_userinfo` stores.

    Returns ``None`` when no active connection matches OR when more than
    one distinct Imbi user is reachable from the (``plugin_slug``,
    ``subject``) pair — that's a data bug we don't want to paper over by
    silently picking one. Callers (the gateway in particular) treat
    ``None`` as "do not attribute" rather than as "no such user".
    """
    query: typing.LiteralString = """
    MATCH (c:IdentityConnection {{subject: {subject}}})
          -[:USES_PLUGIN]->(p:Plugin {{plugin_slug: {plugin_slug}}})
    WHERE c.status = 'active'
    OPTIONAL MATCH (u:User)-[:HAS_IDENTITY]->(c)
    WITH collect(DISTINCT u.id) AS user_ids
    RETURN user_ids
    """
    records = await db.execute(
        query,
        {'subject': subject, 'plugin_slug': plugin_slug},
        ['user_ids'],
    )
    if not records:
        return None
    parsed = graph.parse_agtype(records[0]['user_ids'])
    if not isinstance(parsed, list):
        return None
    # mypy already sees parsed as list[Any] after the isinstance narrow
    # (so any extra cast is "redundant"); basedpyright's strict mode
    # narrows to list[Unknown] and demands an annotation. Suppress the
    # latter on this single statement rather than carry a runtime cast.
    user_ids: list[typing.Any] = parsed  # pyright: ignore[reportUnknownVariableType]
    matches: list[str] = [str(uid) for uid in user_ids if uid]
    if len(matches) != 1:
        if len(matches) > 1:
            LOGGER.error(
                'plugin_slug=%r subject=%r resolved to multiple Imbi '
                'users %r; refusing to guess',
                plugin_slug,
                subject,
                sorted(matches),
            )
        return None
    return matches[0]


async def stale_connections(
    db: graph.Graph,
    before: datetime.datetime,
) -> list[dict[str, typing.Any]]:
    """Return active connections whose ``expires_at < before`` and that
    have a refresh token, for the background refresh sweeper.
    """
    query: typing.LiteralString = """
    MATCH (c:IdentityConnection)
    WHERE c.status = 'active'
      AND c.refresh_token_encrypted IS NOT NULL
      AND c.expires_at IS NOT NULL
      AND c.expires_at < {before}
    RETURN c.id AS id,
           c.plugin_id AS plugin_id,
           c.user_id AS user_id
    """
    records = await db.execute(
        query, {'before': before.isoformat()}, ['id', 'plugin_id', 'user_id']
    )
    return [
        {k: graph.parse_agtype(v) for k, v in row.items()} for row in records
    ]
