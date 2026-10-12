"""The workflow engine (ADR 0021, Execution).

Each worker claims one run, does one thing with it, and releases it:
starts it, closes it, marks steps ``skipped``, or makes one call of one
step. The steps of a run therefore run one at a time.

ponytail: one step at a time per run; parallel branches run in turn.
Run them at once when a workflow needs it.
"""

import asyncio
import contextlib
import datetime
import logging
import re
import typing

from psycopg import sql
from psycopg.types import json as pg_json

from imbi.common import graph, models
from imbi.common.prompts import pool as render_pool
from imbi.common.prompts import rendering
from imbi.common.workflows import graph as wf
from imbi.common.workflows import registry, runtime, walk
from imbi.workflows import executors, settings, store

LOGGER = logging.getLogger(__name__)

#: Seconds of the first retry backoff; it doubles per attempt.
RETRY_BACKOFF = 5

_WHOLE_REFERENCE = re.compile(
    r'^\{\{\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)\s*\}\}$'
)

#: The activator, only when an active member of the run's organization.
_ACTIVATOR_QUERY: typing.LiteralString = """
MATCH (u:User {{email: {email}}})-[m:MEMBER_OF]->(:Organization {{id: {org}}})
WHERE u.is_active = true
RETURN u.is_admin AS is_admin, m.role AS role
"""

