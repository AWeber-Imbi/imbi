"""The trigger reconciler (ADR 0021, Triggers).

imbi-api writes the desired trigger bindings when a workflow activates,
pauses, or is deleted, in Postgres only. This writes the scheduler and
the gateway to match, and records each binding as ``synced`` or
``failed`` with the error. It runs when imbi-api notifies and on a
schedule, so a lost notification or a failed call delays a binding and
leaves nothing half made: the next pass tries again.

- A ``schedule`` binding is the scheduler task ``workflow-<binding id>``.
  Its ``api`` target posts to the run endpoint as the scheduler's service
  account. A pause disables it. The scheduler checks the cron
  expression: a bad one fails the binding with the scheduler's error.
- A ``webhook`` binding is a ``gateway-actions#start_workflow`` rule on
  the Webhook that the trigger names. A pause keeps it, because the run
  endpoint refuses a paused workflow with ``409`` and the gateway records
  that delivery as no effect.
"""

import asyncio
import json
import logging
import typing

import httpx
from psycopg import rows

from imbi.common import graph
from imbi.common.graph import cypher
from imbi.workflows import executors, settings, store

LOGGER = logging.getLogger(__name__)

HANDLER = 'gateway-actions#start_workflow'

#: The scheduler runs an ``api`` task only as its own service account
#: (scheduler ADR 0002).
SCHEDULER_ACCOUNT = 'imbi-scheduler'

HTTP_NOT_FOUND = 404

_RULES: typing.LiteralString = """
MATCH (r:WebhookRule)-[:ACTIONS]->(w:Webhook)
WHERE r.handler = {handler} AND r.handler_config CONTAINS {binding}
RETURN w.id AS webhook, r.filter_expression AS filter,
       r.handler_config AS config
"""

_DELETE_RULES: typing.LiteralString = """
MATCH (r:WebhookRule)
WHERE r.handler = {handler} AND r.handler_config CONTAINS {binding}
DETACH DELETE r
RETURN 1 AS ok
"""

_CREATE_RULE: typing.LiteralString = """
MATCH (w:Webhook {{id: {webhook}}})
      -[:BELONGS_TO]->(:Organization {{id: {org}}})
OPTIONAL MATCH (r:WebhookRule)-[:ACTIONS]->(w)
WITH w, max(r.ordinal) AS top
CREATE (n:WebhookRule {{filter_expression: {filter}, handler: {handler},
                        handler_config: {config},
                        ordinal: coalesce(top, -1) + 1}})-[:ACTIONS]->(w)
RETURN w.id AS id
"""


class SyncError(Exception):
    """The scheduler or the gateway did not take the binding."""


