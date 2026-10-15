"""Tests for the agent platform configuration, the marketplaces, the
agent platform fields, and the identity bundle (ADR 0022, P3).

These run against the live Postgres that ``root:services`` boots. The
marketplace sync reads a saved real ``marketplace.json``; GitHub is not
called.
"""

import json
import typing
import uuid
from unittest import mock

import httpx
from psycopg.types import json as pg_json

from apps.api.tests import test_agent_platform as unit
from apps.api.tests.endpoints import test_harness
from imbi.api import secret_broker
from imbi.api.endpoints import harness as harness_api
from imbi.api.harness import marketplaces

SHA_1 = '1' * 40
SHA_2 = '2' * 40
URL = 'https://github.com/anthropics/claude-code'


class PlatformTestCase(test_harness.RunnerTestCase):
    """Fixtures: the runner fixtures, and the caller is an org admin."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await secret_broker.initialize()
        self.permissions |= {
            'agent:read',
            'agent:write',
            'agent_platform_config:write',
        }
        self.act_as_user()
        self.addAsyncCleanup(self._cleanup_platform)

    async def _cleanup_platform(self) -> None:
        async with self.pool.connection() as conn:
            for statement in (
                'DELETE FROM harness.platform_configs'
                ' WHERE organization_id = %s',
                'DELETE FROM harness.marketplaces WHERE organization_id = %s',
                'DELETE FROM secrets.bindings WHERE organization_id = %s',
                'DELETE FROM secrets.providers WHERE organization_id = %s',
            ):
                await conn.execute(statement, (self.org,))

    async def add_binding(
        self,
        reference: str,
        *,
        provider_type: str = 'github_app',
        enabled: bool = True,
        host: str = 'github.com',
    ) -> None:
        """Insert a provider and a binding, as the broker stores them."""
        provider = uuid.uuid4()
        async with self.pool.connection() as conn:
            await conn.execute(
                'INSERT INTO secrets.providers (id, organization_id, name,'
                ' type, config, created_by)'
                " VALUES (%s, %s, %s, %s, %s, 'test')",
                (
                    provider,
                    self.org,
                    reference,
                    provider_type,
                    pg_json.Jsonb({'host': host}),
                ),
            )
            await conn.execute(
                'INSERT INTO secrets.bindings (id, organization_id,'
                ' reference, provider_id, credential_class,'
                ' max_ttl_seconds, enabled, created_by) VALUES (%s, %s,'
                " %s, %s, 'dynamic', 60, %s, 'test')",
                (uuid.uuid4(), self.org, reference, provider, enabled),
            )

    async def set_links(self, links: dict[str, str]) -> None:
        await self.graph.execute(
            'MATCH (p:Project {{id: {id}}}) SET p.links = {links}'
            ' RETURN p.id AS id',
            {'id': self.project_id, 'links': json.dumps(links)},
            ['id'],
        )

    def org_url(self, path: str) -> str:
        return f'/organizations/{self.org}/{path}'

    async def put_config(self, **config: typing.Any) -> httpx.Response:
        return await self.client.put(
            self.org_url('agent-platform-config/'), json=config
        )

    async def add_marketplace(
        self, sha: str = SHA_1, slug: str = 'claude-code'
    ) -> dict[str, typing.Any]:
        with self.head(sha):
            response = await self.client.post(
                self.org_url('agent-marketplaces/'),
                json={'slug': slug, 'url': URL},
            )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def head(self, sha: str) -> typing.Any:
        """Make the sync read the saved marketplace at ``sha``."""
        return mock.patch.object(
            marketplaces,
            'fetch',
            mock.AsyncMock(
                return_value=marketplaces.Head(
                    'main', sha, unit.FIXTURE.read_text()
                )
            ),
        )

    async def create_agent(self, **settings: typing.Any) -> httpx.Response:
        return await self.client.post(
            self.org_url('agents/'),
            json={
                'name': 'Builder',
                'slug': 'builder',
                'team': self.team_id,
                'settings': settings,
            },
        )


class ConfigTests(PlatformTestCase):
    async def test_versions(self) -> None:
        response = await self.client.get(
            self.org_url('agent-platform-config/')
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()['version'])
        self.assertEqual(
            response.json()['config']['permission_mode'], 'default'
        )

        response = await self.put_config(permission_mode='acceptEdits')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['version'], 1)
        response = await self.client.get(
            self.org_url('agent-platform-config/')
        )
        self.assertEqual(response.json()['version'], 1)
        self.assertEqual(response.json()['created_by'], self.email)
        # No change, no version.
        response = await self.put_config(permission_mode='acceptEdits')
        self.assertEqual(response.json()['version'], 1)
        response = await self.put_config(permission_mode='plan')
        self.assertEqual(response.json()['version'], 2)
        response = await self.client.get(
            self.org_url('agent-platform-config/')
        )
        self.assertEqual(response.json()['version'], 2)
        self.assertEqual(response.json()['config']['permission_mode'], 'plan')

    async def test_write_needs_the_permission(self) -> None:
        self.permissions.discard('agent_platform_config:write')
        response = await self.put_config(permission_mode='plan')
        self.assertEqual(response.status_code, 403, response.text)
        response = await self.client.post(
            self.org_url('agent-marketplaces/'),
            json={'slug': 'x', 'url': URL},
        )
        self.assertEqual(response.status_code, 403, response.text)

    async def test_refuses_unknown_marketplaces_and_bad_refs(self) -> None:
        response = await self.put_config(allowed_marketplaces=['nope'])
        self.assertEqual(response.status_code, 422, response.text)
        response = await self.put_config(
            model_upstream={'kind': 'litellm', 'key_ref': 'not a ref'}
        )
        self.assertEqual(response.status_code, 422, response.text)

    async def test_default_plugins_are_pinned(self) -> None:
        await self.add_marketplace()
        response = await self.put_config(
            allowed_marketplaces=['claude-code'],
            default_plugins=[
                {'marketplace': 'claude-code', 'plugin': 'code-review'}
            ],
        )
        self.assertEqual(response.status_code, 200, response.text)
        (plugin,) = response.json()['config']['default_plugins']
        self.assertEqual(plugin['sha'], SHA_1)
        self.assertEqual(plugin['url'], URL)
        self.assertEqual(plugin['path'], 'plugins/code-review')


class MarketplaceTests(PlatformTestCase):
    async def test_picker_lists_the_real_catalog(self) -> None:
        marketplace = await self.add_marketplace()
        self.assertEqual(marketplace['name'], 'claude-code-plugins')
        self.assertEqual(marketplace['head_sha'], SHA_1)
        self.assertIsNone(marketplace['sync_error'])
        response = await self.client.get(self.org_url('agent-marketplaces/'))
        self.assertEqual(response.status_code, 200, response.text)
        (listed,) = response.json()
        names = {p['name'] for p in listed['plugins']}
        self.assertEqual(len(names), 13)
        self.assertIn('code-review', names)

    async def test_duplicate_and_failed_sync(self) -> None:
        await self.add_marketplace()
        with self.head(SHA_1):
            response = await self.client.post(
                self.org_url('agent-marketplaces/'),
                json={'slug': 'claude-code', 'url': URL},
            )
        self.assertEqual(response.status_code, 409, response.text)
        with mock.patch.object(
            marketplaces,
            'fetch',
            mock.AsyncMock(side_effect=marketplaces.SyncError('no access')),
        ):
            response = await self.client.post(
                self.org_url('agent-marketplaces/claude-code/sync')
            )
        self.assertEqual(response.status_code, 200, response.text)
        # A failed sync keeps the last catalog.
        self.assertEqual(response.json()['sync_error'], 'no access')
        self.assertEqual(len(response.json()['plugins']), 13)

    async def test_delete_refused_while_allowed(self) -> None:
        await self.add_marketplace()
        await self.put_config(allowed_marketplaces=['claude-code'])
        path = self.org_url('agent-marketplaces/claude-code')
        response = await self.client.delete(path)
        self.assertEqual(response.status_code, 409, response.text)
        await self.put_config()
        response = await self.client.delete(path)
        self.assertEqual(response.status_code, 204, response.text)


class AgentFieldTests(PlatformTestCase):
    async def test_widening_is_refused(self) -> None:
        await self.put_config(permission_mode='default')
        response = await self.create_agent(permission_mode='bypassPermissions')
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn('widens', response.text)
        response = await self.create_agent(
            plugins=[{'marketplace': 'claude-code', 'plugin': 'code-review'}]
        )
        self.assertEqual(response.status_code, 422, response.text)
        response = await self.create_agent(permission_mode='plan')
        self.assertEqual(response.status_code, 201, response.text)
        response = await self.client.patch(
            self.org_url('agents/builder'),
            json=[
                {
                    'op': 'replace',
                    'path': '/settings/permission_mode',
                    'value': 'acceptEdits',
                }
            ],
        )
        self.assertEqual(response.status_code, 422, response.text)

    async def test_plugins_are_pinned_in_the_version(self) -> None:
        await self.add_marketplace(SHA_1)
        await self.put_config(allowed_marketplaces=['claude-code'])
        response = await self.create_agent(
            plugins=[{'marketplace': 'claude-code', 'plugin': 'code-review'}]
        )
        self.assertEqual(response.status_code, 201, response.text)
        (plugin,) = response.json()['settings']['plugins']
        self.assertEqual(
            (plugin['sha'], plugin['url'], plugin['path']),
            (SHA_1, URL, 'plugins/code-review'),
        )
        with self.head(SHA_2):
            await self.client.post(
                self.org_url('agent-marketplaces/claude-code/sync')
            )
        # A change that keeps the plugin keeps its pin.
        response = await self.client.patch(
            self.org_url('agents/builder'),
            json=[{'op': 'replace', 'path': '/description', 'value': 'x'}],
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['version'], 2)
        self.assertEqual(
            response.json()['settings']['plugins'][0]['sha'], SHA_1
        )
        version = await self.client.get(
            self.org_url('agents/builder/versions/2')
        )
        self.assertEqual(
            version.json()['snapshot']['settings']['plugins'][0]['sha'], SHA_1
        )
        # A plugin given without sha is pinned to the new head.
        response = await self.client.put(
            self.org_url('agents/builder'),
            json={
                'settings': {
                    'plugins': [
                        {'marketplace': 'claude-code', 'plugin': 'code-review'}
                    ]
                }
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()['settings']['plugins'][0]['sha'], SHA_2
        )

    async def test_secrets_and_github_app_binding(self) -> None:
        response = await self.create_agent(secrets=['not-a-ref'])
        self.assertEqual(response.status_code, 422, response.text)
        response = await self.create_agent(
            github_app_binding='secret://gh/bot'
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn('not found', response.text)
        await self.add_binding('secret://gh/fake', provider_type='fake')
        await self.add_binding('secret://gh/off', enabled=False)
        await self.add_binding('secret://gh/bot')
        for reference, error in (
            ('secret://gh/fake', 'not a github_app binding'),
            ('secret://gh/off', 'disabled'),
        ):
            response = await self.create_agent(github_app_binding=reference)
            self.assertEqual(response.status_code, 422, response.text)
            self.assertIn(error, response.text)
        response = await self.create_agent(
            github_app_binding='secret://gh/bot',
            secrets=['secret://ci/token#value'],
        )
        self.assertEqual(response.status_code, 201, response.text)
        settings = response.json()['settings']
        self.assertEqual(settings['github_app_binding'], 'secret://gh/bot')
        self.assertEqual(settings['secrets'], ['secret://ci/token#value'])


class BundleTests(PlatformTestCase):
    async def test_claim_bundle_has_the_merged_config(self) -> None:
        self.act_as(self.account)
        claim = await self.claim(await self.register())
        assert claim is not None
        bundle = claim['bundle']
        self.assertIsNone(bundle['platform_config_version'])
        self.assertEqual(bundle['config']['permission_mode'], 'default')
        self.assertEqual(bundle['config']['plugins'], [])
        self.assertEqual(bundle['repositories'], [])
        self.assertNotIn('secret', str(bundle['config']['model_upstream']))

    async def test_bundle_of_a_pinned_version_does_not_change(self) -> None:
        await self.add_marketplace()
        await self.put_config(
            system_prompt_prefix='one',
            allowed_marketplaces=['claude-code'],
            default_plugins=[
                {'marketplace': 'claude-code', 'plugin': 'code-review'}
            ],
        )
        await self.set_links({'github-repository': 'https://github.com/a/b'})
        response = await self.create_task(project_id=self.project_id)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['platform_config_version'], 1)
        task = await self.task_row(response.json()['short_id'])
        before = await harness_api._identity(
            self.graph, self.harness, self.secret_store, task, self.org
        )
        self.assertEqual(before.platform_config_version, 1)
        assert before.config is not None
        self.assertEqual(before.config.system_prompt_prefix, 'one')
        self.assertEqual(before.config.plugins[0].sha, SHA_1)
        self.assertEqual(before.config.plugins[0].url, URL)
        self.assertEqual(
            [r.model_dump() for r in before.repositories],
            [
                {
                    'host': 'github.com',
                    'name': 'a/b',
                    'url': 'https://github.com/a/b',
                }
            ],
        )

        await self.put_config(system_prompt_prefix='two')
        after = await harness_api._identity(
            self.graph, self.harness, self.secret_store, task, self.org
        )
        self.assertEqual(after, before)
        # A new task pins the new version.
        response = await self.create_task()
        self.assertEqual(response.json()['platform_config_version'], 2)

    async def test_repositories_use_the_github_app_host(self) -> None:
        await self.add_binding('secret://gh/bot', host='acme.ghe.com')
        await self.make_version(
            {'settings': {'github_app_binding': 'secret://gh/bot'}}
        )
        await self.set_links(
            {
                'github-repository': 'https://acme.ghe.com/ops/billing.git',
                'docs': 'https://github.com/ops/docs',
            }
        )
        response = await self.create_task(project_id=self.project_id)
        task = await self.task_row(response.json()['short_id'])
        bundle = await harness_api._identity(
            self.graph, self.harness, self.secret_store, task, self.org
        )
        self.assertEqual(
            [(r.host, r.name) for r in bundle.repositories],
            [('acme.ghe.com', 'ops/billing')],
        )
        # A link on another host than the provider's gives nothing.
        await self.set_links(
            {'github-repository': 'https://github.com/ops/billing'}
        )
        bundle = await harness_api._identity(
            self.graph, self.harness, self.secret_store, task, self.org
        )
        self.assertEqual(bundle.repositories, [])

    async def test_a_missing_pinned_version_fails_the_claim(self) -> None:
        await self.put_config(system_prompt_prefix='one')
        response = await self.create_task()
        task = await self.task_row(response.json()['short_id'])
        with self.assertRaisesRegex(LookupError, 'version 9 is missing'):
            await harness_api._identity(
                self.graph,
                self.harness,
                self.secret_store,
                {**task, 'platform_config_version': 9},
                self.org,
            )