#: The permissions of one role and the roles it inherits from, as in
#: ``imbi.common.auth.permissions.load_principal_permissions``.
_ROLE_PERMISSIONS_QUERY: typing.LiteralString = """
MATCH (r:Role {{slug: {role}}})
OPTIONAL MATCH (r)-[:INHERITS_FROM*1..]->(ancestor:Role)
WITH r, collect(DISTINCT ancestor) AS ancestors
UNWIND ancestors + [r] AS role
WITH DISTINCT role
OPTIONAL MATCH (role)-[:GRANTS]->(perm:Permission)
RETURN collect(DISTINCT perm.name) AS permissions
"""


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class Engine:
    def __init__(
        self,
        runs_store: store.Store,
        steps: executors.Executors,
        config: settings.Workflows,
    ) -> None:
        self.store = runs_store
        self.steps = steps
        self.config = config
        self._wake = asyncio.Event()

    def notify(self) -> None:
        """Wake idle workers early."""
        self._wake.set()

    # --- Loop ----------------------------------------------------------

    async def run_forever(self, stop: asyncio.Event) -> None:
        LOGGER.info('Workflow engine started')
        await asyncio.gather(
            *(self._worker(stop) for _ in range(self.config.workers))
        )
        LOGGER.info('Workflow engine stopped')

    async def _worker(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                worked = await self.tick()
            except Exception:
                LOGGER.exception('Workflow tick failed; continuing')
                worked = False
            if not worked:
                await self._sleep(stop)

    async def _sleep(self, stop: asyncio.Event) -> None:
        delay = self.config.poll_interval
        with contextlib.suppress(Exception):
            due = await self.store.next_due()
            if due is not None:
                delay = max(0.0, min(delay, (due - _now()).total_seconds()))
        self._wake.clear()
        waiters = [
            asyncio.create_task(stop.wait()),
            asyncio.create_task(self._wake.wait()),
        ]
        try:
            await asyncio.wait(
                waiters, timeout=delay, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for waiter in waiters:
                waiter.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)

    async def listen(self) -> None:
        """Wake on ``NOTIFY``. A hint only: the workers always poll."""
        while True:
            try:
                async with self.store.pool.connection() as conn:
                    await conn.set_autocommit(True)
                    await conn.execute(
                        sql.SQL('LISTEN {}').format(
                            sql.Identifier(runtime.NOTIFY_CHANNEL)
                        )
                    )
                    async for _ in conn.notifies():
                        self.notify()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 -- polling covers the gap
                LOGGER.warning('Run listener stopped; retrying', exc_info=True)
            await asyncio.sleep(self.config.poll_interval)

    async def tick(self) -> bool:
        """Claim one run and do one thing with it. ``False``: no run."""
        run = await self.store.claim(
            datetime.timedelta(seconds=self.config.lease_seconds)
        )
        if run is None:
            return False
        due_at: datetime.datetime | None = _now()
        try:
            due_at = await self._process(run)
        except store.LeaseLost:
            LOGGER.warning('Lost the lease of run %s', run['id'])
            return True
        except Exception:
            LOGGER.exception('Run %s failed in the engine', run['id'])
            due_at = _now() + datetime.timedelta(seconds=RETRY_BACKOFF)
        await self.store.release(run['id'], due_at)
        return True

    # --- One pass ------------------------------------------------------

    async def _process(  # noqa: PLR0911
        self, run: store.Row
    ) -> datetime.datetime | None:
        """Do the next thing for ``run``. Return when it is due again."""
        steps, version = await self.store.load(run)
        wf_graph = wf.Graph.model_validate(version['graph'])
        wf_settings = wf.Settings.model_validate(version['settings'])
        if run['cancel_requested']:
            await self._close(run, steps, 'cancelled')
            return None
        if run['status'] == 'queued':
            if not await self._activator_allowed(run, wf_graph):
                return None
            await self._start(run, wf_graph)
            return _now()
        deadline = run['created_at'] + datetime.timedelta(
            seconds=wf_settings.max_run_time_seconds
        )
        if _now() > deadline:
            await self._close(run, steps, 'timed_out')
            return None
        # A failure with no Failed port fails the run at once: the steps
        # that did not start are cancelled, not run or skipped.
        failed = [
            s
            for s in steps.values()
            if s['status'] == 'failed' and s['port'] is None
        ]
        if failed:
            await self._close(run, steps, 'failed', failed[0]['error'])
            if wf_settings.on_failure == 'notify_owner_team':
                await self._notify_owner_team(run, version['slug'])
            return None
        status = {n: s['status'] for n, s in steps.items()}
        ports = {n: s['port'] for n, s in steps.items()}
        running = [n for n, s in status.items() if s == 'running']
        if running:
            due = await self._call(
                run, wf_graph, steps, running[0], version['slug']
            )
            # A wait or a backoff past the deadline wakes at the deadline,
            # so the run times out on time.
            return min(due, deadline) if due else due
        ready, skipped = walk.advance(wf_graph, status, ports)
        if skipped:
            async with self.store.write(run['id']) as conn:
                for node_id in skipped:
                    await self._finish(
                        conn, run, steps[node_id], 'skipped', None, None
                    )
            return _now()
        if not ready:
            await self._close(run, steps, 'succeeded')
            return None
        node_id = ready[0]
        node = next(n for n in wf_graph.nodes if n.id == node_id)
        try:
            params = await _render(node.params, steps, run['payload'])
        except rendering.RenderError as e:
            LOGGER.info('Run %s: %s: %s', run['id'], node.key, e)
            async with self.store.write(run['id']) as conn:
                await self._fail(conn, run, steps[node_id], 'invalid_params')
            return _now()
        async with self.store.write(run['id']) as conn:
            await store.update(
                conn,
                'step_runs',
                {'run_id': run['id'], 'node_id': node_id},
                status='running',
                attempt=1,
                input=params,
                started_at=_now(),
            )
            await _step_event(conn, run['id'], node_id, 'step.started')
        return _now()

    async def _activator_allowed(
        self, run: store.Row, wf_graph: wf.Graph
    ) -> bool:
        """Check the activator again. Fail the run and pause if not.

        The person who activated the version must still be an active
        member of the run's organization and hold, through that
        membership, every permission that its steps need (ADR 0021).
        An admin passes only as a member too.
        """
        if await self._activator_holds(run, wf_graph):
            return True
        async with self.store.write(run['id']) as conn:
            await conn.execute(
                "UPDATE workflows.workflows SET status = 'paused',"
                ' updated_at = NOW() WHERE id = %s',
                (run['workflow_id'],),
            )
            await self._close_in(
                conn, run, {}, 'failed', 'activator_lacks_permission'
            )
        return False

    async def _activator_holds(
        self, run: store.Row, wf_graph: wf.Graph
    ) -> bool:
        found = await self.steps.db.execute(
            _ACTIVATOR_QUERY,
            {'email': run['activated_by'], 'org': run['organization_id']},
            ['is_admin', 'role'],
        )
        if not found:
            return False
        if graph.parse_agtype(found[0]['is_admin']) is True:
            return True
        required: set[str] = set()
        for node in wf_graph.nodes:
            step = registry.STEP_TYPES[node.type]
            required |= step.required_permissions(node.params)
        if not required:
            return True
        records = await self.steps.db.execute(
            _ROLE_PERMISSIONS_QUERY,
            {'role': graph.parse_agtype(found[0]['role'])},
            ['permissions'],
        )
        raw: typing.Any = (
            graph.parse_agtype(records[0]['permissions']) if records else []
        )
        held = (
            {str(p) for p in typing.cast('list[typing.Any]', raw)}  # type: ignore[redundant-cast]
            if isinstance(raw, list)
            else set[str]()
        )
        return required <= held

    async def _start(self, run: store.Row, wf_graph: wf.Graph) -> None:
        """Write a step row per node and mark the run ``running``."""
        async with self.store.write(run['id']) as conn:
            for node in wf_graph.nodes:
                started = node.id == run['trigger_node_id']
                trigger = registry.STEP_TYPES[node.type].trigger
                await conn.execute(
                    'INSERT INTO workflow_runtime.step_runs (run_id,'
                    ' node_id, node_key, node_type, title, status, port,'
                    ' output, started_at, finished_at)'
                    ' VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)'
                    ' ON CONFLICT DO NOTHING',
                    (
                        run['id'],
                        node.id,
                        node.key,
                        node.type,
                        node.title,
                        'succeeded'
                        if started
                        else ('skipped' if trigger else 'pending'),
                        0 if started else None,
                        pg_json.Jsonb(run['payload']) if started else None,
                        _now() if started else None,
                        _now() if trigger else None,
                    ),
                )
            await store.update(
                conn,
                'runs',
                {'id': run['id']},
                status='running',
                started_at=_now(),
            )
            await runtime.append_event(conn, run['id'], 'run.started', {})
            # Trigger steps get their status here, not from a call, so
            # history has an event for each of them too.
            for node in wf_graph.nodes:
                if registry.STEP_TYPES[node.type].trigger:
                    started = node.id == run['trigger_node_id']
                    await _step_event(
                        conn,
                        run['id'],
                        node.id,
                        'step.succeeded' if started else 'step.skipped',
                    )

    # --- Calls ---------------------------------------------------------

    async def _call(  # noqa: PLR0911
        self,
        run: store.Row,
        wf_graph: wf.Graph,
        steps: dict[str, store.Row],
        node_id: str,
        slug: str,
    ) -> datetime.datetime | None:
        """Make one call of a running step and record what it returns."""
        node = next(n for n in wf_graph.nodes if n.id == node_id)
        step = steps[node_id]
        step_type = registry.STEP_TYPES[node.type]
        if step['call_started_at'] is not None and (
            step_type.side_effect and not step_type.idempotent
        ):
            # A crash or a timeout cut the last call short, and this type
            # cannot find out whether it acted: do not act twice.
            async with self.store.write(run['id']) as conn:
                await self._fail(conn, run, step, 'outcome_unknown')
            return _now()
        timeout = node.timeout_seconds or step_type.timeout_seconds
        limit = float(self.config.lease_seconds - 30)
        if timeout is not None:
            remaining = (
                step['started_at']
                + datetime.timedelta(seconds=timeout)
                - _now()
            ).total_seconds()
            if remaining <= 0:
                return await self._error(run, node, step, 'timeout', True)
            limit = min(limit, remaining)
        async with self.store.write(run['id']) as conn:
            await store.update(
                conn,
                'step_runs',
                {'run_id': run['id'], 'node_id': node_id},
                call_started_at=_now(),
            )
        try:
            async with asyncio.timeout(limit):
                outcome = await self.steps.run(
                    executors.Call(
                        organization_id=run['organization_id'],
                        workflow_slug=slug,
                        run_id=run['id'],
                        node=node,
                        params=step['input'] or {},
                        state=step['state'],
                        idempotency_key=f'{run["id"]}:{node.key}',
                    )
                )
        except executors.StepError as e:
            return await self._error(run, node, step, e.code, e.retry)
        except TimeoutError:
            return await self._error(run, node, step, 'timeout', True)
        except Exception as e:
            LOGGER.exception('Run %s: %s raised', run['id'], node.key)
            return await self._error(run, node, step, type(e).__name__, True)
        key = {'run_id': run['id'], 'node_id': node_id}
        async with self.store.write(run['id']) as conn:
            if outcome.resume_at is not None:
                await store.update(
                    conn,
                    'step_runs',
                    key,
                    state=outcome.state,
                    call_started_at=None,
                )
                return outcome.resume_at
            await store.update(
                conn,
                'step_runs',
                key,
                state=outcome.state,
                output=outcome.output,
            )
            await self._finish(
                conn,
                run,
                step,
                'failed' if outcome.failed else 'succeeded',
                outcome.port,
                None,
            )
        return _now()

    async def _error(
        self,
        run: store.Row,
        node: wf.Node,
        step: store.Row,
        code: str,
        retry: bool,
    ) -> datetime.datetime:
        """Retry the step after a backoff, or fail it."""
        step_type = registry.STEP_TYPES[node.type]
        retries = step_type.retries if node.retries is None else node.retries
        async with self.store.write(run['id']) as conn:
            if not (retry and step['attempt'] <= retries):
                await self._fail(conn, run, step, code)
                return _now()
            attempt = step['attempt'] + 1
            await store.update(
                conn,
                'step_runs',
                {'run_id': run['id'], 'node_id': step['node_id']},
                attempt=attempt,
                error=code,
                state={},
                call_started_at=None,
                started_at=_now(),
            )
            await _step_event(
                conn, run['id'], step['node_id'], 'step.started', retry_of=code
            )
        return _now() + datetime.timedelta(
            seconds=RETRY_BACKOFF * 2 ** (attempt - 2)
        )

    async def _fail(
        self, conn: store.Conn, run: store.Row, step: store.Row, code: str
    ) -> None:
        """Fail a step. It takes its ``Failed`` port when it has one."""
        names = registry.STEP_TYPES[step['node_type']].ports or ()
        port = names.index('Failed') if 'Failed' in names else None
        await self._finish(conn, run, step, 'failed', port, code)

    async def _finish(  # noqa: PLR0913
        self,
        conn: store.Conn,
        run: store.Row,
        step: store.Row,
        status: walk.Status,
        port: int | None,
        error: str | None,
    ) -> None:
        await store.update(
            conn,
            'step_runs',
            {'run_id': run['id'], 'node_id': step['node_id']},
            status=status,
            port=port,
            error=error,
            call_started_at=None,
            finished_at=_now(),
        )
        await _step_event(conn, run['id'], step['node_id'], f'step.{status}')

    # --- Close ---------------------------------------------------------

    async def _close(
        self,
        run: store.Row,
        steps: dict[str, store.Row],
        status: str,
        error: str | None = None,
    ) -> None:
        async with self.store.write(run['id']) as conn:
            await self._close_in(conn, run, steps, status, error)

    async def _close_in(
        self,
        conn: store.Conn,
        run: store.Row,
        steps: dict[str, store.Row],
        status: str,
        error: str | None,
    ) -> None:
        """Close the run. Open steps are ``cancelled``."""
        for step in steps.values():
            if step['status'] in ('pending', 'running'):
                await self._finish(conn, run, step, 'cancelled', None, None)
        await store.update(
            conn,
            'runs',
            {'id': run['id']},
            status=status,
            error=error,
            closed_at=_now(),
        )
        await runtime.append_event(
            conn, run['id'], 'run.closed', {'status': status, 'error': error}
        )

    async def _notify_owner_team(self, run: store.Row, slug: str) -> None:
        """The ``notify_owner_team`` failure policy. Best effort."""
        try:
            await self.steps.notify_failure(
                run['organization_id'], slug, run['id']
            )
        except Exception:  # noqa: BLE001 -- the run is closed already
            LOGGER.warning(
                'Could not tell the owner team that run %s failed',
                run['id'],
                exc_info=True,
            )


# --- Events --------------------------------------------------------------


async def _step_event(
    conn: store.Conn,
    run_id: typing.Any,
    node_id: str,
    event_type: str,
    **extra: typing.Any,
) -> None:
    """Write a step event that holds a snapshot of the step row.

    History rebuilds the step records from these snapshots alone
    (ADR 0021), so read the row after the change it records.
    """
    cur = await conn.execute(
        "SELECT to_jsonb(s) - ARRAY['run_id', 'state', 'call_started_at']"
        ' FROM workflow_runtime.step_runs AS s'
        ' WHERE run_id = %s AND node_id = %s',
        (run_id, node_id),
    )
    row = await cur.fetchone()
    if row is None:
        raise LookupError(f'Run {run_id} has no step {node_id}')
    await runtime.append_event(conn, run_id, event_type, {**row[0], **extra})


# --- References ----------------------------------------------------------


def _scope(
    steps: dict[str, store.Row], payload: dict[str, typing.Any]
) -> tuple[dict[str, typing.Any], dict[str, dict[str, typing.Any]]]:
    """Return the values that references can name: typed, and for text.

    A skipped node resolves to nothing: ``None`` as a whole value, and
    empty text for each of its output fields in a template.
    """
    typed: dict[str, typing.Any] = {'trigger': payload}
    text: dict[str, dict[str, typing.Any]] = {'trigger': payload}
    for step in steps.values():
        key = step['node_key']
        if step['status'] in ('succeeded', 'failed'):
            typed[key] = text[key] = step['output'] or {}
        elif step['status'] == 'skipped':
            typed[key] = None
            output = registry.STEP_TYPES[step['node_type']].output
            text[key] = dict.fromkeys(output.model_fields, '')
    return typed, text


def _lookup(path: str, scope: dict[str, typing.Any]) -> typing.Any:
    value: typing.Any = scope
    for part in path.split('.'):
        if not isinstance(value, dict):
            return None
        value = typing.cast('dict[str, typing.Any]', value).get(part)
    return value


async def _render(
    params: dict[str, typing.Any],
    steps: dict[str, store.Row],
    payload: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    """Resolve the references in ``params`` (ADR 0021, References).

    A value that is one reference resolves to the typed value. Any other
    template renders as text in the sandbox of the prompt CMS.

    Raises:
        rendering.RenderError: A template fails.

    """
    scope, variables = _scope(steps, payload)
    sources: dict[str, str] = {}

    def collect(value: typing.Any, path: str) -> typing.Any:
        if isinstance(value, dict):
            mapping = typing.cast('dict[str, typing.Any]', value)
            return {k: collect(v, f'{path}.{k}') for k, v in mapping.items()}
        if isinstance(value, list):
            items = typing.cast('list[typing.Any]', value)  # type: ignore[redundant-cast]
            return [collect(v, f'{path}.{i}') for i, v in enumerate(items)]
        if not isinstance(value, str) or (
            '{{' not in value and '{%' not in value
        ):
            return value
        whole = _WHOLE_REFERENCE.match(value)
        if whole:
            return _lookup(whole.group(1), scope)
        sources[path] = value
        return value

    resolved = typing.cast('dict[str, typing.Any]', collect(params, ''))
    if not sources:
        return resolved
    schema = {k: models.PromptVariable(type='object') for k in variables}
    if render_pool.in_process():
        rendered = await rendering.render_sources_local(
            schema, variables, {}, sources
        )
    else:
        rendered = await render_pool.get_pool().render_sources(
            schema, variables, {}, sources
        )
    for path, text in rendered.items():
        _assign(resolved, path.split('.')[1:], text)
    return resolved


def _assign(target: typing.Any, parts: list[str], value: str) -> None:
    for part in parts[:-1]:
        target = target[int(part) if isinstance(target, list) else part]
    last = parts[-1]
    if isinstance(target, list):
        typing.cast('list[typing.Any]', target)[int(last)] = value  # type: ignore[redundant-cast]
    else:
        typing.cast('dict[str, typing.Any]', target)[last] = value
