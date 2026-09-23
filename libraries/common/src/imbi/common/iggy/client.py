"""
Abstracted interface for publishing to Apache Iggy

This module provides a singleton client for asynchronous interaction with
an Apache Iggy server. It handles connection management, stream and topic
provisioning, and message publishing with proper error handling.

Example usage:
    await iggy.publish('events', 'gateway', [record])
"""

import asyncio
import contextlib
import logging
import typing
import urllib.parse

import orjson
import pydantic
from apache_iggy import IggyClient, SendMessage

from imbi.common import clickhouse, settings

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None  # type: ignore[assignment]

LOGGER = logging.getLogger(__name__)

#: Partitions created for every topic. One partition keeps the ClickHouse
#: sink's per-partition ordering trivially total, which is all the sink
#: needs -- it flushes a batch as a single insert.
PARTITIONS_COUNT = 1

#: Partition messages are published to. The Python SDK's
#: ``send_messages`` only exposes the ``PartitionId`` partitioning kind
#: -- it wraps the ``partitioning`` argument in
#: ``Partitioning::partition_id()``, so balanced partitioning is not
#: reachable from Python at this version. Partitions are numbered from
#: 0, and any other value is rejected with ``Resource with key: was not
#: found``; with ``PARTITIONS_COUNT`` at 1, publishing to partition 0 is
#: equivalent to the balanced partitioning the ADR describes.
PARTITION_ID = 0


def connection_string(url: pydantic.AnyUrl) -> str:
    """Build the SDK connection string for ``url``.

    pydantic percent-encodes characters such as ``=``, ``+`` and ``/`` in
    the userinfo when it serializes a URL, and the SDK's
    ``from_connection_string`` splits on ``@`` and ``:`` without decoding.
    A base64 password therefore reaches the server encoded and is
    rejected, so the userinfo is decoded here.

    Because the SDK does not decode, a decoded username or password that
    itself contains ``@`` or ``:`` cannot be expressed in its connection
    string, so ``ValueError`` is raised rather than sending misparsed
    credentials.
    """
    userinfo = ''
    if url.username is not None:
        username = urllib.parse.unquote(url.username)
        password = (
            urllib.parse.unquote(url.password)
            if url.password is not None
            else None
        )
        for value in (username, password):
            if value is not None and ('@' in value or ':' in value):
                raise ValueError(
                    'Iggy username and password must not contain "@" or ":"'
                )
        userinfo = username
        if password is not None:
            userinfo += f':{password}'
        userinfo += '@'
    query = f'?{url.query}' if url.query else ''
    return f'{url.scheme}://{userinfo}{url.host}:{url.port}{query}'


class PublishError(Exception):
    """Base class for errors raised by the Iggy client."""


#: Lowercased fragments of the Iggy errors that mean the connection is
#: gone rather than the request refused. The SDK reconnects some of its
#: own transports but surfaces these to the caller with the client left
#: unusable, and it exposes no way to reconnect one, so a client that
#: reports any of them is discarded instead of reused.
_CONNECTION_LOST = (
    'cannot establish connection',
    'connection closed',
    'disconnected',
    'stale client',
    'tcp error',
)


@contextlib.contextmanager
def _translate_errors(
    operation: str, owner: Iggy | None = None
) -> typing.Iterator[None]:
    """Translate Iggy SDK errors into `PublishError`.

    Logs the failure, reports it to Sentry when `sentry_sdk` is
    installed, and re-raises as `PublishError` with a clear message. The
    SDK signals every server-side and transport failure as a plain
    `RuntimeError`.

    When `owner` is given and the error says the connection is gone, the
    owner's cached client is discarded so the next call builds a new
    one. Without that a producer never recovers from an Iggy restart:
    the cached client keeps raising and only a process restart clears
    it. Errors that leave the connection intact, such as a refused
    payload, keep the client.
    """
    try:
        yield
    except RuntimeError as err:
        LOGGER.error('Error during iggy %s: %s', operation, err)
        if sentry_sdk is not None:
            sentry_sdk.capture_exception(err)
        if owner is not None and _connection_lost(err):
            LOGGER.warning(
                'Discarding the Iggy client after %s: %s', operation, err
            )
            owner.discard()
        raise PublishError(f'Iggy {operation} failed: {err}') from err


