"""Tests for the egress destinations, the egress sync routes, and the
egress allowlist of a claim (harness egress PRD).

The destinations are platform-wide, so each test uses slugs with the
suffix of its organization and deletes them at the end.
"""

import json
import pathlib
import typing
import unittest
import uuid
from unittest import mock

import fastapi
import jwt

from apps.api.tests.endpoints import test_harness
from imbi.api import settings as api_settings
from imbi.api.endpoints import agents as agents_api
from imbi.api.endpoints import harness as harness_api
from imbi.api.harness import egress, tokens
from imbi.common import models

#: The C4 contract fixture that the egress proxy tests read too.
CONTRACT = json.loads(
    (
        pathlib.Path(__file__).parents[4] / 'proxy' / 'tests' / 'contract.json'
    ).read_text()
)
PROXY_KEY = 'test-proxy-key-0123456789abcdef0123456789abcdef'


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


class HostnameTests(unittest.TestCase):
    def test_canonical_sorted_and_unique(self) -> None:
        self.assertEqual(
            egress.check_hostnames(
                [
                    'Zoekt.PSE.Example.Cloud',
                    'zoekt.pse.example.cloud.',
                    'bücher.example.com',
                ]
            ),
            ['xn--bcher-kva.example.com', 'zoekt.pse.example.cloud'],
        )

    def test_refused(self) -> None:
        for name in (
            '10.1.2.3',
            '0x0a.1',
            '::1',
            '[::1]',
            'localhost',
            '*.example.com',
            'user@git.example.com',
            'git.example.com/path',
            'git.example.com:443',
            'a..example.com',
            '-a.example.com',
            '',
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                egress.check_hostnames([name])

    def test_count(self) -> None:
        with self.assertRaises(ValueError):
            egress.check_hostnames([])
        too_many = [
            f'h{n}.example.com' for n in range(egress.MAX_HOSTNAMES + 1)
        ]
        with self.assertRaises(ValueError):
            egress.check_hostnames(too_many)

    def test_kind(self) -> None:
        https = [egress.EgressPort(port=443)]
        egress.check_kind(['10.0.0.0/24'], [], https)
        egress.check_kind([], ['a.example.com'], [{'port': 443}])
        for cidrs, hostnames, ports in (
            (['10.0.0.0/24'], ['a.example.com'], https),
            ([], [], https),
            ([], ['a.example.com'], [egress.EgressPort(port=8443)]),
            (
                [],
                ['a.example.com'],
                [egress.EgressPort(port=443, protocol='UDP')],
            ),
            (
                [],
                ['a.example.com'],
                [*https, egress.EgressPort(port=80)],
            ),
        ):
            with (
                self.subTest(cidrs=cidrs, hostnames=hostnames, ports=ports),
                self.assertRaises(ValueError),
            ):
                egress.check_kind(cidrs, hostnames, ports)

    def test_no_port_pairs_without_cidrs(self) -> None:
        self.assertEqual(
            egress.port_pairs_over_limit(
                [
                    {
                        'cidrs': [],
                        'ports': [
                            {'port': p, 'protocol': 'TCP'} for p in range(99)
                        ],
                    }
                ]
            ),
            [],
        )


def grant(cidrs: list[str], *tcp: int, udp: int | None = None) -> egress.Grant:
    """A CIDR grant with the TCP ports ``tcp`` and one UDP port."""
    ports = [egress.EgressPort(port=port) for port in tcp]
    if udp is not None:
        ports.append(egress.EgressPort(port=udp, protocol='UDP'))
    return egress.Grant(slug='g', generation=1, cidrs=cidrs, ports=ports)


class ProxyCidrsTests(unittest.TestCase):
    def test_merge_and_sort(self) -> None:
        self.assertEqual(
            egress.proxy_cidrs(
                [
                    grant(['10.10.0.0/16', '10.9.0.0/24'], 8443, 443),
                    grant(['10.10.0.0/16'], 22, 443, udp=53),
                    grant(['10.8.0.0/24'], 443, 8443),
                ]
            ),
            [
                {'nets': ['10.10.0.0/16'], 'ports': [22, 443, 8443]},
                {'nets': ['10.8.0.0/24', '10.9.0.0/24'], 'ports': [443, 8443]},
            ],
        )

    def test_largest_destination_fits(self) -> None:
        # 25 CIDRs of the longest form and 24 five-digit TCP ports.
        cidrs = [f'192.168.{n}.128/25' for n in range(100, 125)]
        cidrs = egress.proxy_cidrs([grant(cidrs, *range(65500, 65524))])
        token = tokens.mint_proxy_token(
            PROXY_KEY,
            chain_id=uuid.uuid4(),
            attempt=1,
            pod=uuid.uuid4(),
            hosts=[],
            cidrs=cidrs,
        )
        self.assertLess(len(token), tokens.MAX_PROXY_TOKEN_BYTES)

    def test_udp_only_left_out(self) -> None:
        self.assertEqual(
            egress.proxy_cidrs([grant(['10.9.0.0/24'], udp=53)]), []
        )
        self.assertEqual(egress.proxy_cidrs([]), [])


class ContractTests(unittest.TestCase):
    """The C4 contract with the egress proxy."""

    def test_mint_makes_the_valid_token(self) -> None:
        (valid,) = [t for t in CONTRACT['tokens'] if t['name'] == 'valid']
        claims = valid['claims']
        # Grants out of order, split, and with UDP: the claim is the same.
        cidrs = egress.proxy_cidrs(
            [
                grant(['10.40.0.0/16', '10.20.0.0/16'], 8443),
                grant(['10.30.1.0/24'], 22, udp=53),
                grant(['10.20.0.0/16', '10.40.0.0/16'], 443),
            ]
        )
        self.assertEqual(cidrs, claims['cidrs'])
        self.assertEqual(
            tokens.mint_proxy_token(
                CONTRACT['keys'][valid['key']],
                chain_id=claims['chain'],
                attempt=claims['attempt'],
                pod=claims['pod'],
                hosts=list(reversed(claims['hosts'])),
                cidrs=cidrs,
                now=claims['iat'],
                ttl=claims['exp'] - claims['iat'],
            ),
            valid['token'],
        )

    def test_targets(self) -> None:
        for target in CONTRACT['targets']:
            host, _, port = target['target'].rpartition(':')
            with self.subTest(target=target['target']):
                if target['expect'] == 'ok':
                    self.assertEqual(
                        egress.canonical_hostname(host), target['host']
                    )
                elif port.isdigit() and 1 <= int(port) <= 65535:
                    # Only the name is wrong: the API refuses it too.
                    with self.assertRaises(ValueError):
                        egress.check_hostnames([host])


class GrantTests(unittest.TestCase):
    @staticmethod
    def row(slug: str, **values: typing.Any) -> dict[str, typing.Any]:
        return {
            'slug': slug,
            'cidrs': ['10.0.0.0/24'],
            'hostnames': [],
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

    def test_hostnames(self) -> None:
        rows = [self.row('h', cidrs=[], hostnames=['a.example.com'])]
        grants, _pending = egress.grants(rows, ['h'], 'org')
        self.assertEqual(grants[0].hostnames, ['a.example.com'])
        self.assertEqual(grants[0].cidrs, [])


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
                'hostnames': [],
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

    async def proxied(
        self, name: str, hostnames: list[str], **values: typing.Any
    ) -> dict[str, typing.Any]:
        """A host name destination: applied at once, with no sync."""
        return await self.destination(
            name, applied=False, cidrs=[], hostnames=hostnames, **values
        )

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

    async def test_hostname_destinations(self) -> None:
        self.act_as_user()
        self.user.is_admin = True
        https = [{'port': 443}]
        names = ['Git.Example.COM.', 'bücher.example.com']
        for body in (
            self.body('bad', hostnames=names),  # also CIDRs
            self.body('bad', cidrs=[], ports=https),  # neither
            self.body('bad', cidrs=[], hostnames=names),  # not 443
            self.body(
                'bad', cidrs=[], hostnames=['*.example.com'], ports=https
            ),
            self.body('bad', cidrs=[], hostnames=['10.1.2.3'], ports=https),
            self.body('bad', cidrs=[], hostnames=['localhost'], ports=https),
        ):
            with self.subTest(body=body):
                response = await self.client.post(
                    '/harness/egress-destinations', json=body
                )
                self.assertEqual(response.status_code, 422, response.text)
        body = self.body('git', hostnames=names, ports=https)
        del body['cidrs']
        response = await self.client.post(
            '/harness/egress-destinations', json=body
        )
        self.assertEqual(response.status_code, 201, response.text)
        created = response.json()
        self.assertEqual(
            created['hostnames'],
            ['git.example.com', 'xn--bcher-kva.example.com'],
        )
        self.assertEqual(created['cidrs'], [])
        self.assertEqual(created['ports'], [{'port': 443, 'protocol': 'TCP'}])
        self.assertEqual(created['applied_generation'], 1)
        self.assertFalse(created['pending'])
        path = f'/harness/egress-destinations/{self.slug("git")}'
        # A host name change starts a generation that is applied at once.
        response = await self.client.patch(
            path, json={'hostnames': ['git.example.com']}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['generation'], 2)
        self.assertEqual(response.json()['applied_generation'], 2)
        # Other ports, or CIDRs too, are refused.
        for change in (
            {'ports': [{'port': 8443}]},
            {'cidrs': ['10.8.0.0/16']},
            {'hostnames': []},
        ):
            with self.subTest(change=change):
                response = await self.client.patch(path, json=change)
                self.assertEqual(response.status_code, 422, response.text)
        # To CIDRs: a new generation that waits for the sync.
        response = await self.client.patch(
            path, json={'hostnames': [], 'cidrs': ['10.8.0.0/16']}
        )
        self.assertEqual(response.status_code, 200, response.text)
        changed = response.json()
        self.assertEqual(changed['generation'], 3)
        self.assertEqual(changed['applied_generation'], 2)
        self.assertTrue(changed['pending'])
        self.assertEqual(changed['hostnames'], [])
        # And back: applied at once again.
        response = await self.client.patch(
            path, json={'hostnames': ['git.example.com'], 'cidrs': []}
        )
        self.assertEqual(response.json()['generation'], 4, response.text)
        self.assertFalse(response.json()['pending'])

    async def test_hostname_destination_created_again(self) -> None:
        row = await self.destination('cache')
        await self.harness.delete_egress_destination(row['slug'], 'test')
        row = await self.proxied('cache', ['cache.example.com'])
        self.assertEqual(row['generation'], 2)
        self.assertEqual(row['applied_generation'], 2)

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

    async def test_sync_leaves_out_hostname_destinations(self) -> None:
        proxied = await self.proxied('proxied', ['a.example.com'])
        moved = await self.destination('moved')
        response = await self.as_pool('GET', '/harness/egress-sync')
        found = {d['slug'] for d in response.json()['destinations']}
        self.assertNotIn(proxied['slug'], found)
        self.assertIn(moved['slug'], found)
        # A destination that changes to host names leaves the list, so
        # the sync deletes its old policies.
        await self.harness.update_egress_destination(
            moved['slug'],
            {'cidrs': [], 'hostnames': ['b.example.com']},
            'test',
        )
        response = await self.as_pool('GET', '/harness/egress-sync')
        found = {d['slug'] for d in response.json()['destinations']}
        self.assertNotIn(moved['slug'], found)


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
                'hostnames': [],
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


class ProxyTokenTests(EgressTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.pod = uuid.uuid4()
        patcher = mock.patch.object(
            api_settings,
            '_harness_egress_proxy',
            api_settings.HarnessEgressProxy(secret=PROXY_KEY),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def use(self, *slugs: str) -> None:
        await self.make_version({'settings': {'egress_destinations': slugs}})

    async def claim_with_pod(
        self, runner: dict[str, typing.Any], path: str = 'claim'
    ) -> typing.Any:
        return await self.runner_post(
            runner, path, params={'pod': str(self.pod)}
        )

    async def test_token_has_the_hosts_of_the_grants(self) -> None:
        git = await self.proxied('git', ['git.example.com'])
        search = await self.proxied('search', ['search.example.com'])
        await self.proxied(
            'everyone', ['all.example.com', 'git.example.com'], is_global=True
        )
        db = await self.destination('db')
        await self.use(git['slug'], search['slug'], db['slug'])
        response = await self.claim_with_pod(await self.register())
        self.assertEqual(response.status_code, 200, response.text)
        claim = response.json()
        granted = {g['slug']: g for g in claim['egress']}
        self.assertEqual(
            granted[git['slug']]['hostnames'], ['git.example.com']
        )
        self.assertEqual(granted[db['slug']]['hostnames'], [])
        claims = jwt.decode(
            claim['proxy_token'],
            PROXY_KEY,
            algorithms=['HS256'],
            audience=tokens.PROXY_AUDIENCE,
            issuer=tokens.PROXY_ISSUER,
        )
        self.assertEqual(
            list(claims),
            [
                'iss',
                'aud',
                'iat',
                'exp',
                'chain',
                'attempt',
                'pod',
                'hosts',
                'cidrs',
            ],
        )
        self.assertIn(
            '10.9.0.0/24', [n for c in claims['cidrs'] for n in c['nets']]
        )
        self.assertEqual(
            claims['exp'] - claims['iat'], tokens.AGENT_TOKEN_TTL_SECONDS
        )
        self.assertEqual(claims['chain'], claim['chain_id'])
        self.assertEqual(claims['attempt'], claim['attempt'])
        self.assertEqual(claims['pod'], str(self.pod))
        # Other tests may add global host name destinations.
        self.assertLessEqual(
            {'all.example.com', 'git.example.com', 'search.example.com'},
            set(claims['hosts']),
        )
        self.assertEqual(claims['hosts'], sorted(set(claims['hosts'])))

    async def test_no_token_without_pod(self) -> None:
        git = await self.proxied('git', ['git.example.com'])
        await self.use(git['slug'])
        runner = await self.register()
        response = await self.runner_post(
            runner, 'claim', params={'pod': 'not-a-uuid'}
        )
        self.assertEqual(response.status_code, 422, response.text)
        response = await self.runner_post(runner, 'claim')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()['proxy_token'])

    async def test_no_token_without_secret(self) -> None:
        git = await self.proxied('git', ['git.example.com'])
        await self.use(git['slug'])
        with mock.patch.object(
            api_settings,
            '_harness_egress_proxy',
            api_settings.HarnessEgressProxy(secret=''),
        ):
            response = await self.claim_with_pod(await self.register())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()['proxy_token'])

    async def test_cidr_only_chain_gets_a_token(self) -> None:
        cidr_only = [grant(['10.9.0.0/24'], 5432)]
        with mock.patch.object(
            harness_api, '_root_egress', return_value=cidr_only
        ):
            response = await self.claim_with_pod(await self.register())
        self.assertEqual(response.status_code, 200, response.text)
        claims = jwt.decode(
            response.json()['proxy_token'],
            PROXY_KEY,
            algorithms=['HS256'],
            audience=tokens.PROXY_AUDIENCE,
        )
        self.assertEqual(claims['hosts'], [])
        self.assertEqual(
            claims['cidrs'], [{'nets': ['10.9.0.0/24'], 'ports': [5432]}]
        )

    async def assert_no_token(self, egress_: list[egress.Grant]) -> None:
        with mock.patch.object(
            harness_api, '_root_egress', return_value=egress_
        ):
            response = await self.claim_with_pod(await self.register())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()['proxy_token'])

    async def test_no_token_without_egress(self) -> None:
        await self.assert_no_token([])

    async def test_no_token_for_udp_only_cidrs(self) -> None:
        await self.assert_no_token([grant(['10.9.0.0/24'], udp=53)])

    async def test_child_claim_gets_a_token(self) -> None:
        git = await self.proxied('git', ['git.example.com'])
        helper = await self.make_agent(
            'helper', settings={'egress_destinations': [git['slug']]}
        )
        await self.make_version(
            {
                'settings': {'egress_destinations': [git['slug']]},
                'subagents': [{'agent_id': helper}],
            }
        )
        runner = await self.register()
        claim = (await self.claim_with_pod(runner)).json()
        response = await self.client.post(
            '/harness/tasks/T-1/children',
            json={
                'agent_slug': 'helper',
                'title': 'Help',
                'description': 'Help out.',
            },
            headers={'Authorization': f'Bearer {claim["agent_token"]}'},
        )
        self.assertEqual(response.status_code, 201, response.text)
        response = await self.claim_with_pod(runner, 'chain/claim')
        self.assertEqual(response.status_code, 200, response.text)
        child = jwt.decode(
            response.json()['proxy_token'],
            PROXY_KEY,
            algorithms=['HS256'],
            audience=tokens.PROXY_AUDIENCE,
        )
        self.assertIn('git.example.com', child['hosts'])
        self.assertEqual(child['chain'], claim['chain_id'])

    async def test_too_large_token_fails_the_task(self) -> None:
        # 25 names of 247 characters: the token is over 4 KiB.
        names = [
            f'{n:02d}{"a" * 58}.{"b" * 60}.{"c" * 60}.{"d" * 60}.com'
            for n in range(egress.MAX_HOSTNAMES)
        ]
        big = await self.proxied('big', names)
        await self.use(big['slug'])
        runner = await self.register()
        response = await self.claim_with_pod(runner)
        self.assertEqual(response.status_code, 204, response.text)
        task = await self.task_row()
        self.assertEqual(task['status'], 'closed')
        self.assertEqual(task['outcome'], 'exceeded_ceiling')
        self.assertEqual(task['outcome_reason'], 'egress_token_too_large')
        (row,) = [
            r
            for r in await self.harness.runners([self.pool_name])
            if str(r['id']) == runner['runner_id']
        ]
        self.assertEqual(row['state'], 'idle')


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
