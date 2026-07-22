import datetime
from unittest import mock

from imbi_common.auth import core

from imbi_slackbot import identity, settings
from tests import helpers


class FakeSlack:
    def __init__(self, email: str | None) -> None:
        self._email = email
        self.calls = 0

    async def users_info(self, user: str) -> dict:
        self.calls += 1
        profile = {'email': self._email} if self._email else {}
        return {'user': {'profile': profile}}


class FakeGraph:
    def __init__(self, records: list) -> None:
        self._records = records
        self.calls = 0

    async def execute(self, query, params, columns) -> list:
        self.calls += 1
        return self._records


def _user_records(**fields) -> list:
    return [{'u': fields}]


class IdentityTestCase(helpers.TestCase):
    def setUp(self) -> None:
        super().setUp()
        identity.clear_cache()
        settings._slackbot_settings = None
        self._passthrough = mock.patch.object(
            identity.graph, 'parse_agtype', side_effect=lambda v: v
        )
        self._passthrough.start()

    def tearDown(self) -> None:
        self._passthrough.stop()
        identity.clear_cache()
        identity._graph = None
        settings._slackbot_settings = None
        super().tearDown()

    async def test_resolve_success(self) -> None:
        identity.set_graph(
            FakeGraph(
                _user_records(
                    is_active=True, display_name='Ada', is_admin=True
                )
            )
        )
        slack = FakeSlack('ada@example.com')
        user = await identity.resolve(slack, 'U1')
        assert user is not None
        self.assertEqual('ada@example.com', user.email)
        self.assertEqual('Ada', user.display_name)
        self.assertTrue(user.is_admin)

    async def test_resolve_is_cached(self) -> None:
        graph = FakeGraph(_user_records(is_active=True, display_name='Ada'))
        identity.set_graph(graph)
        slack = FakeSlack('ada@example.com')
        await identity.resolve(slack, 'U1')
        await identity.resolve(slack, 'U1')
        self.assertEqual(1, slack.calls)
        self.assertEqual(1, graph.calls)

    async def test_resolve_cache_expires(self) -> None:
        graph = FakeGraph(_user_records(is_active=True, display_name='Ada'))
        identity.set_graph(graph)
        slack = FakeSlack('ada@example.com')
        now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        await identity.resolve(slack, 'U1', now=now)
        later = now + datetime.timedelta(seconds=901)
        await identity.resolve(slack, 'U1', now=later)
        self.assertEqual(2, slack.calls)

    async def test_resolve_no_email(self) -> None:
        identity.set_graph(FakeGraph([]))
        slack = FakeSlack(None)
        user = await identity.resolve(slack, 'U1')
        self.assertIsNone(user)

    async def test_resolve_unknown_user(self) -> None:
        identity.set_graph(FakeGraph([]))
        slack = FakeSlack('nobody@example.com')
        user = await identity.resolve(slack, 'U1')
        self.assertIsNone(user)

    async def test_resolve_inactive_user(self) -> None:
        identity.set_graph(
            FakeGraph(_user_records(is_active=False, display_name='Old'))
        )
        slack = FakeSlack('old@example.com')
        user = await identity.resolve(slack, 'U1')
        self.assertIsNone(user)

    async def test_resolve_non_dict_node(self) -> None:
        self._passthrough.stop()
        with mock.patch.object(
            identity.graph, 'parse_agtype', return_value='oops'
        ):
            identity.set_graph(FakeGraph(_user_records(x=1)))
            slack = FakeSlack('a@example.com')
            user = await identity.resolve(slack, 'U1')
        self._passthrough.start()
        self.assertIsNone(user)

    async def test_load_without_graph_raises(self) -> None:
        identity._graph = None
        slack = FakeSlack('a@example.com')
        with self.assertRaises(RuntimeError):
            await identity.resolve(slack, 'U1')

    async def test_on_graph_ready_sets_graph(self) -> None:
        identity._graph = None
        graph = FakeGraph([])
        await identity.on_graph_ready(graph)
        self.assertIs(graph, identity._graph)

    def test_mint_token(self) -> None:
        token = identity.mint_token(
            identity.ImbiUser(email='a@example.com', display_name='A')
        )
        claims = core.verify_token(token)
        self.assertEqual('a@example.com', claims['sub'])
        self.assertEqual('access', claims['type'])