def _connection_lost(err: RuntimeError) -> bool:
    """Whether `err` means the client's connection is unusable."""
    message = str(err).lower()
    return any(fragment in message for fragment in _CONNECTION_LOST)


class Iggy:
    _instance: typing.ClassVar[Iggy | None] = None

    def __init__(self) -> None:
        self._iggy: IggyClient | None = None
        self._lock = asyncio.Lock()
        self._settings = settings.Iggy()
        self._provisioned: set[tuple[str, str]] = set()

    @classmethod
    def get_instance(cls) -> Iggy:
        """Get an instance of the Iggy client."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def initialize(self) -> bool:
        """Create a client, test the connection, and provision `TOPICS`.

        Provisioning happens here rather than on first publish because
        the ClickHouse sink exits at startup when a topic it is
        configured for does not exist. Bringing any Imbi service up is
        therefore what makes the sink startable.

        Returns False when the connection could not be made, and raises
        `PublishError` when the connection worked but provisioning did
        not; both fail a service's startup.
        """
        LOGGER.debug('Starting Iggy')
        async with self._lock:
            if self._iggy is None:
                self._iggy = await self._connect()

        if self._iggy is None:
            return False

        # Imported here because `imbi.common.iggy` imports this module.
        from imbi.common import iggy

        for stream, topics in iggy.TOPICS.items():
            for topic in topics:
                await self.ensure_topic(stream, topic)
        return True

    async def aclose(self) -> None:
        """Discard the client and everything provisioned through it.

        The SDK exposes no close or disconnect method, so dropping the
        reference is the whole of it. The provisioning cache goes with
        it: a later client re-checks what exists rather than trusting
        what a previous one saw.
        """
        async with self._lock:
            self.discard()

    def discard(self) -> None:
        """Drop the cached client so the next call reconnects.

        Synchronous, and deliberately not holding `_lock`: it runs from
        the error handler in `_translate_errors`, which sits between the
        failed await and the raise with nothing to await on. Racing a
        concurrent `initialize` costs at most one extra reconnect, never
        a client that outlives its connection.
        """
        self._iggy = None
        self._provisioned.clear()

    async def ensure_topic(self, stream: str, topic: str) -> None:
        """Create the stream and topic when they do not exist yet.

        Cached per process, so the round trips happen once. Two workers
        racing on the same pair both succeed: the loser of the race is
        told the stream or topic already exists, which is the outcome it
        asked for.
        """
        client = await self._require_client()
        if (stream, topic) in self._provisioned:
            return
        with _translate_errors(f'provisioning {stream}/{topic}', self):
            if await client.get_stream(stream) is None:
                LOGGER.debug('Creating Iggy stream %s', stream)
                await _tolerate_exists(client.create_stream(stream))
            if await client.get_topic(stream, topic) is None:
                LOGGER.debug('Creating Iggy topic %s/%s', stream, topic)
                await _tolerate_exists(
                    client.create_topic(
                        stream, topic, partitions_count=PARTITIONS_COUNT
                    )
                )
        self._provisioned.add((stream, topic))

    async def ping(self) -> None:
        """Round-trip a ping to the server to prove the connection works."""
        client = await self._require_client()
        with _translate_errors('ping', self):
            await client.ping()

    async def stored_bytes(self) -> int:
        """Total bytes Iggy holds across every stream in `TOPICS`.

        One `get_topics` call per stream, all in flight together: the
        dashboard probe that reads this runs under a short timeout that
        a serial round trip per stream would not fit. The streams all
        exist by the time anything asks, because `initialize` provisions
        them at startup.

        A call that fails or is cancelled takes its siblings with it, so
        no topic read outlives the probe that started it.
        """
        # Imported here because `imbi.common.iggy` imports this module.
        from imbi.common import iggy

        client = await self._require_client()
        tasks = [
            asyncio.ensure_future(client.get_topics(stream))
            for stream in iggy.TOPICS
        ]
        try:
            with _translate_errors('reading topic sizes', self):
                per_stream = await asyncio.gather(*tasks)
        finally:
            # `gather` abandons the siblings of a call that raises, so
            # they would outlive the probe and the next one would stack
            # another set on top. Cancelling here covers the caller's
            # timeout as well, rather than leaving that to `gather`.
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        return sum(topic.size for topics in per_stream for topic in topics)

    async def publish(
        self,
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
            models: List of Pydantic models (all must be the same type)
            columns: Restrict each payload to these keys, in this order
            headers: Iggy ``user_headers`` set on every message

        Raises:
            ValueError: If models is empty or the models are mixed types
            PublishError: If the send fails
        """
        if not models:
            raise ValueError('Data list cannot be empty')

        first_type = type(models[0])
        if not all(type(model) is first_type for model in models):
            raise ValueError(
                f'All models must be of the same type. '
                f'Expected {first_type.__name__}, but found mixed types.'
            )

        await self._send(
            stream,
            topic,
            [_payload(model, columns) for model in models],
            headers,
        )

    async def publish_rows(
        self,
        stream: str,
        topic: str,
        rows: list[dict[str, typing.Any]],
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Publish one message per already-rendered row.

        Each row is a column-to-value mapping and is sent as-is. Use
        this where the producer holds a row rather than a model, for
        example a row read back from ClickHouse and re-published with a
        bumped version.

        Args:
            stream: The name of the stream to publish to
            topic: The name of the topic within that stream
            rows: The rows to publish, one message each
            headers: Iggy ``user_headers`` set on every message

        Raises:
            ValueError: If rows is empty
            PublishError: If the send fails
        """
        if not rows:
            raise ValueError('Data list cannot be empty')
        await self._send(stream, topic, rows, headers)

    async def _send(
        self,
        stream: str,
        topic: str,
        payloads: list[dict[str, typing.Any]],
        headers: dict[str, str] | None,
    ) -> None:
        await self.ensure_topic(stream, topic)
        messages = [
            SendMessage(orjson.dumps(payload), user_headers=headers)
            for payload in payloads
        ]
        client = await self._require_client()
        LOGGER.debug(
            'Iggy PUBLISH: %s/%s (%d messages)', stream, topic, len(messages)
        )
        with _translate_errors(f'publish to {stream}/{topic}', self):
            await client.send_messages(stream, topic, PARTITION_ID, messages)

    async def _require_client(self) -> IggyClient:
        """Return the connected client, initializing it on first use."""
        if self._iggy is None:
            await self.initialize()
        if self._iggy is None:
            raise RuntimeError('Failed to initialize Iggy client')
        return self._iggy

    async def _connect(self, delay: float = 0.5) -> IggyClient | None:
        host = self._settings.url.host
        port = self._settings.url.port
        max_attempts = self._settings.max_connect_attempts
        current_delay = delay
        for attempt in range(1, max_attempts + 1):
            LOGGER.debug(
                'Connecting to Iggy at %s:%s (attempt %d)...',
                host,
                port,
                attempt,
            )
            try:
                client = IggyClient.from_connection_string(
                    connection_string(self._settings.url)
                )
                async with asyncio.timeout(self._settings.connect_timeout):
                    await client.connect()
            except (RuntimeError, TimeoutError) as err:
                if attempt >= max_attempts:
                    LOGGER.critical(
                        'Failed to Connect to Iggy after %s attempts', attempt
                    )
                    return None
                LOGGER.warning(
                    'Failed to connect to Iggy, sleeping %.2f seconds: %s',
                    current_delay,
                    err,
                )
                await asyncio.sleep(current_delay)
                current_delay *= 2
            else:
                return client
        return None


def _payload(
    model: pydantic.BaseModel, columns: list[str] | None
) -> dict[str, typing.Any]:
    """Render one row as a column-to-value mapping.

    The dumped keys are the table's column names, aliases applied and
    nested models flattened, so the sink's ``json_each_row`` insert
    lands the row exactly as the direct insert once did.
    """
    dumped = clickhouse._dump(model, by_alias=True)
    if columns is None:
        return dumped
    return {column: dumped[column] for column in columns}


async def _tolerate_exists(awaitable: typing.Awaitable[None]) -> None:
    """Await a create call, treating "already exists" as success.

    Nothing else creates these streams and topics, so the only way to
    lose the create is to a peer worker provisioning the same pair.
    """
    try:
        await awaitable
    except RuntimeError as err:
        if 'already exists' not in str(err).lower():
            raise
        LOGGER.debug('Iggy create lost a race, continuing: %s', err)
