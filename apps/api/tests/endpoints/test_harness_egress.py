"""Tests for the egress destinations, the egress sync routes, and the
egress allowlist of a claim (harness egress PRD).

The destinations are platform-wide, so each test uses slugs with the
suffix of its organization and deletes them at the end.
"""

import typing
import unittest
import uuid

import fastapi

from apps.api.tests.endpoints import test_harness
from imbi.api.endpoints import agents as agents_api
from imbi.api.endpoints import harness as harness_api
from imbi.api.harness import egress
from imbi.common import models


class CidrTests(unittest.TestCase):
    def test_canonical_sorted_and_unique(self) -> None:
        self.assertEqual(
            egress.check_cidrs(['10.2.0.0/16', '10.1.0.0/16', '10.2.0.0/16']),
            ['10.1.0.0/16', '10.2.0.0/16'],
        )

    def test_refused(self) -> None:
        for cidr in (
            'nope',
            '10.1.2.3/16',  # host bits set
            'fd00::/8',
            '8.8.8.0/24',
            '0.0.0.0/0',
            '169.254.169.254/32',
            '127.0.0.1/32',
        ):
            with self.subTest(cidr=cidr), self.assertRaises(ValueError):
                egress.check_cidrs([cidr])

    def test_count(self) -> None:
        with self.assertRaises(ValueError):
            egress.check_cidrs([])
        too_many = [f'10.0.{n}.0/24' for n in range(egress.MAX_CIDRS + 1)]
        with self.assertRaises(ValueError):
            egress.check_cidrs(too_many)

    def test_port_pairs_per_cidr(self) -> None:
        def row(cidr: str, ports: range) -> dict[str, typing.Any]:
            return {
                'cidrs': [cidr],
                'ports': [{'port': p, 'protocol': 'TCP'} for p in ports],
            }

        rows = [
            row('10.0.0.0/24', range(1, 13)),
            row('10.0.0.0/24', range(13, 25)),
        ]
        self.assertEqual(egress.port_pairs_over_limit(rows), [])
        rows.append(row('10.0.0.0/24', range(25, 26)))
        self.assertEqual(egress.port_pairs_over_limit(rows), ['10.0.0.0/24'])


class GrantTests(unittest.TestCase):
    @staticmethod
    def row(slug: str, **values: typing.Any) -> dict[str, typing.Any]:
        return {
            'slug': slug,
            'cidrs': ['10.0.0.0/24'],
            'ports': [{'port': 443, 'protocol': 'TCP'}],
            'is_global': False,
            'organization_ids': [],
            'generation': 1,
            'applied_generation': 1,
            **values,
        }

    def test_split(self) -> None:
        rows = [
            self.row('g', is_global=True),
            self.row('a'),
            self.row('pending', generation=2, applied_generation=1),
            self.row('other-org', organization_ids=['x']),
            self.row('not-mine'),
        ]
        grants, pending = egress.grants(
            rows, ['a', 'pending', 'other-org', 'gone'], 'org'
        )
        self.assertEqual([g.slug for g in grants], ['a', 'g'])
        self.assertEqual(
            {p.slug: p.reason for p in pending},
            {
                'gone': 'unknown',
                'other-org': 'organization_not_allowed',
                'pending': 'not_applied',
            },
        )


