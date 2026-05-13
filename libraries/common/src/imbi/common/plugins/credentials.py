"""Credential retrieval for plugin instances.

Lives in ``imbi-common`` so any host that owns the graph (the API
process, the gateway, future workers) can fetch decrypted credentials
through one implementation.

Routing depends on the plugin manifest's ``auth_type``:

* ``api_token`` / ``aws-iam-ic``: read the Fernet-encrypted
  ``plugin_configuration`` blob stored on the ``Plugin`` node itself
  (``api_token`` is operator-pasted via the third-party-services UI;
  ``aws-iam-ic`` self-mints its OIDC client and the host persists
  values back via :func:`patch_plugin_configuration`).
* ``oauth2`` / ``oidc``: walk
  ``Plugin -[:USES_APPLICATION]-> ServiceApplication`` and pull
  plaintext ``client_id`` plus Fernet-decrypted ``client_secret``.
"""

import json
import logging
import typing

from imbi_common import graph
from imbi_common.auth.encryption import TokenEncryption
from imbi_common.plugins.errors import (
    PluginCredentialsMissing,
)
from imbi_common.plugins.registry import (
    RegistryEntry,
)

LOGGER = logging.getLogger(__name__)


async def get_plugin_credentials(
    db: graph.Graph,
    plugin_id: str,
    entry: RegistryEntry,
) -> dict[str, str]:
    """Fetch and decrypt plugin credentials from the graph.

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


async def _get_plugin_configuration_credentials(
    db: graph.Graph,
    plugin_id: str,
    entry: RegistryEntry,
) -> dict[str, str]:
    """Resolve credentials for ``api_token``/``aws-iam-ic`` plugins."""
    query: typing.LiteralString = """
    MATCH (p:Plugin {{id: {plugin_id}}})
    RETURN p.plugin_configuration AS creds
    LIMIT 1
    """
    records = await db.execute(query, {'plugin_id': plugin_id}, ['creds'])
    if not records or records[0].get('creds') is None:
        creds_raw: str | None = None
    else:
        creds_raw = graph.parse_agtype(records[0]['creds'])

    credentials: dict[str, typing.Any] = {}
    if creds_raw:
        # Treat decrypt failures and JSON parse errors as "no credentials"
        # rather than silently passing an empty dict that satisfies a
        # ``key in dict`` check downstream.
        try:
            decrypted_str = TokenEncryption.get_instance().decrypt(creds_raw)
        except Exception:  # noqa: BLE001
            LOGGER.warning(
                'Plugin credentials decrypt failed for plugin_id=%s',
                plugin_id,
            )
            decrypted_str = None
        if decrypted_str:
            try:
                credentials = json.loads(decrypted_str)
            except json.JSONDecodeError:
                LOGGER.warning(
                    'Plugin credentials JSON parse failed for plugin_id=%s',
                    plugin_id,
                )
                credentials = {}

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


async def _read_plugin_configuration(
    db: graph.Graph, plugin_id: str
) -> dict[str, typing.Any]:
    """Internal: decrypt and return the plugin_configuration blob.

    Returns ``{}`` when the blob is absent or empty. Raises
    ``ValueError`` when the blob is present but cannot be decrypted or
    parsed — callers must not silently overwrite a corrupted blob.
    """
    query: typing.LiteralString = """
    MATCH (p:Plugin {{id: {plugin_id}}})
    RETURN p.plugin_configuration AS creds
    LIMIT 1
    """
    records = await db.execute(query, {'plugin_id': plugin_id}, ['creds'])
    if not records or records[0].get('creds') is None:
        return {}
    raw = graph.parse_agtype(records[0]['creds'])
    if not raw:
        return {}
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
    if not isinstance(data, dict):
        raise ValueError(
            f'plugin_configuration for plugin_id={plugin_id!r} must be'
            ' a JSON object; refusing to overwrite'
        )
    return data  # pyright: ignore[reportUnknownVariableType]


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
    """
    current = await _read_plugin_configuration(db, plugin_id)
    for key, value in updates.items():
        if value is None or value == '':
            current.pop(key, None)
        else:
            current[key] = value
    encrypted = TokenEncryption.get_instance().encrypt(json.dumps(current))
    query: typing.LiteralString = """
    MATCH (p:Plugin {{id: {plugin_id}}})
    SET p.plugin_configuration = {blob}
    RETURN p
    """
    await db.execute(
        query,
        {'plugin_id': plugin_id, 'blob': encrypted},
        [],
    )
    return [k for k, v in current.items() if v]


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
