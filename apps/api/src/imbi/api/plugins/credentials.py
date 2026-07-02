"""Credential retrieval for plugin instances."""

import json
import logging
import typing

import fastapi
from imbi_common import graph
from imbi_common.auth.encryption import TokenEncryption
from imbi_common.plugins.errors import (
    PluginCredentialsMissing,
)
from imbi_common.plugins.registry import (
    RegistryEntry,
    list_plugins,
)

LOGGER = logging.getLogger(__name__)


def connection_plugin_slugs() -> list[str]:
    """Return the slugs of every registered ``connection``-type plugin.

    The connection sibling on a ``ThirdPartyService`` is identified by
    its manifest ``plugin_type``, but the graph ``Plugin`` node persists
    only ``plugin_slug`` (never ``plugin_type`` — that property lives on
    ``USES_PLUGIN`` assignment edges, not on the node or the
    ``HAS_PLUGIN`` edge). Callers that locate the connection sibling
    therefore match on ``plugin_slug`` against this registry-derived set.
    """
    return [
        e.manifest.slug
        for e in list_plugins()
        if e.manifest.plugin_type == 'connection'
    ]


# Bounded retries for the patch_plugin_configuration compare-and-swap
# (M19). Each retry re-reads the committed blob and re-applies the
# partial update on top, so concurrent patches converge; the cap only
# fires under pathological sustained contention on the same plugin.
_MAX_PATCH_RETRIES = 3


async def get_plugin_credentials(
    db: graph.Graph,
    plugin_id: str,
    entry: RegistryEntry,
) -> dict[str, str]:
    """Fetch and decrypt plugin credentials from the graph.

    Routing depends on the plugin manifest's ``auth_type``:

    * ``api_token`` / ``aws-iam-ic``: read the encrypted
      ``plugin_configuration`` blob stored directly on the ``Plugin``
      node. (``api_token`` is operator-pasted; ``aws-iam-ic`` self-mints
      its OIDC client and the host persists creds back via
      ``patch_plugin_configuration``.)
    * ``oauth2`` / ``oidc``: traverse the ``USES_APPLICATION`` edge to
      the linked ``ServiceApplication`` and pull plaintext
      ``client_id`` plus Fernet-decrypted ``client_secret``.

    Raises:
        PluginCredentialsMissing: If required credentials are absent or
            the plugin is not linked to a ServiceApplication.
    """
    auth_type = entry.manifest.auth_type
    if auth_type in ('api_token', 'aws-iam-ic'):
        return await _get_plugin_configuration_credentials(
            db, plugin_id, entry
        )
    return await _get_application_credentials(db, plugin_id, entry)


_OWN_BLOB: typing.LiteralString = """
MATCH (p:Plugin {{id: {plugin_id}}})
RETURN p.plugin_configuration AS creds
LIMIT 1
"""

# Single source for the connection-sibling traversal: locate the
# ``connection`` plugin on the invoked plugin's ThirdPartyService by
# ``plugin_slug`` (see ``connection_plugin_slugs``) because the node does
# not persist ``plugin_type``. Reused by both the credential fallback
# here (``_CONNECTION_BLOB``) and identity host resolution in
# ``identity/flows.py``, so the filter can't drift between the two — the
# ``plugin_type = 'connection'`` bug this replaced lived in both copies
# and had to be patched twice. Callers append only their ``RETURN``.
CONNECTION_SIBLING_MATCH: typing.LiteralString = """
MATCH (p:Plugin {{id: {plugin_id}}})<-[:HAS_PLUGIN]-(:ThirdPartyService)
  -[:HAS_PLUGIN]->(conn:Plugin)
WHERE conn.plugin_slug IN {connection_slugs}
"""

# The shared connection plugin holds the service-account credentials when
# the invoked plugin carries none of its own (deployment/lifecycle read
# the App/PAT off the github-connection sibling).
_CONNECTION_BLOB: typing.LiteralString = (
    CONNECTION_SIBLING_MATCH
    + 'RETURN conn.plugin_configuration AS creds\nLIMIT 1\n'
)


