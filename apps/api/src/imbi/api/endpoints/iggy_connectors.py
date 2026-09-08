"""Sink configuration for the Apache Iggy connectors runtime.

The connectors runtime does not carry its own sink definitions. Its
``http`` configuration provider fetches them from here once at startup
(``GET /configs/active``) and never polls again, so a change takes
effect on a runtime restart. ADR 0019 §3 records the decision; the
contract is ``connectors/README.md`` in ``AWeber-Imbi/iggy``.

One sink is rendered per stream in :data:`imbi.common.iggy.TOPICS`, so
the streams Imbi publishes to and the streams the ClickHouse sink drains
are one list, not two. The ClickHouse coordinates come from this
service's own ``settings.Clickhouse``: the runtime marks ``plugin_config``
as not environment-addressable, so credentials cannot reach the sink any
other way.

Because the response body carries those credentials, every route
requires ``Authorization: Bearer <key>`` matched against
``IMBI_IGGY_CONNECTORS_API_KEYS``. With no key configured the endpoint
answers 503 rather than opening up. The router is excluded from the
OpenAPI schema, which keeps it out of the UI client codegen and the MCP
tool surface.

The runtime also proxies its own operator API to the remaining routes in
the contract. Versions here are code, not data, so the write routes
answer 405 -- Starlette raises it for a method no route on a matched
path declares, so only the GETs are registered.
"""

import logging
import secrets
import typing

import fastapi
import pydantic

from imbi.api import settings
from imbi.common import iggy

LOGGER = logging.getLogger(__name__)

#: Where the image places the compiled ClickHouse sink plugin. The
#: runtime appends ``.so`` itself.
PLUGIN_PATH = '/opt/iggy/connectors/libiggy_connector_clickhouse_sink'

#: Sink settings pinned by ADR 0019 §3.
BATCH_LENGTH = 1000
POLL_INTERVAL = '250ms'
MAX_RETRIES = 3
RETRY_DELAY = 1
TIMEOUT_SECONDS = 30

#: The one version each sink has. The configuration is generated from
#: code, so there is no version history to serve and no creation time to
#: report; the epoch stands in for one.
VERSION = 0
CREATED_AT = '1970-01-01T00:00:00Z'

#: Fallbacks matching ``clickhouse.client.Clickhouse._connect``, which
#: reads the same DSN. ``ClickHouseDsn`` fills in port 9000 when the DSN
#: omits one, so an unported DSN sends the sink to the same place the
#: direct client goes; neither ever sees ``None``.
DEFAULT_PORT = 9000
DEFAULT_DATABASE = 'internal'
DEFAULT_USERNAME = 'default'

_warned_unconfigured = False


class StreamConsumerConfig(pydantic.BaseModel):
    """One stream the sink consumes, with its consumer-group settings."""

    stream: str
    topics: list[str]
    schema_: typing.Literal['json'] = pydantic.Field(
        default='json', serialization_alias='schema'
    )
    avro_schema_json: str | None = None
    avro_schema_path: str | None = None
    batch_length: int = BATCH_LENGTH
    poll_interval: str = POLL_INTERVAL
    consumer_group: str


class SinkConfig(pydantic.BaseModel):
    """One connector sink, as the runtime deserializes it.

    The runtime's struct carries no container-level ``serde(default)``,
    so every field has to be present. Nullable fields are serialized as
    explicit ``null`` rather than omitted.
    """

    key: str
    enabled: bool = True
    version: int = VERSION
    name: str
    path: str = PLUGIN_PATH
    transforms: dict[str, typing.Any] | None = None
    streams: list[StreamConsumerConfig]
    plugin_config_format: typing.Literal['json'] = 'json'
    plugin_config: dict[str, typing.Any]
    verbose: bool = False
    benchmark: bool = False


class ConnectorsConfig(pydantic.BaseModel):
    """The whole active configuration: every sink, and no sources."""

    sinks: dict[str, SinkConfig]
    sources: dict[str, SinkConfig] = {}


class ConfigVersion(pydantic.BaseModel):
    """The active version of one connector."""

    version: int = VERSION
    created_at: str = CREATED_AT


class ConnectorConfigVersions(pydantic.BaseModel):
    """Active versions, keyed the same way as the configurations."""

    sinks: dict[str, ConfigVersion]
    sources: dict[str, ConfigVersion] = {}


