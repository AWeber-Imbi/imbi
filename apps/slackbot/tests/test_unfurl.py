import contextlib
import typing
from collections import abc
from unittest import mock

from slack_sdk import errors

from apps.slackbot.tests import helpers, test_create_ticket
from imbi.slackbot import identity, settings, unfurl

USER = identity.ImbiUser('ada@example.com', 'Ada')
UI = 'https://imbi.example.com'
TICKET_URL = f'{UI}/tickets/acme/T-12/activity'
PROJECT_URL = f'{UI}/projects/p1'
TICKET = {
    'short_id': 'T-12',
    'title': 'Fix <login>',
    'status': 'running',
    'priority': 'high',
    'type': 'bug',
    'assignee': 'fixer',
    'team': {'name': 'Core'},
}
PROJECT = {
    'name': 'API',
    'description': 'The API\nmore text',
    'team': {'name': 'Core'},
    'project_types': [{'name': 'Service'}],
    'environments': [{'name': 'production'}],
    'archived': False,
}


class SettingsTestCase(helpers.TestCase):
    def setUp(self) -> None:
        super().setUp()
        settings._slackbot_settings = None
        self.enterContext(self.override_environment(IMBI_UI_URL=UI))

    def tearDown(self) -> None:
        settings._slackbot_settings = None
        super().tearDown()


class ParseTests(SettingsTestCase):
    def test_ticket(self) -> None:
        self.assertEqual(
            unfurl.Ticket('acme', 'T-12'), unfurl.parse(TICKET_URL)
        )

    def test_project_with_tab(self) -> None:
        self.assertEqual(
            unfurl.Project('p1'), unfurl.parse(f'{PROJECT_URL}/logs')
        )

    def test_not_imbi(self) -> None:
        for url in (
            'https://other.example.com/projects/p1',
            f'{UI}/reports/r1',
            f'{UI}/tickets/acme',
            f'{UI}/tickets/acme/new',
            f'{UI}/projects',
        ):
            with self.subTest(url=url):
                self.assertIsNone(unfurl.parse(url))

    def test_no_ui_url(self) -> None:
        settings._slackbot_settings = None
        with self.override_environment(IMBI_UI_URL=None):
            self.assertIsNone(unfurl.parse(TICKET_URL))


class BlockTests(helpers.TestCase):
    def test_ticket(self) -> None:
        self.assertEqual(
            [
                {
                    'type': 'section',
                    'text': {
                        'type': 'mrkdwn',
                        'text': f'*<{TICKET_URL}|T-12 · Fix &lt;login&gt;>*',
                    },
                },
                {
                    'type': 'context',
                    'elements': [
                        {
                            'type': 'mrkdwn',
                            'text': 'running · high · bug · fixer · Core',
                        }
                    ],
                },
            ],
            unfurl.ticket_blocks(TICKET, TICKET_URL),
        )

    def test_project(self) -> None:
        result = unfurl.project_blocks(
            {**PROJECT, 'archived': True}, PROJECT_URL
        )
        self.assertEqual(
            f'*<{PROJECT_URL}|API>*\nThe API', result[0]['text']['text']
        )
        self.assertEqual(
            'Core · Service · production · archived',
            result[1]['elements'][0]['text'],
        )