async def _read_blob(
    db: graph.Graph,
    query: typing.LiteralString,
    plugin_id: str,
    extra_params: dict[str, typing.Any] | None = None,
) -> dict[str, typing.Any]:
    """Read + decrypt a ``plugin_configuration`` blob to a dict.

    Treats a missing row, decrypt failure, or JSON parse error as "no
    credentials" (empty dict) rather than raising, so the caller can fall
    through to the next credential source.
    """
    params: dict[str, typing.Any] = {'plugin_id': plugin_id}
    if extra_params:
        params.update(extra_params)
    records = await db.execute(query, params, ['creds'])
    if not records or records[0].get('creds') is None:
        return {}
    creds_raw: str | None = graph.parse_agtype(records[0]['creds'])
    if not creds_raw:
        return {}
    try:
        decrypted_str = TokenEncryption.get_instance().decrypt(creds_raw)
    except Exception:  # noqa: BLE001
        LOGGER.warning(
            'Plugin credentials decrypt failed for plugin_id=%s', plugin_id
        )
        return {}
    if not decrypted_str:
        return {}
    try:
        parsed = json.loads(decrypted_str)
    except json.JSONDecodeError:
        LOGGER.warning(
            'Plugin credentials JSON parse failed for plugin_id=%s', plugin_id
        )
        return {}
    if not isinstance(parsed, dict):
        return {}
    return typing.cast('dict[str, typing.Any]', parsed)


async def _get_plugin_configuration_credentials(
    db: graph.Graph,
    plugin_id: str,
    entry: RegistryEntry,
) -> dict[str, str]:
    """Resolve credentials for ``api_token``/``aws-iam-ic`` plugins.

    Reads the plugin's own ``plugin_configuration`` blob; if it carries
    nothing usable, falls back to the ``connection`` plugin attached to
    the same ``ThirdPartyService`` (the shared service-account creds).
    """
    credentials: dict[str, typing.Any] = await _read_blob(
        db, _OWN_BLOB, plugin_id
    )
    if not credentials:
        credentials = await _read_blob(
            db,
            _CONNECTION_BLOB,
            plugin_id,
            {'connection_slugs': connection_plugin_slugs()},
        )

    required_fields = [f for f in entry.manifest.credentials if f.required]
    # ``null`` JSON values must be treated as missing — otherwise
    # ``{"token": null}`` would slip past the presence check and reach
    # the plugin handler as if the secret were configured.
    missing = [f.name for f in required_fields if not credentials.get(f.name)]
    if missing:
        raise PluginCredentialsMissing(
            f'Missing required credentials for plugin '
            f'{entry.manifest.slug!r}: {missing}'
        )
    return {k: str(v) for k, v in credentials.items() if v is not None}


async def _get_application_credentials(
    db: graph.Graph,
    plugin_id: str,
    entry: RegistryEntry,
) -> dict[str, str]:
    """Resolve OAuth2/OIDC credentials from the linked ServiceApplication."""
    query: typing.LiteralString = """
    MATCH (p:Plugin {{id: {plugin_id}}})
    -[:USES_APPLICATION]->(a:ServiceApplication)
    RETURN a.client_id AS client_id, a.client_secret AS client_secret
    LIMIT 1
    """
    records = await db.execute(
        query, {'plugin_id': plugin_id}, ['client_id', 'client_secret']
    )
    if not records:
        raise PluginCredentialsMissing(
            f'Plugin {entry.manifest.slug!r} is not linked to a'
            ' ServiceApplication; pick one on the Plugins tab'
        )
    record = records[0]
    client_id_raw = record.get('client_id')
    client_secret_raw = record.get('client_secret')
    if client_id_raw is None or client_secret_raw is None:
        raise PluginCredentialsMissing(
            f'Linked ServiceApplication for plugin {entry.manifest.slug!r}'
            ' is missing client_id or client_secret'
        )
    client_id = graph.parse_agtype(client_id_raw)
    client_secret_enc = graph.parse_agtype(client_secret_raw)
    try:
        client_secret = TokenEncryption.get_instance().decrypt(
            client_secret_enc
        )
    except Exception as exc:
        LOGGER.warning(
            'client_secret decrypt failed for plugin_id=%s: %s',
            plugin_id,
            exc,
        )
        raise PluginCredentialsMissing(
            f'Linked ServiceApplication for plugin {entry.manifest.slug!r}'
            ' has a client_secret that could not be decrypted'
        ) from exc
    if not client_secret:
        raise PluginCredentialsMissing(
            f'Linked ServiceApplication for plugin {entry.manifest.slug!r}'
            ' has no client_secret'
        )
    return {'client_id': str(client_id), 'client_secret': client_secret}


