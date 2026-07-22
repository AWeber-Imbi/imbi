"""Valkey-backed run state for global maintenance operations.

A maintenance run distributes work across every API instance through a
Valkey SET of pending project ids: :func:`start_run` seeds the set, each
instance's worker :func:`checkout`\\ s (``SPOP``) ids and records
per-project outcomes on a shared run hash, and :func:`maybe_finalize`
completes the run once the set is drained and nothing is in flight.
There is no delivery guarantee: a hard-killed instance loses the id it
had checked out and the run surfaces as ``abandoned`` once the lock's
TTL lapses -- acceptable for an idempotent admin tool.

Keys (all under ``imbi:maintenance:{slug}:``):

- ``lock`` -- run id via ``SET NX EX``; existence means "running".
- ``pending`` -- SET of project ids awaiting execution.
- ``run`` -- HASH of run metadata and outcome counters.
- ``failures`` -- HASH of ``project_id -> error`` for failed items.
"""

from __future__ import annotations

import datetime
import inspect
import typing
import uuid
from collections import abc

import pydantic
from valkey import asyncio as valkey

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
                'in_flight': 0,
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


async def checkout(client: valkey.Valkey, slug: str) -> str | None:
    """Pop one pending project id, marking it in flight."""
    popped = await _resolve(
        client.spop(  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
            _key(slug, 'pending')
        )
    )
    if popped is None:
        return None
    await _resolve(client.hincrby(_key(slug, 'run'), 'in_flight', 1))
    return _decode(popped)


async def record_outcome(
    client: valkey.Valkey,
    slug: str,
    project_id: str,
    outcome: Outcome,
    error: str = '',
) -> None:
    """Record a checked-out project's outcome on the run hash."""
    record_detail = False
    if outcome == 'failed' and error:
        details = await _resolve(client.hlen(_key(slug, 'failures')))
        record_detail = _opt_int(details) < MAX_FAILURE_DETAILS
    async with client.pipeline(transaction=False) as pipe:
        pipe.hincrby(  # pyright: ignore[reportUnknownMemberType]
            _key(slug, 'run'), 'in_flight', -1
        )
        pipe.hincrby(  # pyright: ignore[reportUnknownMemberType]
            _key(slug, 'run'), outcome, 1
        )
        if record_detail:
            pipe.hset(  # pyright: ignore[reportUnknownMemberType]
                _key(slug, 'failures'), project_id, error[:MAX_ERROR_LEN]
            )
        await pipe.execute()  # pyright: ignore[reportUnknownMemberType]


async def requeue(client: valkey.Valkey, slug: str, project_id: str) -> None:
    """Return a checked-out id to the pending set (rate limit/shutdown)."""
    async with client.pipeline(transaction=False) as pipe:
        pipe.sadd(  # pyright: ignore[reportUnknownMemberType]
            _key(slug, 'pending'), project_id
        )
        pipe.hincrby(  # pyright: ignore[reportUnknownMemberType]
            _key(slug, 'run'), 'in_flight', -1
        )
        await pipe.execute()  # pyright: ignore[reportUnknownMemberType]


async def maybe_finalize(client: valkey.Valkey, slug: str) -> bool:
    """Complete the run if the set is drained and nothing is in flight.

    Safe to call from any instance after every outcome; the benign race
    where two instances both pass the check is idempotent (both write
    ``state=completed``).
    """
    async with client.pipeline(transaction=False) as pipe:
        pipe.scard(  # pyright: ignore[reportUnknownMemberType]
            _key(slug, 'pending')
        )
        pipe.hget(  # pyright: ignore[reportUnknownMemberType]
            _key(slug, 'run'), 'in_flight'
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
        await pipe.execute()  # pyright: ignore[reportUnknownMemberType]


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
        results = typing.cast(
            'list[object]',
            await pipe.execute(),  # pyright: ignore[reportUnknownMemberType]
        )
    locked, raw_run, pending = results
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
        in_flight=_opt_int(run.get('in_flight')),
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
