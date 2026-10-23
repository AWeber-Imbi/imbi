"""The egress self-test, readiness probe, and policy sync (PRD 5.3,
5.6, 5.7)."""

import socket
import typing
import unittest
from unittest import mock

import respx

from imbi.harness import egress, kube

POLICIES = kube.API + egress.POLICIES
PODS = f'{kube.API}/api/v1/namespaces/imbi-runners/pods'


def destination(
    slug: str = 'db', generation: int = 2, *, deleted: bool = False
) -> dict[str, typing.Any]:
    return {
        'slug': slug,
        'generation': generation,
        'cidrs': ['10.1.0.0/16'],
        'ports': [{'port': 5432, 'protocol': 'TCP'}],
        'deleted': deleted,
    }


def managed(name: str) -> dict[str, typing.Any]:
    return {
        'metadata': {
            'name': name,
            'labels': {'app.kubernetes.io/managed-by': egress.MANAGED_BY},
        }
    }


class PlanTestCase(unittest.TestCase):
    def test_creates_a_new_generation(self) -> None:
        result = egress.plan([destination()], [], set())
        self.assertEqual(result.create, [destination()])
        self.assertEqual(result.applied, [])
        self.assertEqual(result.delete, [])

    def test_reports_an_existing_policy(self) -> None:
        result = egress.plan(
            [destination()], [managed('imbi-harness-dest-db-g2')], set()
        )
        self.assertEqual(result.create, [])
        self.assertEqual(result.applied, [{'slug': 'db', 'generation': 2}])

    def test_keeps_an_old_generation_while_a_pod_holds_it(self) -> None:
        policies = [
            managed('imbi-harness-dest-db-g1'),
            managed('imbi-harness-dest-db-g2'),
        ]
        held = {('egress.imbi.aweber.com/db', 'g1')}
        result = egress.plan([destination()], policies, held)
        self.assertEqual(result.delete, [])
        # Then the pod ends.
        result = egress.plan([destination()], policies, set())
        self.assertEqual(result.delete, ['imbi-harness-dest-db-g1'])

    def test_deleted_destination(self) -> None:
        policies = [managed('imbi-harness-dest-db-g2')]
        deleted = [destination(deleted=True)]
        result = egress.plan(
            deleted, policies, {('egress.imbi.aweber.com/db', 'g2')}
        )
        self.assertEqual((result.create, result.delete), ([], []))
        result = egress.plan(deleted, policies, set())
        self.assertEqual(result.delete, ['imbi-harness-dest-db-g2'])
        self.assertEqual(result.applied, [])

    def test_slug_with_a_generation_like_part(self) -> None:
        policies = [managed('imbi-harness-dest-db-g7-g1')]
        held = {('egress.imbi.aweber.com/db-g7', 'g1')}
        self.assertEqual(egress.plan([], policies, held).delete, [])

    def test_never_touches_unmanaged_policies(self) -> None:
        policies = [
            {'metadata': {'name': 'imbi-harness-dest-db-g1'}},
            {
                'metadata': {
                    'name': 'imbi-harness-required',
                    'labels': {'app.kubernetes.io/managed-by': 'Helm'},
                }
            },
        ]
        result = egress.plan([], policies, set())
        self.assertEqual(result.delete, [])

    def test_held_labels_skip_ended_pods(self) -> None:
        pods = [
            {
                'metadata': {
                    'labels': {
                        'egress.imbi.aweber.com/db': 'g1',
                        'imbi.aweber.com/pool': 'general',
                    }
                },
                'status': {'phase': 'Running'},
            },
            {
                'metadata': {'labels': {'egress.imbi.aweber.com/x': 'g3'}},
                'status': {'phase': 'Succeeded'},
            },
        ]
        self.assertEqual(
            egress.held_labels(pods), {('egress.imbi.aweber.com/db', 'g1')}
        )

    def test_policy(self) -> None:
        body = egress.policy(destination(), 'imbi-runners')
        self.assertEqual(body['metadata']['name'], 'imbi-harness-dest-db-g2')
        spec = body['spec']
        self.assertEqual((spec['tier'], spec['priority']), ('Admin', 200))
        self.assertEqual(
            spec['subject']['pods']['podSelector']['matchLabels'],
            {
                'app.kubernetes.io/name': 'imbi-harness',
                'egress.imbi.aweber.com/db': 'g2',
            },
        )
        self.assertEqual(
            spec['egress'],
            [
                {
                    'name': 'db',
                    'action': 'Accept',
                    'to': [{'networks': ['10.1.0.0/16']}],
                    'ports': [
                        {'portNumber': {'port': 5432, 'protocol': 'TCP'}}
                    ],
                }
            ],
        )

    def test_labels(self) -> None:
        self.assertEqual(
            egress.labels([destination(), destination('web', 1)]),
            {
                'egress.imbi.aweber.com/db': 'g2',
                'egress.imbi.aweber.com/web': 'g1',
            },
        )


class SelfTestTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        for name in ('sleep',):
            patcher = mock.patch.object(egress.asyncio, name, mock.AsyncMock())
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_passes_when_both_fail(self) -> None:
        answers = mock.AsyncMock(side_effect=[True, False, False, False])
        with mock.patch.object(egress, 'answers', answers):
            await egress.self_test(('10.0.0.9', 5432))
        answers.assert_any_await('169.254.169.254', 80)
        answers.assert_any_await('10.0.0.9', 5432)

    async def test_exits_when_not_enforced(self) -> None:
        clock = iter(range(0, 1000, 20))
        with (
            mock.patch.object(
                egress, 'answers', mock.AsyncMock(return_value=True)
            ),
            mock.patch.object(
                egress.time, 'monotonic', side_effect=lambda: next(clock)
            ),
            self.assertRaisesRegex(SystemExit, 'not enforced'),
        ):
            await egress.self_test(('10.0.0.9', 5432))

    async def test_answers(self) -> None:
        for error, expected in (
            (ConnectionRefusedError(), True),
            (TimeoutError(), False),
            (OSError(113, 'No route to host'), False),
        ):
            with (
                self.subTest(error=error),
                mock.patch.object(
                    egress.asyncio,
                    'open_connection',
                    mock.AsyncMock(side_effect=error),
                ),
            ):
                self.assertIs(await egress.answers('10.0.0.9', 1), expected)

    async def test_answers_exits_when_not_resolved(self) -> None:
        with (
            mock.patch.object(
                egress.asyncio,
                'open_connection',
                mock.AsyncMock(side_effect=socket.gaierror('no')),
            ),
            self.assertRaisesRegex(SystemExit, 'does not resolve'),
        ):
            await egress.answers('canary.invalid', 1)


class ProbeTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_reports_what_did_not_connect(self) -> None:
        udp = {
            **destination('dns'),
            'ports': [{'port': 53, 'protocol': 'UDP'}],
        }
        host = {**destination('one'), 'cidrs': ['10.5.0.7/32']}
        reached = {'10.5.0.7'}

        async def connects(address: str, _port: int) -> bool:
            return address in reached

        clock = iter(range(0, 1000, 20))
        with (
            mock.patch.object(egress, 'connects', connects),
            mock.patch.object(egress.asyncio, 'sleep', mock.AsyncMock()),
            mock.patch.object(
                egress.time, 'monotonic', side_effect=lambda: next(clock)
            ),
        ):
            self.assertEqual(
                await egress.probe([destination(), udp, host]), ['db']
            )
            self.assertEqual(await egress.probe([]), [])


class SyncRoundTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_round(self) -> None:
        sync = egress.Sync(
            'http://imbi.test', ('id', 'secret'), 'imbi-runners'
        )
        sync.api = mock.AsyncMock()
        sync.api.pool_token.return_value = 'pool-token'
        sync.api.egress_destinations.return_value = [
            destination('db', 2),
            destination('web', 1),
            destination('old', 1, deleted=True),
        ]
        with (
            mock.patch.object(
                egress.pathlib.Path, 'read_text', return_value='sa-token\n'
            ),
            mock.patch.object(egress.ssl, 'create_default_context'),
            respx.mock(assert_all_called=True) as router,
        ):
            router.get(POLICIES).respond(
                200,
                json={
                    'items': [
                        managed('imbi-harness-dest-web-g1'),
                        managed('imbi-harness-dest-old-g1'),
                    ]
                },
            )
            router.get(PODS).respond(200, json={'items': []})
            create = router.post(POLICIES).respond(201, json={})
            delete = router.delete(
                f'{POLICIES}/imbi-harness-dest-old-g1'
            ).respond(200, json={})
            await sync.round()
        self.assertEqual(
            create.calls.last.request.headers['Authorization'],
            'Bearer sa-token',
        )
        self.assertTrue(delete.called)
        sync.api.report_applied.assert_awaited_once_with(
            'pool-token',
            [
                {'slug': 'web', 'generation': 1},
                {'slug': 'db', 'generation': 2},
            ],
        )