async def _read_plugin_configuration_raw(
    db: graph.Graph, plugin_id: str
) -> tuple[str | None, dict[str, typing.Any]]:
    """Internal: decrypt the plugin_configuration blob with its ciphertext.

    Returns ``(stored_blob, decrypted_dict)`` where ``stored_blob`` is
    the raw encrypted value as persisted (or ``None`` when absent/empty)
    — used as the compare-and-swap witness in
    ``patch_plugin_configuration``. ``decrypted_dict`` is ``{}`` when the
    blob is absent or empty. Raises ``ValueError`` when the blob is
    present but cannot be decrypted or parsed — callers must not silently
    overwrite a corrupted blob.
    """
    query: typing.LiteralString = """
    MATCH (p:Plugin {{id: {plugin_id}}})
    RETURN p.plugin_configuration AS creds
    LIMIT 1
    """
    records = await db.execute(query, {'plugin_id': plugin_id}, ['creds'])
    if not records or records[0].get('creds') is None:
        return None, {}
    raw = graph.parse_agtype(records[0]['creds'])
    if not raw:
        return None, {}
    try:
        plaintext = TokenEncryption.get_instance().decrypt(raw)
    except Exception as exc:
        raise ValueError(
            f'plugin_configuration for plugin_id={plugin_id!r} could not'
            ' be decrypted; refusing to overwrite'
        ) from exc
    if plaintext is None:
        raise ValueError(
            f'plugin_configuration for plugin_id={plugin_id!r} decrypted'
            ' to None; refusing to overwrite'
        )
    try:
        data = json.loads(plaintext)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f'plugin_configuration for plugin_id={plugin_id!r} is not'
            ' valid JSON; refusing to overwrite'
        ) from exc
    return raw, (data if isinstance(data, dict) else {})  # pyright: ignore[reportUnknownVariableType]


async def _read_plugin_configuration(
    db: graph.Graph, plugin_id: str
) -> dict[str, typing.Any]:
    """Internal: decrypt and return the plugin_configuration blob.

    Returns ``{}`` when the blob is absent or empty. Raises
    ``ValueError`` when the blob is present but cannot be decrypted or
    parsed — callers must not silently overwrite a corrupted blob.
    """
    _blob, data = await _read_plugin_configuration_raw(db, plugin_id)
    return data


async def patch_plugin_configuration(
    db: graph.Graph,
    plugin_id: str,
    updates: dict[str, str | None],
) -> list[str]:
    """Apply a partial update to ``plugin_configuration``.

    ``updates`` maps field name to new plaintext value. ``None`` (or
    empty string) removes the field. Existing keys not present in
    ``updates`` are preserved. Returns the resulting set of populated
    keys (no plaintext values).

    The read-modify-write is guarded by a compare-and-swap on the stored
    ciphertext (M19): the encrypted blob is opaque to AGE so it cannot be
    merged server-side, and a plain ``SET`` would let two concurrent
    patches clobber each other. Each attempt re-reads the committed blob
    and only writes when it is unchanged since the read; a lost CAS
    re-reads and re-applies the partial update on top of the winner.
    """
    for _attempt in range(_MAX_PATCH_RETRIES):
        expected_blob, current = await _read_plugin_configuration_raw(
            db, plugin_id
        )
        for key, value in updates.items():
            if value is None or value == '':
                current.pop(key, None)
            else:
                current[key] = value
        encrypted = TokenEncryption.get_instance().encrypt(json.dumps(current))
        query: typing.LiteralString = """
        MATCH (p:Plugin {{id: {plugin_id}}})
        WHERE coalesce(p.plugin_configuration, '') = {expected}
        SET p.plugin_configuration = {blob}
        RETURN p
        """
        updated = await db.execute(
            query,
            {
                'plugin_id': plugin_id,
                'expected': expected_blob or '',
                'blob': encrypted,
            },
            ['p'],
        )
        if updated:
            return [k for k, v in current.items() if v]
    raise fastapi.HTTPException(
        status_code=409,
        detail=(
            'plugin_configuration was modified concurrently; please retry'
        ),
    )


async def get_plugin_configuration_keys(
    db: graph.Graph,
    plugin_id: str,
) -> list[str]:
    """Return the set of credential field names currently set.

    The plaintext values themselves are never surfaced to the caller.
    """
    try:
        data = await _read_plugin_configuration(db, plugin_id)
    except ValueError:
        LOGGER.warning(
            'plugin_configuration unreadable for plugin_id=%s; '
            'reporting no keys',
            plugin_id,
        )
        return []
    return [k for k, v in data.items() if v]
