import pydantic

from . import client
from .client import PublishError

__all__ = [
    'TOPICS',
    'PublishError',
    'aclose',
    'ensure_topic',
    'initialize',
    'publish',
]

#: The streams Imbi publishes to and the topics of each, keyed by stream
#: name, which is also the ClickHouse table the stream lands in.
#:
#: This is the single source of truth for the streams and topics the
#: ClickHouse sink consumes: imbi-api serves the sink configuration
#: generated from this mapping to the Iggy connectors runtime over HTTP,
#: so a topic added here is a topic the sink drains, with no second list
#: to keep in step.
TOPICS: dict[str, tuple[str, ...]] = {'events': ('gateway',)}


async def initialize() -> bool:
    """Create a new client and test the connection."""
    return await client.Iggy.get_instance().initialize()


async def aclose() -> None:
    """Discard the Iggy client."""
    await client.Iggy.get_instance().aclose()


async def ensure_topic(stream: str, topic: str) -> None:
    """Create the stream and topic when they do not exist yet."""
    await client.Iggy.get_instance().ensure_topic(stream, topic)


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