class EgressTestCase(test_harness.RunnerTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.suffix = self.org.removeprefix('at-')
        self.addAsyncCleanup(self._cleanup_egress)

    async def _cleanup_egress(self) -> None:
        async with self.pool.connection() as conn:
            for table in (
                'egress_destinations',
                'egress_destination_changes',
            ):
                await conn.execute(
                    f'DELETE FROM harness.{table} WHERE slug LIKE %s',
                    (f'%{self.suffix}',),
                )

    def slug(self, name: str) -> str:
        return f'{name}-{self.suffix}'

    async def destination(
        self, name: str, *, applied: bool = True, **values: typing.Any
    ) -> dict[str, typing.Any]:
        row = await self.harness.create_egress_destination(
            {
                'slug': self.slug(name),
                'name': name,
                'description': None,
                'cidrs': ['10.9.0.0/24'],
                'ports': [{'port': 443, 'protocol': 'TCP'}],
                'is_global': False,
                'organization_ids': [],
                **values,
            },
            'test',
        )
        if applied:
            await self.harness.report_egress_sync(
                {row['slug']: row['generation']}, 'test'
            )
        return row

    async def as_pool(
        self, method: str, path: str, **kwargs: typing.Any
    ) -> typing.Any:
        self.act_as(self.pool_account)
        try:
            return await self.client.request(method, path, **kwargs)
        finally:
            self.act_as(self.account)


class DestinationApiTests(EgressTestCase):
    def body(self, name: str, **values: typing.Any) -> dict[str, typing.Any]:
        return {
            'slug': self.slug(name),
            'name': name,
            'cidrs': ['10.8.0.0/16'],
            'ports': [{'port': 443}, {'port': 53, 'protocol': 'UDP'}],
            **values,
        }

    async def test_platform_admin_manages_destinations(self) -> None:
        self.act_as_user()
        response = await self.client.post(
            '/harness/egress-destinations', json=self.body('db')
        )
        self.assertEqual(response.status_code, 403, response.text)
        self.user.is_admin = True
        response = await self.client.post(
            '/harness/egress-destinations',
            json=self.body('db', organizations=[self.org]),
        )
        self.assertEqual(response.status_code, 201, response.text)
        created = response.json()
        self.assertEqual(created['generation'], 1)
        self.assertIsNone(created['applied_generation'])
        self.assertTrue(created['pending'])
        self.assertFalse(created['global'])
        self.assertEqual(created['organizations'], [self.org])
        self.assertEqual(
            created['ports'],
            [
                {'port': 53, 'protocol': 'UDP'},
                {'port': 443, 'protocol': 'TCP'},
            ],
        )
        response = await self.client.post(
            '/harness/egress-destinations', json=self.body('db')
        )
        self.assertEqual(response.status_code, 409, response.text)
        for cidrs in (['8.8.8.0/24'], ['169.254.169.254/32'], ['x']):
            with self.subTest(cidrs=cidrs):
                response = await self.client.post(
                    '/harness/egress-destinations',
                    json=self.body('bad', cidrs=cidrs),
                )
                self.assertEqual(response.status_code, 422, response.text)
        path = f'/harness/egress-destinations/{self.slug("db")}'
        # A name change keeps the generation; a CIDR change does not.
        response = await self.client.patch(path, json={'name': 'Database'})
        self.assertEqual(response.json()['generation'], 1, response.text)
        response = await self.client.patch(
            path, json={'cidrs': ['10.8.1.0/24']}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['generation'], 2)
        self.assertEqual(response.json()['cidrs'], ['10.8.1.0/24'])
        response = await self.client.get(f'{path}/changes')
        self.assertEqual(
            [c['action'] for c in response.json()],
            ['updated', 'updated', 'created'],
        )
        # An agent that has it holds it.
        await self.make_agent(
            'db-user', settings={'egress_destinations': [self.slug('db')]}
        )
        response = await self.client.delete(path)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            response.json()['detail']['error'], 'egress_destination_in_use'
        )
        response = await self.client.get(path)
        self.assertEqual(
            response.json()['agents'],
            [{'organization_slug': self.org, 'slug': 'db-user'}],
        )

    async def test_delete_and_create_again_continues_generations(
        self,
    ) -> None:
        row = await self.destination('cache')
        self.act_as_user()
        self.user.is_admin = True
        path = f'/harness/egress-destinations/{row["slug"]}'
        response = await self.client.delete(path)
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual((await self.client.get(path)).status_code, 404)
        response = await self.client.post(
            '/harness/egress-destinations', json=self.body('cache')
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['generation'], 2)
        self.assertTrue(response.json()['pending'])

    async def test_port_pair_limit(self) -> None:
        self.act_as_user()
        self.user.is_admin = True
        ports = [{'port': p} for p in range(1, 21)]
        response = await self.client.post(
            '/harness/egress-destinations',
            json=self.body('a', cidrs=['10.250.0.0/24'], ports=ports),
        )
        self.assertEqual(response.status_code, 201, response.text)
        more = [{'port': p} for p in range(21, 26)]
        response = await self.client.post(
            '/harness/egress-destinations',
            json=self.body('b', cidrs=['10.250.0.0/24'], ports=more),
        )
        self.assertEqual(response.status_code, 422, response.text)

    async def test_members_list_what_their_agents_may_get(self) -> None:
        await self.destination('mine', organization_ids=[self.org])
        await self.destination('all')
        await self.destination('theirs', organization_ids=[self.other_org])
        await self.destination('everyone', is_global=True)
        self.act_as_user()
        response = await self.client.get(
            '/harness/egress-destinations', params={'organization': self.org}
        )
        self.assertEqual(response.status_code, 403, response.text)
        self.permissions.add('agent:read')
        response = await self.client.get('/harness/egress-destinations')
        self.assertEqual(response.status_code, 422, response.text)
        response = await self.client.get(
            '/harness/egress-destinations', params={'organization': self.org}
        )
        self.assertEqual(response.status_code, 200, response.text)
        slugs = {d['slug'] for d in response.json()}
        self.assertIn(self.slug('mine'), slugs)
        self.assertIn(self.slug('all'), slugs)
        self.assertNotIn(self.slug('theirs'), slugs)
        self.assertNotIn(self.slug('everyone'), slugs)
        self.assertTrue(all(d['agents'] == [] for d in response.json()))


