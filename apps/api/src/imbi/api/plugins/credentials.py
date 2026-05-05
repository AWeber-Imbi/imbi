"""Credential retrieval for plugin instances."""

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

    Routing depends on the plugin manifest's ``auth_type``:

    * ``api_token``: read the encrypted ``plugin_configuration`` blob
      stored directly on the ``Plugin`` node.
    * ``oauth2``: traverse ``Plugin <-[:HAS_PLUGIN]- ThirdPartyService
      -[:HAS_APPLICATION]-> ServiceApplication`` and read the legacy
      ``plugin_credentials`` field on the application.

    Raises:
        PluginCredentialsMissing: If required credentials are absent.
    """
    auth_type = entry.manifest.auth_type
    if auth_type == 'api_token':
        query: typing.LiteralString = """
        MATCH (p:Plugin {{id: {plugin_id}}})
        RETURN p.plugin_configuration AS creds
        LIMIT 1
        """
    else:
        # ``ThirdPartyService.service_application`` is a single edge in
        # the domain model, so this MATCH cannot legally fan out to
        # multiple apps. ``LIMIT 1`` is defensive.
        query = """
        MATCH (p:Plugin {{id: {plugin_id}}})
        <-[:HAS_PLUGIN]-(s:ThirdPartyService)
        -[:HAS_APPLICATION]->(a:ServiceApplication)
        RETURN a.plugin_credentials AS creds
        LIMIT 1
        """
    records = await db.execute(
        query,
        {'plugin_id': plugin_id},
        ['creds'],
    )
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
    return data if isinstance(data, dict) else {}  # pyright: ignore[reportUnknownVariableType]


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
