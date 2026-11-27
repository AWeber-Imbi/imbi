import datetime
from unittest import mock

from apps.slackbot.tests import helpers
from imbi.common.auth import core
from imbi.slackbot import identity, settings


class FakeSlack:
    def __init__(self, email: str | None) -> None:
        self._email = email
        self.calls = 0

    async def users_info(self, user: str) -> dict:
        self.calls += 1
        profile = {'email': self._email} if self._email else {}
        return {'user': {'profile': profile, 'tz': 'America/New_York'}}


class FakeGraph:
    def __init__(self, records: list, workspace: list | None = None) -> None:
        self._records = records
        self._workspace = (
            [{'slug': 'acme'}] if workspace is None else workspace
        )
        self.calls = 0

    async def execute(self, query, params, columns) -> list:
        self.calls += 1
        if query is identity._WORKSPACE_ORG_QUERY:
            return self._workspace
        return self._records


def _user_records(slug: str | None = 'acme', **fields) -> list:
    """A user row; ``slug`` is the workspace org when a member."""
    return [{'u': fields, 'slug': slug}]


class IdentityTestCase(helpers.TestCase):
    def setUp(self) -> None:
        super().setUp()
        identity.clear_cache()
        identity.set_team_id('T1')
        settings._slackbot_settings = None
        self._passthrough = mock.patch.object(
            identity.graph, 'parse_agtype', side_effect=lambda v: v
        )
        self._passthrough.start()

    def tearDown(self) -> None:
        self._passthrough.stop()
        identity.clear_cache()
        identity._graph = None
        identity.set_team_id(None)
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
        self.assertEqual('America/New_York', user and user.tz)
        assert user is not None
        self.assertEqual('ada@example.com', user.email)
        self.assertEqual('Ada', user.display_name)
        self.assertTrue(user.is_admin)
        self.assertEqual('acme', user.org_slug)

    async def test_resolve_needs_the_workspace_org(self) -> None:
        # Not a member of the organization with the workspace's team id
        # (or no organization has it): the query gives no slug.
        identity.set_graph(
            FakeGraph(
                _user_records(slug=None, is_active=True, display_name='Ada')
            )
        )
        self.assertIsNone(
            await identity.resolve(FakeSlack('ada@example.com'), 'U1')
        )

    async def test_workspace_org_slug_is_cached(self) -> None:
        graph = FakeGraph([])
        identity.set_graph(graph)
        now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        self.assertEqual('acme', await identity.workspace_org_slug(now=now))
        self.assertEqual('acme', await identity.workspace_org_slug(now=now))
        self.assertEqual(1, graph.calls)
        later = now + datetime.timedelta(seconds=901)
        await identity.workspace_org_slug(now=later)
        self.assertEqual(2, graph.calls)

    async def test_unlinked_workspace_has_no_org(self) -> None:
        identity.set_graph(FakeGraph([], workspace=[]))
        self.assertIsNone(await identity.workspace_org_slug())

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
            identity.ImbiUser(
                email='a@example.com', display_name='A', org_slug='acme'
            )
        )
        claims = core.verify_token(token)
        self.assertEqual('a@example.com', claims['sub'])
        self.assertEqual('access', claims['type'])
        self.assertEqual('slack', claims['channel'])