class SyncApiTests(EgressTestCase):
    async def test_only_a_pool_account_syncs(self) -> None:
        response = await self.client.get('/harness/egress-sync')
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(
            response.json()['detail']['error'], 'egress_sync_forbidden'
        )

    async def test_report_applies_only_the_current_generation(self) -> None:
        row = await self.destination('api', applied=False)
        response = await self.as_pool('GET', '/harness/egress-sync')
        self.assertEqual(response.status_code, 200, response.text)
        found = {d['slug']: d for d in response.json()['destinations']}
        self.assertEqual(found[row['slug']]['generation'], 1)
        self.assertFalse(found[row['slug']]['deleted'])
        await self.harness.update_egress_destination(
            row['slug'], {'cidrs': ['10.9.1.0/24']}, 'test'
        )
        # A stale report changes nothing.
        response = await self.as_pool(
            'PUT',
            '/harness/egress-sync',
            json={'applied': [{'slug': row['slug'], 'generation': 1}]},
        )
        self.assertEqual(response.status_code, 204, response.text)
        current = await self.harness.egress_destination(row['slug'])
        assert current is not None
        self.assertIsNone(current['applied_generation'])
        response = await self.as_pool(
            'PUT',
            '/harness/egress-sync',
            json={'applied': [{'slug': row['slug'], 'generation': 2}]},
        )
        current = await self.harness.egress_destination(row['slug'])
        assert current is not None
        self.assertEqual(current['applied_generation'], 2)
        self.act_as_user()
        self.user.is_admin = True
        response = await self.client.get('/harness/egress-sync/status')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['synced_by'], self.pool_account.slug)


