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
    'status': 'in_progress',
    'priority': 'high',
    'type': 'bug',
    'assignee': 'fixer',
    'team': {'name': 'Core'},
}
PROJECT: dict[str, typing.Any] = {
    'id': 'p1',
    'name': 'Admin v1',
    'slug': 'admin',
    'description': ' Administrative interface ',
    'team': {'name': 'Backend'},
    'project_types': [{'name': 'Web Application', 'deployable': True}],
    'environments': [
        {'name': 'Production', 'slug': 'prod', 'sort_order': 3},
        {'name': 'Testing', 'slug': 'test', 'sort_order': 1},
        {'name': 'Staging', 'slug': 'stage', 'sort_order': 2},
    ],
    'current_releases': {
        'prod': {'tag': '3.46.4', 'deployed_at': '2026-11-24T17:00:00+00:00'}
    },
    'drift_pairs': [
        {
            'head': {'name': 'Testing', 'slug': 'test'},
            'base': {'name': 'Staging', 'slug': 'stage'},
            'oldest': '2026-10-01T00:00:00',
        }
    ],
    'score': 44.2,
    'has_deployment_plugin': True,
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


def fields_by_key(entity: dict[str, typing.Any]) -> dict[str, typing.Any]:
    return {f['key']: f for f in entity['entity_payload']['custom_fields']}


class EntityRefTests(SettingsTestCase):
    def test_equivalent_links_share_a_ref(self) -> None:
        cases = {
            'ticket': (
                lambda u: unfurl.ticket_entity(TICKET, u, 'acme'),
                TICKET_URL,
                f'{UI}/tickets/acme/T-12?tab=x#y',
                {'id': 'acme/T-12', 'type': 'ticket'},
                f'{UI}/tickets/acme/T-12',
            ),
            'project': (
                lambda u: unfurl.project_entity(PROJECT, u),
                PROJECT_URL,
                f'{PROJECT_URL}/logs',
                {'id': 'p1', 'type': 'project'},
                PROJECT_URL,
            ),
        }
        for name, (build, first, second, ref, canonical) in cases.items():
            with self.subTest(name):
                a, b = build(first), build(second)
                self.assertEqual(ref, a['external_ref'])
                self.assertEqual(a['external_ref'], b['external_ref'])
                self.assertEqual((canonical, canonical), (a['url'], b['url']))
                self.assertEqual(second, b['app_unfurl_url'])


class TicketEntityTests(SettingsTestCase):
    def test_ticket(self) -> None:
        entity = unfurl.ticket_entity(
            {**TICKET, 'assignee': 'ada@example.com'}, TICKET_URL, 'acme'
        )
        self.assertEqual('slack#/entities/task', entity['entity_type'])
        self.assertEqual(TICKET_URL, entity['app_unfurl_url'])
        payload = entity['entity_payload']
        self.assertEqual(
            {
                'title': {'text': 'Fix <login>'},
                'display_type': 'Bug',
                'display_id': 'T-12',
                'product_name': 'Imbi',
                'product_icon': {'url': unfurl.LOGO_URL, 'alt_text': 'Imbi'},
            },
            payload['attributes'],
        )
        self.assertEqual(
            {
                'status': {'value': 'In Progress', 'tag_color': 'yellow'},
                'priority': {'value': 'High'},
                'assignee': {
                    'type': 'slack#/types/user',
                    'user': {
                        'text': 'ada@example.com',
                        'email': 'ada@example.com',
                    },
                },
            },
            payload['fields'],
        )
        [button] = payload['actions']['primary_actions']
        self.assertEqual(
            ('primary', TICKET_URL), (button['style'], button['url'])
        )
        self.assertTrue(button['action_id'].startswith(unfurl.ACTION_PREFIX))

    def test_ticket_without_assignee_or_type(self) -> None:
        entity = unfurl.ticket_entity(
            {**TICKET, 'assignee': None, 'type': None, 'status': 'odd'},
            TICKET_URL,
            'acme',
        )
        payload = entity['entity_payload']
        self.assertNotIn('assignee', payload['fields'])
        self.assertEqual('gray', payload['fields']['status']['tag_color'])
        self.assertEqual('Ticket', payload['attributes']['display_type'])


class ProjectEntityTests(SettingsTestCase):
    def test_project(self) -> None:
        entity = unfurl.project_entity(PROJECT, PROJECT_URL)
        self.assertEqual('slack#/entities/item', entity['entity_type'])
        attributes = entity['entity_payload']['attributes']
        self.assertEqual(
            ('Admin v1', 'Project', 'admin'),
            (
                attributes['title']['text'],
                attributes['display_type'],
                attributes['display_id'],
            ),
        )
        fields = fields_by_key(entity)
        self.assertEqual(
            [
                'description',
                'team',
                'type',
                'health',
                'drift',
                'release',
                'deployed',
            ],
            list(fields),
        )
        self.assertEqual(
            'Administrative interface', fields['description']['value']
        )
        self.assertEqual(
            ('44', 'red'),
            (fields['health']['value'], fields['health']['tag_color']),
        )
        self.assertEqual(
            ('Production', '3.46.4'),
            (fields['release']['label'], fields['release']['value']),
        )
        self.assertEqual(1795539600, fields['deployed']['value'])
        buttons = entity['entity_payload']['actions']['primary_actions']
        self.assertEqual(
            [PROJECT_URL, f'{UI}/projects/p1/deployments'],
            [b['url'] for b in buttons],
        )

    def test_minimal_project(self) -> None:
        entity = unfurl.project_entity(
            {
                'id': 'p1',
                'name': 'API',
                'slug': 'api',
                'team': {'name': 'Core'},
                'score': None,
            },
            PROJECT_URL,
        )
        self.assertEqual(['team'], list(fields_by_key(entity)))
        buttons = entity['entity_payload']['actions']['primary_actions']
        self.assertEqual(['Open in Imbi'], [b['text'] for b in buttons])

    def test_health_bands(self) -> None:
        for score, color in ((85, 'green'), (50, 'yellow'), (49.4, 'red')):
            with self.subTest(score=score):
                entity = unfurl.project_entity(
                    {**PROJECT, 'score': score}, PROJECT_URL
                )
                self.assertEqual(
                    color, fields_by_key(entity)['health']['tag_color']
                )


class DriftTests(helpers.TestCase):
    def chips(self, project: dict[str, typing.Any]) -> list[tuple[str, str]]:
        return [
            (c['value'], c['tag_color']) for c in unfurl.drift_chips(project)
        ]

    def test_pipeline(self) -> None:
        days = unfurl._days_since('2026-10-01T00:00:00')
        self.assertEqual(
            [('T', 'green'), (f'S {days}', 'red'), ('P', 'green')],
            self.chips(PROJECT),
        )

    def test_undated_drift(self) -> None:
        pair = {**PROJECT['drift_pairs'][0], 'oldest': None}
        self.assertEqual(
            [('T', 'green'), ('S', 'red'), ('P', 'green')],
            self.chips({**PROJECT, 'drift_pairs': [pair]}),
        )

    def test_release(self) -> None:
        project = {
            **PROJECT,
            'drift_pairs': [],
            'environments': [],
            'release_drifted': True,
        }
        self.assertEqual([('Release', 'red')], self.chips(project))

    def test_none(self) -> None:
        self.assertEqual([], self.chips({'environments': []}))


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
            {'entities': [unfurl.ticket_entity(TICKET, TICKET_URL, 'acme')]},
            kwargs['metadata'],
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
        self.ok('/organizations/one/projects/', [])
        self.ok('/organizations/two/projects/', [PROJECT])
        with self.api():
            await unfurl.handle(self.event(PROJECT_URL), self.slack)
        entities = self.slack.chat_unfurl.await_args.kwargs['metadata']
        self.assertEqual(
            [PROJECT_URL], [e['app_unfurl_url'] for e in entities['entities']]
        )
        self.assertEqual(
            {'slim': 'true', 'include_archived': 'true', 'project_id': 'p1'},
            dict(self.calls[-1].url.params),
        )

    async def test_unreadable_link_is_skipped(self) -> None:
        self.ok('/organizations/acme/tickets/T-12', TICKET)
        self.ok('/organizations/', [{'slug': 'acme'}])
        with self.api():
            await unfurl.handle(
                self.event(TICKET_URL, PROJECT_URL), self.slack
            )
        entities = self.slack.chat_unfurl.await_args.kwargs['metadata']
        self.assertEqual(
            [TICKET_URL], [e['app_unfurl_url'] for e in entities['entities']]
        )

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
