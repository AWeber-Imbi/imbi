# Iggy

The `imbi.common.iggy` module publishes analytics rows to Apache Iggy.
The Iggy ClickHouse sink reads the streams and writes the rows to
ClickHouse. No Imbi service inserts rows into ClickHouse directly. See
[ADR 0019](../../api/adr/0019-apache-iggy-message-streaming.md).

The module needs the `databases` extra, which installs `apache-iggy`.
That package can need a Rust toolchain to build. See
[Installation](../installation.md).

## Streams and topics

`TOPICS` maps each stream name to its topics. The stream name is also
the name of the ClickHouse table that the stream goes to. A topic is the
feature that makes the rows, for example `github` or `maintenance`.

`TOPICS` is the only list of streams and topics. `imbi-api` makes the
sink configuration from it and serves that configuration to the Iggy
connectors runtime over HTTP. The runtime reads the configuration one
time, at startup. When you add a topic, restart the connectors runtime.

For the full list of streams and the tables they go to, see
[ClickHouse Client](clickhouse.md#built-in-tables).

## Lifecycle

`initialize()` connects to the server and creates every stream and topic
in `TOPICS` that does not exist. The sink stops at startup if a topic in
its configuration does not exist, so a service must create the topics
before the sink starts. `initialize()` returns `False` when it cannot
connect, and raises `PublishError` when it connects but cannot create a
topic.

The client is a singleton per process. Services call `initialize()` from
a lifespan hook and `aclose()` on shutdown:

```python
import contextlib

from imbi.common import iggy


@contextlib.asynccontextmanager
async def iggy_hook():
    if await iggy.initialize() is False:
        raise RuntimeError('Iggy initialization failed')
    async with contextlib.aclosing(iggy):
        yield
```

When an error shows that the connection is lost, the client discards
itself. The next call connects again. A service therefore recovers
after an Iggy restart without a process restart.

## Publish rows

`publish()` sends one message per Pydantic model. All models in one call
must be of the same type. The message body is the model dumped by alias,
so the keys must be the column names of the table.

```python
from imbi.common import iggy

await iggy.publish('commits', 'github', [commit_record])
```

Use `columns` to send only some keys, in a given order. Use `headers` to
set Iggy user headers on every message.

`publish_rows()` sends rows that are already dictionaries, for example a
row read back from ClickHouse and sent again with a higher version.

Both functions raise `ValueError` for an empty list, and `PublishError`
when the send fails. A publish creates the topic first if it does not
exist.

## Metrics

The client counts messages on two Prometheus counters, labelled by
`stream` and `topic`:

| Counter | Counts |
|---|---|
| `imbi_iggy_published_total` | Messages published |
| `imbi_iggy_publish_errors_total` | Messages that failed to publish |

`topic_status()` returns a `TopicStatus` for each topic: the message
count, the size, and the members of the sink consumer group. A group
with more `members` than `members_owning` has a member that reads
nothing. That is how a stuck sink shows. `stored_bytes()` returns the
total size of all the streams.

## Configuration

The client reads `settings.Iggy` from the environment only. A
`config.toml` has no `[iggy]` section.

| Variable | Default | Description |
|---|---|---|
| `IGGY_URL` | `iggy+tcp://iggy:iggy@localhost:8090` | Server URL with the user name and password |
| `IGGY_CONNECT_TIMEOUT` | `10.0` | Connection timeout, in seconds |
| `IGGY_MAX_CONNECT_ATTEMPTS` | `10` | Connection attempts before `initialize()` returns `False` |

The user name and password must not contain `@` or `:`. The SDK cannot
parse these characters.

## API Reference

::: imbi.common.iggy.TOPICS

::: imbi.common.iggy.initialize

::: imbi.common.iggy.aclose

::: imbi.common.iggy.publish

::: imbi.common.iggy.publish_rows

::: imbi.common.iggy.ensure_topic

::: imbi.common.iggy.ping

::: imbi.common.iggy.topic_status

::: imbi.common.iggy.stored_bytes

::: imbi.common.iggy.TopicStatus

::: imbi.common.iggy.PublishError
