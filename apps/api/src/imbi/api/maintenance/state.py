"""Valkey-backed run state for global maintenance operations.

A maintenance run distributes work across every API instance through a
Valkey SET of pending project ids: :func:`start_run` seeds the set, each
instance's worker :func:`checkout`\\ s ids onto a leased processing
hash and records per-project outcomes on a shared run hash, and
:func:`maybe_finalize` completes the run once both are empty. An id
whose lease is older than :data:`LEASE_SECONDS` -- its instance was
hard-killed -- goes back on the pending set through :func:`reclaim`, so
the cost of a lost instance is one retry. Items are idempotent, so a
retry of a half-finished item is safe.

Keys (all under ``imbi:maintenance:{slug}:``):

- ``lock`` -- run id via ``SET NX EX``; existence means "running".
- ``pending`` -- SET of project ids awaiting execution.
- ``processing`` -- HASH of ``project_id -> claimed_at`` (epoch seconds)
  for checked-out ids; its size is the run's ``in_flight``. The
  ``claimed_at`` value is also the claim token: only the holder of the
  current claim can record an outcome for the id or requeue it.
- ``run`` -- HASH of run metadata and outcome counters.
- ``failures`` -- HASH of ``project_id -> error`` for failed items.
"""

from __future__ import annotations

import datetime
import inspect
import logging
import time
import typing
import uuid
from collections import abc

import pydantic
from valkey import asyncio as valkey

from imbi.api.maintenance import log

LOGGER = logging.getLogger(__name__)

KEY_PREFIX = 'imbi:maintenance'
#: Backstop for a run whose instances all died mid-flight; a healthy run
#: deletes the lock at finalize.
LOCK_TTL_SECONDS = 43_200
PENDING_TTL_SECONDS = 86_400
#: How long the last run's result stays visible in the registry.
RESULT_TTL_SECONDS = 604_800
SADD_CHUNK = 1_000
MAX_ERROR_LEN = 500
#: Stop recording per-project failure detail past this many entries;
#: the ``failed`` counter keeps counting.
MAX_FAILURE_DETAILS = 500
#: A checked-out id older than this goes back on the pending set. Longer
#: than any single item should take; an item that runs past it can run
#: twice, which idempotency makes safe.
LEASE_SECONDS = 900

# Lua keeps each move between keys atomic, so a hard kill between two
# commands cannot leave an id in neither place.
_CHECKOUT = """
local id = redis.call('SPOP', KEYS[1])
if not id then return false end
redis.call('HSET', KEYS[2], id, ARGV[1])
redis.call('EXPIRE', KEYS[2], ARGV[2])
return id
"""
# Counts the outcome only while this claim still holds the lease; once
# reclaim has handed the id back, the retry's outcome is the one that
# counts, and a former holder cannot remove its replacement's lease.
_RECORD_OUTCOME = """
if redis.call('HGET', KEYS[2], ARGV[1]) ~= ARGV[5] then return 0 end
redis.call('HDEL', KEYS[2], ARGV[1])
redis.call('HINCRBY', KEYS[1], ARGV[2], 1)
if ARGV[3] ~= '' and redis.call('HLEN', KEYS[3]) < tonumber(ARGV[4]) then
  redis.call('HSET', KEYS[3], ARGV[1], ARGV[3])
end
return 1
"""
# Same claim check: a requeue after an outcome that committed (but whose
# reply was lost) or after a reclaim does nothing.
_REQUEUE = """
if redis.call('HGET', KEYS[2], ARGV[1]) ~= ARGV[2] then return 0 end
redis.call('HDEL', KEYS[2], ARGV[1])
redis.call('SADD', KEYS[1], ARGV[1])
return 1
"""
_RECLAIM = """
local entries = redis.call('HGETALL', KEYS[1])
local count = 0
for i = 1, #entries, 2 do
  if tonumber(entries[i + 1]) < tonumber(ARGV[1]) then
    redis.call('HDEL', KEYS[1], entries[i])
    redis.call('SADD', KEYS[2], entries[i])
    count = count + 1
  end
end
if count > 0 then redis.call('EXPIRE', KEYS[2], ARGV[2]) end
return count
"""

RunState = typing.Literal[
    'idle', 'running', 'completed', 'cancelled', 'abandoned'
]
Outcome = typing.Literal['succeeded', 'failed', 'skipped']


