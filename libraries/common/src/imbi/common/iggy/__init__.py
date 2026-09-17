import typing

import pydantic

from . import client
from .client import PublishError

__all__ = [
    'TOPICS',
    'PublishError',
    'aclose',
    'ensure_topic',
    'initialize',
    'ping',
    'publish',
    'publish_rows',
    'stored_bytes',
]

#: The streams Imbi publishes to and the topics of each, keyed by stream
#: name, which is also the ClickHouse table the stream lands in.
#:
#: This is the single source of truth for the streams and topics the
#: ClickHouse sink consumes: imbi-api serves the sink configuration
#: generated from this mapping to the Iggy connectors runtime over HTTP,
#: so a topic added here is a topic the sink drains, with no second list
#: to keep in step.
#:
#: Topics split a stream by the feature that produces the rows. The
#: runtime reads this mapping once at startup, so a topic added here
#: reaches ClickHouse after the connectors runtime restarts.
TOPICS: dict[str, tuple[str, ...]] = {
    'commit_drift': ('drift',),
    'commits': ('github', 'maintenance'),
    'document_read_events': ('documents',),
    'document_read_sessions': ('documents',),
    'document_versions': ('documents',),
    'email_audit': ('email',),
    'events': ('comments', 'documents', 'gateway', 'lifecycle', 'projects'),
    'maintenance_log': ('maintenance',),
    'operations_log': ('api', 'configuration', 'deployments', 'maintenance'),
    'pull_requests': ('github',),
    'release_component_batches': ('sbom',),
    'release_components': ('sbom',),
    'scheduler_runs': ('scheduler',),
    'score_history': ('scoring',),
    'tags': ('github',),
}


async def initialize() -> bool:
    """Create a new client and test the connection."""
    return await client.Iggy.get_instance().initialize()


async def aclose() -> None:
    """Discard the Iggy client."""
    await client.Iggy.get_instance().aclose()


async def ensure_topic(stream: str, topic: str) -> None:
    """Create the stream and topic when they do not exist yet."""
    await client.Iggy.get_instance().ensure_topic(stream, topic)


async def ping() -> None:
    """Round-trip a ping to the server to prove the connection works."""
    await client.Iggy.get_instance().ping()


async def stored_bytes() -> int:
    """Total bytes Iggy holds across every stream in `TOPICS`."""
    return await client.Iggy.get_instance().stored_bytes()


async def publish(
    stream: str,
    topic: str,
    models: list[pydantic.BaseModel],
    *,
    columns: list[str] | None = None,
    headers: dict[str, str] | None = None,
) -> None:
    """Publish one message per model to a stream's topic.

    Args:
        stream: The name of the stream to publish to
        topic: The name of the topic within that stream
        models: List of Pydantic models to publish (all the same type)
        columns: Restrict each payload to these keys, in this order
        headers: Iggy ``user_headers`` set on every message

    Raises:
        ValueError: If models is empty or the models are mixed types
        PublishError: If the send fails
    """
    await client.Iggy.get_instance().publish(
        stream, topic, models, columns=columns, headers=headers
    )


async def publish_rows(
    stream: str,
    topic: str,
    rows: list[dict[str, typing.Any]],
    *,
    headers: dict[str, str] | None = None,
) -> None:
    """Publish one message per already-rendered row to a stream's topic.

    For producers whose row is a column-to-value mapping rather than a
    model, such as a row read back from ClickHouse and re-published with
    a bumped version. Each row is sent as-is, so its keys must be the
    table's column names.

    Args:
        stream: The name of the stream to publish to
        topic: The name of the topic within that stream
        rows: The rows to publish, one message each
        headers: Iggy ``user_headers`` set on every message

    Raises:
        ValueError: If rows is empty
        PublishError: If the send fails
    """
    await client.Iggy.get_instance().publish_rows(
        stream, topic, rows, headers=headers
    )