def _require_api_key(request: fastapi.Request) -> None:
    """Reject anything not carrying a configured bearer token.

    Answers 503 when no key is configured, so a deployment that forgot
    to set one fails closed instead of serving ClickHouse credentials to
    anyone who asks.
    """
    global _warned_unconfigured
    keys = settings.get_iggy_connectors_settings().api_keys
    if not keys:
        if not _warned_unconfigured:
            _warned_unconfigured = True
            LOGGER.error(
                'IMBI_IGGY_CONNECTORS_API_KEYS is unset; refusing to serve '
                'the Iggy connector configuration'
            )
        raise fastapi.HTTPException(
            status_code=503, detail='Connector configuration is not enabled'
        )
    scheme, _, token = request.headers.get('Authorization', '').partition(' ')
    # compare_digest over every configured key, not a set lookup, so an
    # overlapping key during rotation is accepted without leaking which
    # one matched through timing.
    if scheme.lower() != 'bearer' or not any(
        secrets.compare_digest(token, key) for key in keys
    ):
        raise fastapi.HTTPException(status_code=401, detail='Unauthorized')


iggy_connectors_router = fastapi.APIRouter(
    prefix='/iggy/connectors',
    tags=['Iggy Connectors'],
    dependencies=[fastapi.Depends(_require_api_key)],
    include_in_schema=False,
)


def clickhouse_plugin_config(table: str) -> dict[str, typing.Any]:
    """Render the ClickHouse sink plugin configuration for one table.

    The DSN is read exactly as ``Clickhouse._connect`` reads it, so the
    sink writes to the database this service would have inserted into.
    """
    url = settings.Clickhouse().url
    port = url.port or DEFAULT_PORT
    database = (url.path or '')[1:] or DEFAULT_DATABASE
    # ``clickhouses`` is pydantic's secure ClickHouse scheme; every other
    # scheme it accepts reaches the HTTP interface unencrypted.
    protocol = 'https' if url.scheme == 'clickhouses' else 'http'
    return {
        'url': f'{protocol}://{url.host}:{port}',
        'database': database,
        'username': url.username or DEFAULT_USERNAME,
        'password': url.password or '',
        'table': table,
        'insert_format': 'json_each_row',
        'timeout_seconds': TIMEOUT_SECONDS,
        'max_retries': MAX_RETRIES,
        'retry_delay': RETRY_DELAY,
        'verbose_logging': False,
    }


def sink_config(stream: str, topics: tuple[str, ...]) -> SinkConfig:
    """Build the sink that drains one stream into its ClickHouse table.

    A stream is named for the table it lands in, so the stream name is
    also the table name and the consumer group.
    """
    return SinkConfig(
        key=stream,
        name=f'ClickHouse sink: {stream}',
        streams=[
            StreamConsumerConfig(
                stream=stream,
                topics=list(topics),
                consumer_group=stream,
            )
        ],
        plugin_config=clickhouse_plugin_config(stream),
    )


def _sink_or_404(key: str) -> SinkConfig:
    if key not in iggy.TOPICS:
        raise fastapi.HTTPException(status_code=404, detail='Unknown sink')
    return sink_config(key, iggy.TOPICS[key])


@iggy_connectors_router.get('/configs/active')
async def get_active_configs() -> ConnectorsConfig:
    """Every active sink. The only route the runtime needs to start."""
    return ConnectorsConfig(
        sinks={
            stream: sink_config(stream, topics)
            for stream, topics in iggy.TOPICS.items()
        }
    )


@iggy_connectors_router.get('/configs/active/versions')
async def get_active_versions() -> ConnectorConfigVersions:
    """The active version of every sink."""
    return ConnectorConfigVersions(
        sinks={stream: ConfigVersion() for stream in iggy.TOPICS}
    )


@iggy_connectors_router.get('/sinks/{key}/configs')
async def get_sink_configs(key: str) -> list[SinkConfig]:
    """Every version of one sink, of which there is exactly one."""
    return [_sink_or_404(key)]


@iggy_connectors_router.get('/sinks/{key}/configs/active')
async def get_active_sink_config(key: str) -> SinkConfig:
    """The active version of one sink."""
    return _sink_or_404(key)


@iggy_connectors_router.get('/sinks/{key}/configs/{version}')
async def get_sink_config(key: str, version: int) -> SinkConfig:
    """One version of one sink.

    404 means absent to the runtime's provider rather than an error, so
    any version but the one this service generates is a 404.
    """
    config = _sink_or_404(key)
    if version != VERSION:
        raise fastapi.HTTPException(status_code=404, detail='Unknown version')
    return config
