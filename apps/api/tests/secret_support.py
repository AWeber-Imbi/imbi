"""Fixtures for the secrets broker tests (ADR 0022).

Rows are written to the live Postgres that ``root:services`` boots.
Each test uses its own organization id and deletes only its own rows,
because other suites share the database.
"""

import typing
import unittest
import uuid
from unittest import mock

from psycopg.types import json as pg_json

from imbi.api import agent_tasks, harness, secret_broker
from imbi.api.secret_broker import audit, broker, providers, store

#: The secret value of the fake provider. Every leak check looks for it.
MATERIAL = 'material-' + uuid.uuid4().hex
JSON_MATERIAL = (
    '{"token": "' + MATERIAL + '", "user": "bot", "count": 3}'
).encode()


def use_plugin_providers(case: unittest.TestCase) -> None:
    """Register the providers of the AWS and GitHub plugins for a test.

    imbi-api loads them from the plugin registry when it first needs a
    provider (:func:`providers.get`). The tests do not load the registry.
    """
    from imbi.plugins.aws.secrets_manager import AwsSecretsManager
    from imbi.plugins.github.secret_provider import GitHubApp

    host = providers._Host()  # pyright: ignore[reportPrivateUsage]
    # Start from these providers only: a registry that an earlier test
    # loaded must not add more types.
    for patcher in (
        mock.patch.dict(
            providers.PROVIDERS,
            {
                'fake': providers.PROVIDERS['fake'],
                'aws_secrets_manager': AwsSecretsManager(host),
                'github_app': GitHubApp(host),
            },
            clear=True,
        ),
        mock.patch.dict(providers._LOADED, clear=True),  # pyright: ignore[reportPrivateUsage]
        mock.patch.object(
            providers.plugin_registry, 'list_plugins', return_value=[]
        ),
    ):
        patcher.start()
        case.addCleanup(patcher.stop)


