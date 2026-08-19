"""Release-promote watch queue (Valkey Streams).

Sibling of :mod:`imbi.api.deployment_sync.queue`, with three deliberate
differences forced by how long a release build runs:

* **No per-project debounce.**  The resync debounce is right for
  coalescable work; silently dropping a promote watch would orphan a
  build nobody is waiting on.  Jobs are made idempotent instead --
  re-running one re-polls the same run id and converges on the same
  outcome.
* **Entries are processed concurrently**, not serially.  A watch job
  lives for the length of a release build (minutes, up to
  ``service.TIMEOUT_SECONDS``).  Handling entries one at a time -- what
  the resync consumer does, correctly, for second-long jobs -- would make
  one project's build block every other project's promote behind it, and
  the ones behind could time out having never been polled.
* **Claim renewal is mandatory, not defensive.**  A job routinely
  outlives ``CLAIM_IDLE_MS`` by an order of magnitude, so without
  renewal another worker reclaims it mid-flight and double-drives the
  same promote -- two Deployments for one tag.

Dead-lettering after ``MAX_DELIVERIES`` and the global rate-limit pause
carry over from the sibling unchanged.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import socket
import time
import typing
from collections import abc

import pydantic
from valkey import asyncio as valkey

from imbi.api.release_promote.service import WatchJob, run_watch, set_status
from imbi.common import deployments, graph
from imbi.common.plugins.errors import PluginRateLimited

STREAM = 'imbi:release-promote'
GROUP = 'release-promote-workers'
CONSUMER_PREFIX = 'worker'
DLQ = 'imbi:release-promote:dlq'
MAX_DELIVERIES = 3
CLAIM_IDLE_MS = 120_000
#: How often an in-flight job renews its claim.  Must stay well under
#: ``CLAIM_IDLE_MS``; see the module docstring.
CLAIM_RENEW_SECONDS = 30
PAUSE_KEY = 'imbi:release-promote:paused-until'
PAUSE_POLL_CAP_SECONDS = 30
PAUSE_KEY_BUFFER_SECONDS = 5
#: Concurrent watch jobs one worker process will drive.  Bounds the graph
#: and remote-API load a burst of promotes can generate; excess entries
#: stay unread in the stream until a slot frees.
MAX_CONCURRENT = 8
#: Gap between main-loop iterations when the stream read didn't block.
IDLE_SLEEP_SECONDS = 0.5

LOGGER = logging.getLogger(__name__)


async def enqueue_release_promote(
    client: valkey.Valkey | None,
    job: WatchJob,
) -> bool:
    """XADD a promote-watch job.  Returns True if enqueued.

    Tolerates *client* being ``None`` (returns False) so the promote
    endpoint can tell the user the build is running but unwatched, rather
    than 500, when Valkey is down.
    """
    if client is None:
        return False
    try:
        await client.xadd(STREAM, {'job': job.model_dump_json()})
    except Exception:
        LOGGER.exception(
            'enqueue_release_promote failed for project %s tag %s',
            job.project_id,
            job.tag,
        )
        return False
    return True


async def ensure_group(client: valkey.Valkey) -> None:
    try:
        await client.xgroup_create(STREAM, GROUP, id='$', mkstream=True)
    except Exception as err:
        if 'BUSYGROUP' not in str(err):
            LOGGER.exception('xgroup_create failed')
            raise


def _decode_fields(
    raw: abc.Mapping[bytes | str, bytes | str],
) -> dict[str, str]:
    return {
        (k.decode() if isinstance(k, bytes) else k): (
            v.decode() if isinstance(v, bytes) else v
        )
        for k, v in raw.items()
    }


def _parse_job(fields: dict[str, str]) -> WatchJob | None:
    raw = fields.get('job')
    if not raw:
        return None
    try:
        return WatchJob.model_validate_json(raw)
    except (pydantic.ValidationError, json.JSONDecodeError):
        # Deliberately not the payload itself: a ``WatchJob`` carries
        # ``requested_by``, which is the promoting user's identity, and
        # this fires on every malformed message.  The exception already
        # says which field failed; the length is enough to tell a
        # truncated write from a schema mismatch.
        LOGGER.exception(
            'release-promote job payload is unusable (%d bytes)', len(raw)
        )
        return None


async def _process_message(
    db: graph.Graph,
    fields: dict[str, str],
    valkey_client: valkey.Valkey | None,
) -> None:
    job = _parse_job(fields)
    if job is None:
        # Nothing to retry toward: a payload we can't parse will never
        # become parseable.  Ack it (the caller does) and move on.
        return
    await run_watch(db, job, valkey_client=valkey_client)


async def _paused_remaining(client: valkey.Valkey) -> float:
    """Seconds left on the global rate-limit pause, ``0.0`` when clear."""
    try:
        raw = await client.get(PAUSE_KEY)
    except Exception:  # noqa: BLE001
        return 0.0
    if raw is None:
        return 0.0
    try:
        until = float(raw.decode() if isinstance(raw, bytes) else raw)
    except ValueError:
        return 0.0
    return max(0.0, until - time.time())


async def _pause_until(client: valkey.Valkey, retry_at: float) -> None:
    """Record the resume time so every worker backs off until *retry_at*."""
    ttl = max(1, int(retry_at - time.time()) + PAUSE_KEY_BUFFER_SECONDS)
    try:
        await client.set(PAUSE_KEY, str(retry_at), ex=ttl)
    except Exception:
        LOGGER.exception('failed to set release-promote pause marker')


async def _claim_stale(
    client: valkey.Valkey,
    consumer: str,
    count: int,
) -> list[tuple[bytes, abc.Mapping[bytes | str, bytes | str]]]:
    try:
        result = await client.xautoclaim(
            STREAM,
            GROUP,
            consumer,
            min_idle_time=CLAIM_IDLE_MS,
            start_id='0-0',
            count=count,
        )
    except Exception as err:  # noqa: BLE001
        LOGGER.debug('xautoclaim failed: %s', err)
        return []
    if isinstance(result, (list, tuple)) and len(result) >= 2:  # type: ignore[arg-type]
        msgs: object = result[1]  # type: ignore[index]
        if isinstance(msgs, list):
            return msgs  # type: ignore[return-value]
    return []


async def _renew_claim(
    client: valkey.Valkey,
    consumer: str,
    msg_id: bytes,
) -> None:
    """Reset *msg_id*'s idle clock while its job is still running.

    ``JUSTID`` renews without re-reading the entry or bumping the
    delivery counter, so renewal never pushes a healthy job toward the
    dead-letter threshold.  Cancelled by :func:`_run_job` on completion.
    """
    while True:
        await asyncio.sleep(CLAIM_RENEW_SECONDS)
        try:
            await client.xclaim(
                STREAM,
                GROUP,
                consumer,
                min_idle_time=0,
                message_ids=[msg_id],
                justid=True,
            )
        except Exception as err:  # noqa: BLE001
            LOGGER.debug('claim renewal failed for %s: %s', msg_id, err)


async def _maybe_dead_letter(
    client: valkey.Valkey,
    db: graph.Graph,
    msg_id: bytes,
    fields: dict[str, str],
) -> bool:
    try:
        info = await client.xpending_range(
            STREAM, GROUP, min=msg_id, max=msg_id, count=1
        )
    except Exception:  # noqa: BLE001
        return False
    if not info:
        return False
    entry: object = info[0]  # type: ignore[index]
    delivered: int | None = None
    if isinstance(entry, dict):
        raw_delivered = entry.get('times_delivered')  # type: ignore[union-attr]
        if raw_delivered is not None:
            delivered = int(raw_delivered)  # type: ignore[arg-type]
    elif isinstance(entry, (list, tuple)) and len(entry) >= 4:  # type: ignore[arg-type]
        raw_delivered = entry[3]  # type: ignore[index]
        if raw_delivered is not None:
            delivered = int(raw_delivered)  # type: ignore[arg-type]
    if delivered is not None and delivered >= MAX_DELIVERIES:
        await client.xadd(DLQ, fields)
        await client.xack(STREAM, GROUP, msg_id)
        LOGGER.warning(
            'dead-lettered release-promote msg %s after %s deliveries',
            msg_id,
            delivered,
        )
        # The promote will never be watched now, so say so on the project
        # rather than leaving the panel spinning on ``building`` forever.
        job = _parse_job(fields)
        if job is not None:
            await _mark_abandoned(db, job)
        return True
    return False


async def _mark_abandoned(db: graph.Graph, job: WatchJob) -> None:
    """Flag a dead-lettered watch so the UI stops showing ``building``.

    Whatever deployment the promote managed to open is closed out too:
    nothing is going to watch it now, so leaving it ``in_progress``
    would add to the stuck backlog this queue's own docstring warns
    about.  The ``history`` on the node keeps the trail if a late
    webhook lands afterwards.
    """
    try:
        await deployments.close_in_flight(
            db,
            project_id=job.project_id,
            release_id=job.release_id,
            env_slug=job.to_environment,
            status='failed',
            note='promote watch abandoned',
            source='promote-queue',
        )
    except Exception:
        LOGGER.exception(
            'could not close the deployment for abandoned promote of '
            'project %s tag %s',
            job.project_id,
            job.tag,
        )
    await set_status(
        db,
        job.project_id,
        status='failed',
        tag=job.tag,
        committish=job.committish,
        environment=job.to_environment,
        from_environment=job.from_environment,
        artifact_run_id=job.run_id,
        artifact_run_url=job.run_url,
        requested_by=job.requested_by,
        error=(
            'Imbi gave up watching this release build after repeated '
            'failures. Check the workflow run on the remote; the tag was '
            'not blocked, so it can still be deployed once green.'
        ),
    )


async def _run_job(
    client: valkey.Valkey,
    db: graph.Graph,
    msg_id: bytes,
    fields: dict[str, str],
    consumer: str,
    valkey_client: valkey.Valkey | None,
) -> None:
    """Drive one watch job to completion, then ack it."""
    renewer = asyncio.ensure_future(_renew_claim(client, consumer, msg_id))
    try:
        await _process_message(db, fields, valkey_client)
    except PluginRateLimited as exc:
        # Don't ack: leave the job pending so a reclaim re-drives it once
        # the limit clears, and pause every worker until then.
        await _pause_until(client, exc.retry_at)
        LOGGER.warning(
            'release-promote paused ~%.0fs (remote rate limit); job left '
            'queued',
            max(0.0, exc.retry_at - time.time()),
        )
        return
    except Exception:
        # Leave it pending for a reclaim; ``_maybe_dead_letter`` retires
        # it once the delivery count is exhausted.
        #
        # Identify the job by project and tag rather than dumping
        # ``fields``: its ``job`` entry is a serialized ``WatchJob``,
        # which carries the promoting user's identity in
        # ``requested_by``.  Those two are enough to find the run.
        job = _parse_job(fields)
        LOGGER.exception(
            'release-promote job failed for project=%s tag=%s',
            job.project_id if job else '<unparseable>',
            job.tag if job else '<unparseable>',
        )
        return
    finally:
        renewer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await renewer
    with contextlib.suppress(Exception):
        await client.xack(STREAM, GROUP, msg_id)


async def consume_release_promote(
    client: valkey.Valkey,
    db: graph.Graph,
    consumer: str | None = None,
    stop: asyncio.Event | None = None,
) -> None:
    """Run the release-promote consumer loop until *stop* is set.

    Reads only as many entries as there are free concurrency slots and
    drives each as its own task, so a long build never blocks another
    project's promote.
    """
    consumer = (
        consumer or f'{CONSUMER_PREFIX}-{socket.gethostname()}-{os.getpid()}'
    )
    await ensure_group(client)
    LOGGER.info(
        'Release-promote consumer loop running (consumer=%s)', consumer
    )
    in_flight: dict[bytes, asyncio.Task[None]] = {}

    def _spawn(
        msg_id: bytes, raw_fields: abc.Mapping[bytes | str, bytes | str]
    ) -> None:
        if msg_id in in_flight:
            return
        fields = _decode_fields(raw_fields)
        task = asyncio.ensure_future(
            _run_job(client, db, msg_id, fields, consumer or '', client)
        )
        in_flight[msg_id] = task
        task.add_done_callback(lambda _t: in_flight.pop(msg_id, None))

    try:
        while stop is None or not stop.is_set():
            paused = await _paused_remaining(client)
            if paused > 0:
                await asyncio.sleep(min(paused, PAUSE_POLL_CAP_SECONDS))
                continue
            free = MAX_CONCURRENT - len(in_flight)
            if free <= 0:
                await asyncio.sleep(IDLE_SLEEP_SECONDS)
                continue
            stale = await _claim_stale(client, consumer, free)
            for msg_id, raw_fields in stale:
                if await _maybe_dead_letter(
                    client, db, msg_id, _decode_fields(raw_fields)
                ):
                    continue
                _spawn(msg_id, raw_fields)
            free = MAX_CONCURRENT - len(in_flight)
            if free <= 0:
                await asyncio.sleep(IDLE_SLEEP_SECONDS)
                continue
            try:
                response = await client.xreadgroup(
                    GROUP,
                    consumer,
                    {STREAM: '>'},
                    count=free,
                    block=2000,
                )
            except Exception:
                LOGGER.exception('xreadgroup failed')
                await asyncio.sleep(1)
                continue
            if not response:
                continue
            for _stream, entries in typing.cast(
                'list[tuple[object, list[typing.Any]]]', response
            ):
                for msg_id, raw_fields in entries:
                    _spawn(msg_id, raw_fields)
    finally:
        for task in list(in_flight.values()):
            task.cancel()
        for task in list(in_flight.values()):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