class HandleTests(SettingsTestCase, test_create_ticket.ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.slack = mock.AsyncMock()
        self.slack.conversations_info.return_value = {'channel': {}}
        self.resolve = mock.AsyncMock(return_value=USER)

    @contextlib.contextmanager
    def api(self) -> abc.Generator[None]:
        with (
            super().api(),
            mock.patch.object(identity, 'resolve', new=self.resolve),
        ):
            yield

    def ok(self, path: str, body: object) -> None:
        self.route('GET', path, 200, body)

    def event(self, *urls: str, **extra: str) -> dict[str, typing.Any]:
        return {
            'user': 'U1',
            'channel': 'C1',
            'source': 'conversations_history',
            'unfurl_id': 'X1',
            'links': [{'url': u, 'domain': 'imbi.example.com'} for u in urls],
            **extra,
        }

    async def test_ticket(self) -> None:
        self.ok('/organizations/acme/tickets/T-12', TICKET)
        with self.api():
            await unfurl.handle(self.event(TICKET_URL), self.slack)
        kwargs = self.slack.chat_unfurl.await_args.kwargs
        self.assertEqual('X1', kwargs['unfurl_id'])
        self.assertEqual('conversations_history', kwargs['source'])
        self.assertEqual(
            unfurl.ticket_blocks(TICKET, TICKET_URL),
            kwargs['unfurls'][TICKET_URL]['blocks'],
        )

    async def test_enterprise_event_targets_channel_and_ts(self) -> None:
        self.ok('/organizations/acme/tickets/T-12', TICKET)
        event = self.event(TICKET_URL, message_ts='1.2')
        del event['unfurl_id'], event['source']
        with self.api():
            await unfurl.handle(event, self.slack)
        kwargs = self.slack.chat_unfurl.await_args.kwargs
        self.assertEqual(('C1', '1.2'), (kwargs['channel'], kwargs['ts']))
        self.assertNotIn('unfurl_id', kwargs)

    async def test_project_in_second_org(self) -> None:
        self.ok('/organizations/', [{'slug': 'one'}, {'slug': 'two'}])
        self.ok('/organizations/two/projects/p1', PROJECT)
        with self.api():
            await unfurl.handle(self.event(PROJECT_URL), self.slack)
        unfurls = self.slack.chat_unfurl.await_args.kwargs['unfurls']
        self.assertEqual([PROJECT_URL], list(unfurls))

    async def test_unreadable_link_is_skipped(self) -> None:
        self.ok('/organizations/acme/tickets/T-12', TICKET)
        self.ok('/organizations/', [{'slug': 'acme'}])
        with self.api():
            await unfurl.handle(
                self.event(TICKET_URL, PROJECT_URL), self.slack
            )
        unfurls = self.slack.chat_unfurl.await_args.kwargs['unfurls']
        self.assertEqual([TICKET_URL], list(unfurls))

    async def test_nothing_readable(self) -> None:
        with self.api():
            await unfurl.handle(self.event(TICKET_URL), self.slack)
        self.slack.chat_unfurl.assert_not_awaited()

    async def test_no_imbi_item_makes_no_slack_call(self) -> None:
        with self.api():
            await unfurl.handle(self.event(f'{UI}/reports/r1'), self.slack)
        self.slack.conversations_info.assert_not_awaited()
        self.resolve.assert_not_awaited()

    async def test_unknown_user(self) -> None:
        self.resolve.return_value = None
        with self.api():
            await unfurl.handle(self.event(TICKET_URL), self.slack)
        self.slack.chat_unfurl.assert_not_awaited()

    async def test_no_card_outside_the_org(self) -> None:
        info_error = errors.SlackApiError('nope', {'ok': False})
        cases: dict[str, tuple[dict[str, str], object]] = {
            'composer': ({'source': 'composer'}, {'channel': {}}),
            'slack connect': ({}, {'channel': {'is_ext_shared': True}}),
            'pending': ({}, {'channel': {'is_pending_ext_shared': True}}),
            'info error': ({}, info_error),
        }
        for name, (extra, info) in cases.items():
            with self.subTest(name):
                self.slack.reset_mock()
                self.resolve.reset_mock()
                self.slack.conversations_info.side_effect = [info]
                with self.api():
                    await unfurl.handle(
                        self.event(TICKET_URL, **extra), self.slack
                    )
                self.resolve.assert_not_awaited()
                self.slack.chat_unfurl.assert_not_awaited()

    async def test_unfurl_error_is_swallowed(self) -> None:
        self.ok('/organizations/acme/tickets/T-12', TICKET)
        self.slack.chat_unfurl.side_effect = errors.SlackApiError(
            'nope', {'ok': False}
        )
        with self.api():
            await unfurl.handle(self.event(TICKET_URL), self.slack)