class RunStatus(pydantic.BaseModel):
    """Point-in-time view of an operation's current or last run."""

    state: RunState = 'idle'
    run_id: str | None = None
    total: int = 0
    remaining: int = 0
    in_flight: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    started_at: datetime.datetime | None = None
    started_by: str | None = None
    completed_at: datetime.datetime | None = None


def _key(slug: str, part: str) -> str:
    return f'{KEY_PREFIX}:{slug}:{part}'


async def _resolve(value: object) -> object:
    """Resolve valkey-py's ``Awaitable[T] | T`` command return typing."""
    if inspect.isawaitable(value):
        return await value
    return value


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _decode(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def _opt_int(value: object) -> int:
    try:
        return int(_decode(value)) if value is not None else 0
    except ValueError:
        return 0


def _opt_datetime(value: object) -> datetime.datetime | None:
    if value is None:
        return None
    try:
        return datetime.datetime.fromisoformat(_decode(value))
    except ValueError:
        return None


async def start_run(
    client: valkey.Valkey,
    slug: str,
    project_ids: abc.Iterable[str],
    started_by: str,
) -> RunStatus | None:
    """Begin a run: acquire the lock and seed the pending set.

    Returns ``None`` when a run is already in progress (lock held).
    Leftover state from a previous run is cleared before seeding.
    """
    run_id = uuid.uuid4().hex
    acquired = await client.set(
        _key(slug, 'lock'), run_id, nx=True, ex=LOCK_TTL_SECONDS
    )
    if not acquired:
        return None
    ids = list(project_ids)
    started_at = _now_iso()
    async with client.pipeline(transaction=False) as pipe:
        pipe.delete(  # pyright: ignore[reportUnknownMemberType]
            _key(slug, 'pending'),
            _key(slug, 'processing'),
            _key(slug, 'failures'),
            _key(slug, 'run'),
        )
        for offset in range(0, len(ids), SADD_CHUNK):
            pipe.sadd(  # pyright: ignore[reportUnknownMemberType]
                _key(slug, 'pending'), *ids[offset : offset + SADD_CHUNK]
            )
        pipe.hset(  # pyright: ignore[reportUnknownMemberType]
            _key(slug, 'run'),
            mapping={
                'run_id': run_id,
                'total': len(ids),
                'started_at': started_at,
                'started_by': started_by,
                'state': 'running',
                'succeeded': 0,
                'failed': 0,
                'skipped': 0,
            },
        )
        pipe.expire(  # pyright: ignore[reportUnknownMemberType]
            _key(slug, 'pending'), PENDING_TTL_SECONDS
        )
        await pipe.execute()  # pyright: ignore[reportUnknownMemberType]
    if not ids:
        await maybe_finalize(client, slug)
        return await read_status(client, slug)
    return RunStatus(
        state='running',
        run_id=run_id,
        total=len(ids),
        remaining=len(ids),
        started_at=datetime.datetime.fromisoformat(started_at),
        started_by=started_by,
    )


async def has_active_run(client: valkey.Valkey, slug: str) -> bool:
    """Whether the run lock is currently held."""
    return bool(await client.exists(_key(slug, 'lock')))


async def read_run_meta(client: valkey.Valkey, slug: str) -> tuple[str, str]:
    """The current run's ``(run_id, started_by)``, empty when idle.

    The activity log stamps both on every row it writes, and the worker
    holds neither -- a run is started by whichever instance served the
    POST, not by the one that picks the work up.
    """
    raw = typing.cast(
        'list[object]',
        await _resolve(
            client.hmget(  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
                _key(slug, 'run'), ['run_id', 'started_by']
            )
        ),
    )
    run_id, started_by = raw[0], raw[1]
    return (
        _decode(run_id) if run_id is not None else '',
        _decode(started_by) if started_by is not None else '',
    )


async def checkout(client: valkey.Valkey, slug: str) -> tuple[str, str] | None:
    """Move one pending project id onto the processing hash.

    Returns ``(project_id, token)``; pass the token to
    :func:`record_outcome` or :func:`requeue`.
    """
    token = str(time.time())
    popped = await _resolve(
        client.eval(  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
            _CHECKOUT,
            2,
            _key(slug, 'pending'),
            _key(slug, 'processing'),
            token,
            str(PENDING_TTL_SECONDS),
        )
    )
    return None if popped is None else (_decode(popped), token)


async def record_outcome(
    client: valkey.Valkey,
    slug: str,
    project_id: str,
    token: str,
    outcome: Outcome,
    error: str = '',
) -> bool:
    """Record a checked-out project's outcome on the run hash.

    Returns ``False`` when *token* no longer holds the lease (it was
    reclaimed): the outcome is not counted, because the retry records
    its own.
    """
    detail = error[:MAX_ERROR_LEN] if outcome == 'failed' else ''
    recorded = await _resolve(
        client.eval(  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
            _RECORD_OUTCOME,
            3,
            _key(slug, 'run'),
            _key(slug, 'processing'),
            _key(slug, 'failures'),
            project_id,
            outcome,
            detail,
            str(MAX_FAILURE_DETAILS),
            token,
        )
    )
    return bool(_opt_int(recorded))


async def requeue(
    client: valkey.Valkey, slug: str, project_id: str, token: str
) -> bool:
    """Return a checked-out id to the pending set (rate limit/shutdown).

    Returns ``False`` when *token* no longer holds the lease: the outcome
    was already recorded, or the lease was reclaimed.
    """
    requeued = await _resolve(
        client.eval(  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
            _REQUEUE,
            2,
            _key(slug, 'pending'),
            _key(slug, 'processing'),
            project_id,
            token,
        )
    )
    return bool(_opt_int(requeued))


async def reclaim(client: valkey.Valkey, slug: str) -> int:
    """Return ids whose lease expired to the pending set.

    An expired lease means the instance that held the id died without
    recording an outcome or requeueing it.
    """
    reclaimed = await _resolve(
        client.eval(  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
            _RECLAIM,
            2,
            _key(slug, 'processing'),
            _key(slug, 'pending'),
            str(time.time() - LEASE_SECONDS),
            str(PENDING_TTL_SECONDS),
        )
    )
    return _opt_int(reclaimed)


async def maybe_finalize(client: valkey.Valkey, slug: str) -> bool:
    """Complete the run if the set is drained and nothing is in flight.

    Safe to call from any instance after every outcome; the benign race
    where two instances both pass the check is idempotent (both write
    ``state=completed``). The reads run in one MULTI/EXEC so a
    concurrent :func:`reclaim` cannot move an id between them.
    """
    async with client.pipeline(transaction=True) as pipe:
        pipe.scard(  # pyright: ignore[reportUnknownMemberType]
            _key(slug, 'pending')
        )
        pipe.hlen(  # pyright: ignore[reportUnknownMemberType]
            _key(slug, 'processing')
        )
        pipe.hget(  # pyright: ignore[reportUnknownMemberType]
            _key(slug, 'run'), 'state'
        )
        results = typing.cast(
            'list[object]',
            await pipe.execute(),  # pyright: ignore[reportUnknownMemberType]
        )
    pending, in_flight, run_state = results
    if int(typing.cast('int', pending)) > 0:
        return False
    if _opt_int(in_flight) > 0:
        return False
    if run_state is None or _decode(run_state) != 'running':
        return False
    await _finish(client, slug, 'completed')
    return True


async def cancel_run(client: valkey.Valkey, slug: str) -> bool:
    """Cancel the in-progress run; returns ``False`` when none is."""
    if not await has_active_run(client, slug):
        return False
    run_state = await _resolve(client.hget(_key(slug, 'run'), 'state'))
    if run_state is None or _decode(run_state) != 'running':
        return False
    await client.delete(_key(slug, 'pending'))
    await _finish(client, slug, 'cancelled')
    return True


async def _finish(
    client: valkey.Valkey,
    slug: str,
    state: typing.Literal['completed', 'cancelled'],
) -> None:
    async with client.pipeline(transaction=False) as pipe:
        pipe.hset(  # pyright: ignore[reportUnknownMemberType]
            _key(slug, 'run'),
            mapping={'state': state, 'completed_at': _now_iso()},
        )
        pipe.delete(  # pyright: ignore[reportUnknownMemberType]
            _key(slug, 'lock')
        )
        pipe.expire(  # pyright: ignore[reportUnknownMemberType]
            _key(slug, 'run'), RESULT_TTL_SECONDS
        )
        pipe.expire(  # pyright: ignore[reportUnknownMemberType]
            _key(slug, 'failures'), RESULT_TTL_SECONDS
        )
        # Kept, not deleted: a cancelled run's in-flight items still
        # record their outcomes against it.
        pipe.expire(  # pyright: ignore[reportUnknownMemberType]
            _key(slug, 'processing'), RESULT_TTL_SECONDS
        )
        results = typing.cast(
            'list[object]',
            await pipe.execute(),  # pyright: ignore[reportUnknownMemberType]
        )
    # Only the instance whose DEL actually removed the lock writes the
    # run row. The benign race above -- two instances both passing
    # ``maybe_finalize``'s drained check -- is idempotent in Valkey,
    # where both write the same hash, but the log is a plain MergeTree:
    # two calls would leave two run rows for one run, and anything
    # summing their counters would double them.
    if not _opt_int(results[1] if len(results) > 1 else 0):
        return
    # The durable record of the run, written after the Valkey state so a
    # ClickHouse problem cannot leave a run un-finished. The counters it
    # carries are the authoritative ones: an activity log short of them
    # is a logging gap, and comparing the two is how that becomes
    # visible. An ``abandoned`` run reaches neither branch and so has no
    # terminal row at all, which is what identifies it later.
    #
    # A cancelled run is the one case where the counters legitimately
    # fall short of the attempt rows: ``cancel_run`` finishes while
    # items are still in flight, and those record their outcomes after
    # this row is written.
    #
    # ``record_run`` never raises, but this read does, and by here the
    # terminal state is written and the lock is gone. Letting a Valkey
    # blip out would report a failure for a cancellation that already
    # applied.
    try:
        status = await read_status(client, slug)
    except Exception:
        LOGGER.exception(
            'maintenance log dropped the run row for %s: '
            'could not read the final counters',
            slug,
        )
        return
    await log.record_run(
        slug,
        status.run_id or '',
        state,
        status.started_by or '',
        total=status.total,
        succeeded=status.succeeded,
        failed=status.failed,
        skipped=status.skipped,
        remaining=status.remaining,
        in_flight=status.in_flight,
    )


async def read_status(client: valkey.Valkey, slug: str) -> RunStatus:
    """Read the operation's current (or last) run state.

    A run hash claiming ``running`` with no lock present means every
    worker died holding work -- reported as the derived ``abandoned``
    state rather than stored.
    """
    async with client.pipeline(transaction=False) as pipe:
        pipe.exists(  # pyright: ignore[reportUnknownMemberType]
            _key(slug, 'lock')
        )
        pipe.hgetall(  # pyright: ignore[reportUnknownMemberType]
            _key(slug, 'run')
        )
        pipe.scard(  # pyright: ignore[reportUnknownMemberType]
            _key(slug, 'pending')
        )
        pipe.hlen(  # pyright: ignore[reportUnknownMemberType]
            _key(slug, 'processing')
        )
        results = typing.cast(
            'list[object]',
            await pipe.execute(),  # pyright: ignore[reportUnknownMemberType]
        )
    locked, raw_run, pending, processing = results
    run = {
        _decode(k): v
        for k, v in typing.cast('dict[object, object]', raw_run).items()
    }
    if not run:
        return RunStatus()
    raw_state = _decode(run.get('state', 'idle'))
    state: RunState = 'idle'
    if raw_state in ('running', 'completed', 'cancelled'):
        state = typing.cast('RunState', raw_state)
    if state == 'running' and not locked:
        state = 'abandoned'
    run_id = run.get('run_id')
    started_by = run.get('started_by')
    return RunStatus(
        state=state,
        run_id=_decode(run_id) if run_id is not None else None,
        total=_opt_int(run.get('total')),
        remaining=int(typing.cast('int', pending)),
        in_flight=_opt_int(processing),
        succeeded=_opt_int(run.get('succeeded')),
        failed=_opt_int(run.get('failed')),
        skipped=_opt_int(run.get('skipped')),
        started_at=_opt_datetime(run.get('started_at')),
        started_by=_decode(started_by) if started_by is not None else None,
        completed_at=_opt_datetime(run.get('completed_at')),
    )


async def read_failures(client: valkey.Valkey, slug: str) -> dict[str, str]:
    """Per-project failure detail for the current/last run."""
    raw = typing.cast(
        'dict[object, object]',
        await _resolve(
            client.hgetall(  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
                _key(slug, 'failures')
            )
        ),
    )
    return {_decode(k): _decode(v) for k, v in raw.items()}