class ClaimEgressTests(EgressTestCase):
    async def test_claim_gives_applied_global_and_agent_destinations(
        self,
    ) -> None:
        mine = await self.destination('mine')
        everyone = await self.destination('everyone', is_global=True)
        waiting = await self.destination('waiting', applied=False)
        await self.destination('not-mine')
        await self.make_version(
            {
                'settings': {
                    'egress_destinations': [mine['slug'], waiting['slug']]
                }
            }
        )
        runner = await self.register()
        claim = await self.claim(runner)
        assert claim is not None
        granted = {g['slug']: g for g in claim['egress']}
        self.assertIn(mine['slug'], granted)
        self.assertIn(everyone['slug'], granted)
        self.assertNotIn(waiting['slug'], granted)
        self.assertNotIn(self.slug('not-mine'), granted)
        self.assertEqual(
            granted[mine['slug']],
            {
                'slug': mine['slug'],
                'generation': 1,
                'cidrs': ['10.9.0.0/24'],
                'ports': [{'port': 443, 'protocol': 'TCP'}],
            },
        )
        events = await self.store.events(
            uuid.UUID(claim['task']['id']), 0, 100
        )
        pending = [
            e['payload']
            for e in events
            if e['type'] == harness_api.EGRESS_PENDING_EVENT
        ]
        self.assertEqual(
            pending,
            [
                {
                    'slug': waiting['slug'],
                    'reason': 'not_applied',
                    'generation': 1,
                    'applied_generation': None,
                }
            ],
        )
        # The chain keeps the list: the runner list shows it.
        chain = await self.harness.chain(uuid.UUID(claim['chain_id']))
        assert chain is not None
        self.assertEqual(
            sorted(g['slug'] for g in chain['egress']), sorted(granted)
        )


class ChildEgressTests(EgressTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.held = await self.destination('held')
        self.other = await self.destination('other')
        self.helper_id = await self.make_agent(
            'helper',
            settings={'egress_destinations': [self.held['slug']]},
        )
        self.outsider_id = await self.make_agent(
            'outsider',
            settings={'egress_destinations': [self.other['slug']]},
        )
        await self.make_version(
            {
                'settings': {'egress_destinations': [self.held['slug']]},
                'subagents': [
                    {'agent_id': self.helper_id},
                    {'agent_id': self.outsider_id},
                ],
            }
        )
        self.runner = await self.register()
        claim = await self.claim(self.runner)
        assert claim is not None
        self.token: str = claim['agent_token']
        self.root_egress = claim['egress']

    async def child(self, agent_slug: str) -> typing.Any:
        return await self.client.post(
            '/harness/tasks/T-1/children',
            json={
                'agent_slug': agent_slug,
                'title': 'Help',
                'description': 'Help out.',
            },
            headers={'Authorization': f'Bearer {self.token}'},
        )

    async def test_child_needs_the_pod_destinations(self) -> None:
        response = await self.child('outsider')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            response.json()['detail']['error'], 'egress_destination_missing'
        )

    async def test_child_claim_gets_the_chain_egress(self) -> None:
        response = await self.child('helper')
        self.assertEqual(response.status_code, 201, response.text)
        response = await self.runner_post(self.runner, 'chain/claim')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['egress'], self.root_egress)


class AgentEgressTests(EgressTestCase):
    async def check(
        self, slugs: list[str], current: list[str] | None = None
    ) -> None:
        await agents_api._check_egress(
            self.harness,
            self.org,
            models.AgentSettings(egress_destinations=slugs),
            None
            if current is None
            else models.AgentSettings(egress_destinations=current),
        )

    async def test_new_destinations_are_checked(self) -> None:
        mine = await self.destination('mine', organization_ids=[self.org])
        theirs = await self.destination(
            'theirs', organization_ids=[self.other_org]
        )
        everyone = await self.destination('everyone', is_global=True)
        await self.check([mine['slug']])
        for slug in (theirs['slug'], everyone['slug'], self.slug('gone')):
            with (
                self.subTest(slug=slug),
                self.assertRaises(fastapi.HTTPException) as caught,
            ):
                await self.check([slug])
            self.assertEqual(caught.exception.status_code, 422)
        # A destination that the agent has already is not checked again.
        await self.check([theirs['slug']], current=[theirs['slug']])