class Reconciler:
    def __init__(
        self,
        pool: store.Pool,
        http: httpx.AsyncClient,
        steps: executors.Executors,
        config: settings.Workflows,
        organization_id: str | None = None,
    ) -> None:
        self.pool = pool
        self.http = http
        self.steps = steps
        self.config = config
        #: Sync only the bindings of this organization. ``None``, as in
        #: production, syncs every binding. Tests that share one
        #: database with other engines set it, as for ``store.Store``.
        self.organization_id = organization_id
        self._wake = asyncio.Event()

    def notify(self) -> None:
        """Start the next pass now."""
        self._wake.set()

    async def run_forever(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            self._wake.clear()
            try:
                await self.reconcile()
            except Exception:
                LOGGER.exception('Trigger reconcile failed; continuing')
            waiters = [
                asyncio.create_task(stop.wait()),
                asyncio.create_task(self._wake.wait()),
            ]
            try:
                await asyncio.wait(
                    waiters,
                    timeout=self.config.reconcile_interval,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                for waiter in waiters:
                    waiter.cancel()
                await asyncio.gather(*waiters, return_exceptions=True)

    async def reconcile(self) -> None:
        """Sync every binding once."""
        async with (
            self.pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cur,
        ):
            await cur.execute(
                'SELECT b.*, w.slug AS workflow_slug'
                ' FROM workflows.trigger_bindings AS b'
                ' LEFT JOIN workflows.workflows AS w ON w.id = b.workflow_id'
                ' WHERE %(org)s::text IS NULL OR b.organization_id = %(org)s'
                ' ORDER BY b.updated_at',
                {'org': self.organization_id},
            )
            bindings = await cur.fetchall()
        for binding in bindings:
            try:
                if binding['type'] == 'schedule':
                    target_id = await self._schedule(binding)
                else:
                    target_id = await self._webhook(binding)
            except Exception as e:  # noqa: BLE001 -- recorded on the binding
                LOGGER.warning(
                    'Trigger binding %s failed: %s', binding['id'], e
                )
                await self._record(binding, None, str(e) or type(e).__name__)
            else:
                await self._record(binding, target_id, None)

    async def _record(
        self, binding: store.Row, target_id: str | None, error: str | None
    ) -> None:
        """Write the outcome, unless imbi-api changed the binding since.

        A changed binding has a new ``updated_at`` and is ``pending``,
        and imbi-api notified, so the next pass syncs it.
        """
        where = (binding['id'], binding['updated_at'])
        async with self.pool.connection() as conn:
            if error is not None:
                await conn.execute(
                    'UPDATE workflows.trigger_bindings SET sync_state ='
                    " 'failed', error = %s WHERE id = %s AND updated_at = %s",
                    (error[:1000], *where),
                )
            elif binding['removed']:
                await conn.execute(
                    'DELETE FROM workflows.trigger_bindings'
                    ' WHERE id = %s AND updated_at = %s',
                    where,
                )
            else:
                await conn.execute(
                    'UPDATE workflows.trigger_bindings SET sync_state ='
                    " 'synced', error = NULL, target_id = %s,"
                    ' synced_at = NOW() WHERE id = %s AND updated_at = %s',
                    (target_id, *where),
                )

    # --- Scheduler -----------------------------------------------------

    async def _scheduler(
        self, method: str, path: str, body: typing.Any = None
    ) -> httpx.Response:
        return await self.http.request(
            method,
            self.config.scheduler_url.rstrip('/') + path,
            json=body,
            headers={
                'Authorization': f'Bearer {await self.steps.api.bearer()}'
            },
        )

    async def _schedule(self, binding: store.Row) -> str | None:
        """Make the scheduler task match the binding. Return its id."""
        path = f'/tasks/workflow-{binding["id"]}'
        if binding['removed']:
            response = await self._scheduler('DELETE', path)
            if response.status_code != HTTP_NOT_FOUND:
                _check(response)
            return None
        desired = await self._task(binding)
        response = await self._scheduler('GET', path)
        if response.status_code == HTTP_NOT_FOUND:
            response = await self._scheduler(
                'POST',
                '/tasks',
                {'slug': path.rsplit('/', 1)[1], 'kind': 'user', **desired},
            )
        else:
            _check(response)
            task = response.json()
            patch = [
                {'op': 'replace', 'path': f'/{key}', 'value': value}
                for key, value in desired.items()
                if task.get(key) != value
            ]
            if patch:
                response = await self._scheduler('PATCH', path, patch)
        _check(response)
        return str(response.json()['id'])

    async def _task(self, binding: store.Row) -> dict[str, typing.Any]:
        """Return the fields of the scheduler task, as the scheduler
        returns them, so that a task that matches is not patched."""
        slug = binding['workflow_slug']
        params = binding['params']
        return {
            'name': f'Workflow {slug}: {binding["node_id"]}',
            'description': 'Schedule trigger of a workflow. imbi-workflows '
            'manages this task: a change to it is undone.',
            'organization': await self.steps.org_slug(
                binding['organization_id']
            ),
            'enabled': binding['enabled'],
            'trigger': {
                'kind': 'cron',
                'expression': params['cron'],
                'jitter': None,
            },
            'timezone': params.get('timezone', 'UTC'),
            'identity': {
                'kind': 'service_account',
                'subject': SCHEDULER_ACCOUNT,
                'consent_id': None,
                'scope': 'imbi-api:*',
            },
            'target': {
                'kind': 'api',
                'method': 'POST',
                'path': f'/workflows/{slug}/runs',
                'query': {},
                # The scheduler renders the body; its run id is the
                # Idempotency-Key, so a retry starts no second run.
                'body': {
                    'trigger': binding['node_id'],
                    'payload': {'fired_at': '{{ run.fired_at }}'},
                },
                'organization': None,
            },
        }

    # --- Gateway -------------------------------------------------------

    async def _webhook(self, binding: store.Row) -> str | None:
        """Make the gateway rule match the binding. Return the webhook id.

        The rule is found by the binding id in its config, so a rule on a
        Webhook that the trigger no longer names is removed too.
        """
        # The exact field, as json.dumps writes it here and in the
        # webhooks API: an id elsewhere in the config (a trigger node id
        # can be any string) must not match.
        marker = {
            'handler': HANDLER,
            'binding': f'"binding": "{binding["id"]}"',
        }
        if binding['removed']:
            await self.steps.db.execute(_DELETE_RULES, marker, ['ok'])
            return None
        params = binding['params']
        rule_filter = params.get('filter') or 'true'
        config = {
            'workflow_slug': binding['workflow_slug'],
            'trigger': binding['node_id'],
            'binding': str(binding['id']),
        }
        found = await self.steps.db.execute(
            _RULES, marker, ['webhook', 'filter', 'config']
        )
        current = [
            (
                graph.parse_agtype(r['webhook']),
                graph.parse_agtype(r['filter']),
                json.loads(str(graph.parse_agtype(r['config']))),
            )
            for r in found
        ]
        if current == [(params['webhook_id'], rule_filter, config)]:
            return str(params['webhook_id'])
        # One transaction, delete first: the gateway never sees the
        # webhook without the rule, and a webhook outside the org rolls
        # the delete back.
        try:
            await self.steps.db._execute_batch(  # pyright: ignore[reportPrivateUsage]
                [
                    cypher.Statement(_DELETE_RULES, marker),
                    cypher.Statement(
                        _CREATE_RULE,
                        {
                            **marker,
                            'webhook': params['webhook_id'],
                            'org': binding['organization_id'],
                            'filter': rule_filter,
                            'config': json.dumps(config),
                        },
                        expect_rows=True,
                    ),
                ]
            )
        except graph.StatementMatchedNothing as e:
            raise SyncError(
                f'Webhook {params["webhook_id"]!r} is not in the organization'
            ) from e
        return str(params['webhook_id'])


def _check(response: httpx.Response) -> None:
    if response.is_error:
        raise SyncError(
            f'imbi-scheduler returned {response.status_code}: '
            f'{response.text[:500]}'
        )
