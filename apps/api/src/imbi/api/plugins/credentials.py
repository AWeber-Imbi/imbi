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

    Traverses Plugin <- HAS_PLUGIN - ThirdPartyService
    -> HAS_APPLICATION -> ServiceApplication and decrypts
    the plugin_credentials field.

    Raises:
        PluginCredentialsMissing: If required credentials are absent.
    """
    # ``ThirdPartyService.service_application`` is a single edge in the
    # domain model, so this MATCH cannot legally fan out to multiple
    # apps. ``LIMIT 1`` is defensive — if a misbehaving migration ever
    # writes more than one ``HAS_APPLICATION`` edge we want the read to
    # fail closed (missing credentials) rather than pick at random.
    query: typing.LiteralString = """
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