class SecretCase(unittest.IsolatedAsyncioTestCase):
    """A pool, a broker, a fake provider, and audit capture."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        suffix = uuid.uuid4().hex[:10]
        self.org = f'sec-{suffix}'
        self.agent = f'agent-{suffix}'
        self.project = f'proj-{suffix}'
        #: A live runner: materialization checks its state.
        self.runner = str(uuid.uuid4())
        self.runner_pool = f'pool-{suffix}'
        await agent_tasks.initialize()
        await harness.initialize()
        await secret_broker.initialize()
        self.pool = agent_tasks.create_pool()
        await self.pool.open()
        async with self.pool.connection() as conn:
            await conn.execute(
                'INSERT INTO harness.pools (name, service_account)'
                " VALUES (%s, 'test')",
                (self.runner_pool,),
            )
            await conn.execute(
                'INSERT INTO harness.runners (id, pool, state,'
                ' runner_token_hash, executor_token_hash, lease_expires_at)'
                " VALUES (%s, %s, 'busy', %s, %s,"
                " NOW() + interval '1 hour')",
                (self.runner, self.runner_pool, self.runner, self.runner),
            )
        self.broker = broker.Broker(self.pool)
        self.store = store.SecretStore(self.pool)
        self.addAsyncCleanup(self._cleanup)

        use_plugin_providers(self)
        fake = providers.PROVIDERS['fake']
        assert isinstance(fake, providers.FakeProvider)
        self.fake = fake
        fake.values = {'plain': MATERIAL.encode(), 'json': JSON_MATERIAL}
        fake.leases = set()
        fake.revoked = []
        fake.fail_revoke = False
        fake.unavailable = False

        #: The events that the outbox published to Iggy.
        self.published: list[audit.Event] = []

        async def capture(
            stream: str, topic: str, models: list[typing.Any], **_: typing.Any
        ) -> None:
            self.assertEqual((stream, topic), (audit.STREAM, audit.TOPIC))
            self.published.extend(models)

        patcher = mock.patch.object(
            audit.iggy, 'publish', mock.AsyncMock(side_effect=capture)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        #: The task log publish of the ADR 0020 task events.
        self.task_log = mock.AsyncMock()
        patcher = mock.patch.object(broker.log, 'publish', self.task_log)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.provider = await self.store.create(
            'providers',
            self.org,
            {
                'name': 'fake',
                'type': 'fake',
                'config': {},
                'capabilities': sorted(fake.capabilities),
                'created_by': 'test',
            },
        )
        self.binding = await self.add_binding()
        self.grant = await self.add_grant([self.binding['id']])
        self.task_id = await self.add_task()

    async def _cleanup(self) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                'DELETE FROM secrets.audit_outbox'
                " WHERE event->>'organization_id' = %s",
                (self.org,),
            )
            for table in (
                'resolutions',
                'grants',
                'bindings',
                'providers',
                'identity_sources',
            ):
                await conn.execute(
                    f'DELETE FROM secrets.{table} WHERE organization_id = %s',
                    (self.org,),
                )
            for table in ('task_projects', 'tasks'):
                await conn.execute(
                    f'DELETE FROM agent_runtime.{table}'
                    ' WHERE organization_id = %s',
                    (self.org,),
                )
            await conn.execute(
                'DELETE FROM harness.pools WHERE name = %s',
                (self.runner_pool,),
            )
        await self.pool.close()

    async def audit_events(self) -> list[audit.Event]:
        """Return the outbox events of this organization, in order."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                'SELECT event FROM secrets.audit_outbox'
                " WHERE event->>'organization_id' = %s ORDER BY seq",
                (self.org,),
            )
            return [
                audit.Event.model_validate(r[0]) for r in await cur.fetchall()
            ]

    async def task_events(
        self, task_id: uuid.UUID | None = None
    ) -> list[dict[str, typing.Any]]:
        """Return the secret events of a task, in order."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                'SELECT actor_kind, payload FROM agent_runtime.events'
                ' WHERE task_id = %s AND type = %s ORDER BY seq',
                (task_id or self.task_id, broker.TASK_EVENT_TYPE),
            )
            return [
                {'actor_kind': kind, **payload}
                for kind, payload in await cur.fetchall()
            ]

    async def add_binding(self, **values: typing.Any) -> store.Row:
        return await self.store.create(
            'bindings',
            self.org,
            {
                'reference': 'secret://production/github/token',
                'provider_id': self.provider['id'],
                'credential_class': 'static',
                'locator': {'key': 'plain'},
                'allowed_fields': [],
                'allowed_delivery_modes': ['environment', 'stdin'],
                'max_ttl_seconds': 900,
                'created_by': 'test',
            }
            | values,
        )

    async def add_grant(
        self, binding_ids: list[uuid.UUID], **values: typing.Any
    ) -> store.Row:
        return await self.store.create(
            'grants',
            self.org,
            {
                'agent_ids': [self.agent],
                'project_ids': [self.project],
                'binding_ids': binding_ids,
                'purposes': ['github_write'],
                'delivery_modes': ['environment', 'stdin'],
                'max_ttl_seconds': 900,
                'created_by': 'test',
            }
            | values,
        )

    async def add_task(
        self, agent: str | None = None, project: str | None = ''
    ) -> uuid.UUID:
        task_id = uuid.uuid4()
        async with self.pool.connection() as conn:
            await conn.execute(
                'INSERT INTO agent_runtime.tasks (id, organization_id,'
                ' short_id, agent_id, agent_version, service_account_id,'
                ' title, description, origin_kind, origin_id,'
                ' origin, owner) VALUES (%s, %s, %s, %s, 1, %s, %s, %s,'
                " 'human', 'test', %s, 'test')",
                (
                    task_id,
                    self.org,
                    task_id.hex[:8],
                    agent or self.agent,
                    'sa',
                    'Task',
                    '',
                    pg_json.Jsonb({}),
                ),
            )
            project_id = self.project if project == '' else project
            if project_id is not None:
                await self.add_task_project(conn, task_id, project_id)
        return task_id

    async def add_task_project(
        self, conn: typing.Any, task_id: uuid.UUID, project_id: str
    ) -> None:
        await conn.execute(
            'INSERT INTO agent_runtime.task_projects (organization_id,'
            ' task_id, project_id, project_slug, added_by_kind, added_by)'
            " VALUES (%s, %s, %s, %s, 'human', 'test')",
            (self.org, task_id, project_id, project_id),
        )

    def context(self, **changes: typing.Any) -> broker.ResolutionContext:
        values: dict[str, typing.Any] = {
            'organization_id': self.org,
            'agent_id': self.agent,
            'project_ids': (self.project,),
            'task_id': self.task_id,
            'runner_id': self.runner,
        } | changes
        return broker.ResolutionContext(**values)

    def request(self, **changes: typing.Any) -> broker.ResolutionRequest:
        values: dict[str, typing.Any] = {
            'reference': 'secret://production/github/token',
            'purpose': 'github_write',
            'ttl_seconds': 300,
            'delivery_mode': 'environment',
            'delivery_target': 'GH_TOKEN',
        } | changes
        return broker.ResolutionRequest(**values)

    def materialize_request(
        self, handle: str, **changes: typing.Any
    ) -> broker.MaterializeRequest:
        values: dict[str, typing.Any] = {
            'handle': handle,
            'nonce': uuid.uuid4().hex,
            'task_id': self.task_id,
            'agent_id': self.agent,
            'purpose': 'github_write',
        } | changes
        return broker.MaterializeRequest(**values)

    def executor(self, runner: str | None = None) -> broker.ExecutorContext:
        return broker.ExecutorContext(runner or self.runner)
