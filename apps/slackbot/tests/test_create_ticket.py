import contextlib
import datetime
import typing
from unittest import mock

import httpx
import orjson

from apps.slackbot.tests import helpers
from imbi.slackbot import create_ticket as ct
from imbi.slackbot import identity

USER = identity.ImbiUser('ada@example.com', 'Ada', org_slug='acme')

SECTIONS = [
    {
        'scope': 'ticket',
        'required': ['severity', 'urgent', 'count', 'tags', 'extra', 'done'],
        'properties': {
            'severity': {'type': 'string', 'enum': ['sev1', 'sev2']},
            'urgent': {'type': 'boolean'},
            'count': {'type': 'integer', 'minimum': 0},
            'tags': {'type': 'array', 'items': {'type': 'string'}},
            'extra': {'type': 'object'},
            'done': {'type': 'string', 'default': 'no'},
            'optional': {'type': 'string'},
        },
    },
]


def meta(**kw: typing.Any) -> dict[str, typing.Any]:
    return {
        'org': 'acme',
        'manage': True,
        'me': ['ada@example.com', 'Ada'],
        'roles': 0,
        'extra': {},
        **kw,
    }


def opt(text: str, value: str | None = None) -> dict[str, typing.Any]:
    return {
        'text': {'type': 'plain_text', 'text': text, 'emoji': True},
        'value': value or text,
    }


def blocks_by_id(view: dict[str, typing.Any]) -> dict[str, typing.Any]:
    return {b['block_id']: b for b in view['blocks'] if 'block_id' in b}


def gating_block(view: dict[str, typing.Any]) -> dict[str, typing.Any]:
    return next(
        b
        for b in view['blocks']
        if b.get('element', {}).get('action_id') == ct.GATING
    )


class FormViewTests(helpers.TestCase):
    def test_agent_form(self) -> None:
        view = ct.form_view(meta(), {}, [])
        blocks = blocks_by_id(view)
        self.assertIn(ct.AGENT, blocks)
        self.assertNotIn(ct.PERSON, blocks)
        self.assertEqual(
            blocks[ct.OWNER]['element']['initial_option']['value'],
            'ada@example.com',
        )
        self.assertEqual(
            blocks[ct.TYPE]['element']['initial_option']['value'], 'task'
        )
        self.assertEqual(orjson.loads(view['private_metadata']), meta())

    def test_person_form(self) -> None:
        blocks = blocks_by_id(
            ct.form_view(meta(), {ct.KIND: opt('Person', 'person')}, [])
        )
        self.assertIn(ct.PERSON, blocks)
        self.assertNotIn(ct.AGENT, blocks)
        self.assertEqual(
            blocks[ct.KIND]['element']['initial_option']['value'], 'person'
        )

    def test_owner_is_the_user_without_manage(self) -> None:
        blocks = blocks_by_id(ct.form_view(meta(manage=False), {}, []))
        # No ticket:manage: the owner is the user.
        self.assertNotIn(ct.OWNER, blocks)

    def test_values_are_kept(self) -> None:
        values = {
            ct.DESCRIPTION: 'Fix it',
            ct.DUE: '2030-01-01',
            ct.LABELS: [opt('api')],
            ct.PRIORITY: opt('High', 'high'),
        }
        blocks = blocks_by_id(ct.form_view(meta(), values, []))
        element = blocks[ct.DESCRIPTION]['element']
        self.assertEqual(element['initial_value'], 'Fix it')
        self.assertEqual(
            blocks[ct.DUE]['element']['initial_date'], '2030-01-01'
        )
        self.assertEqual(
            blocks[ct.LABELS]['element']['initial_options'], [opt('api')]
        )
        self.assertEqual(
            blocks[ct.PRIORITY]['element']['initial_option']['value'], 'high'
        )

    def test_custom_fields(self) -> None:
        blocks = blocks_by_id(ct.form_view(meta(), {}, SECTIONS))
        kinds = {
            key: blocks[ct.FIELD + key]['element']['type']
            for key in ('severity', 'urgent', 'count', 'tags', 'extra')
        }
        self.assertEqual(
            kinds,
            {
                'severity': 'static_select',
                'urgent': 'checkboxes',
                'count': 'number_input',
                'tags': 'plain_text_input',
                'extra': 'plain_text_input',
            },
        )
        self.assertNotIn(ct.FIELD + 'done', blocks)
        self.assertNotIn(ct.FIELD + 'optional', blocks)
        self.assertEqual(
            blocks[ct.FIELD + 'count']['element']['min_value'], '0'
        )

    def test_problems_are_hints(self) -> None:
        view = ct.form_view(
            meta(), {}, [], {ct.DUE: 'Too early'}, notice='No <!here>'
        )
        self.assertEqual(
            blocks_by_id(view)[ct.DUE]['hint']['text'], '⚠ Too early'
        )
        self.assertIn('&lt;!here&gt;', view['blocks'][0]['text']['text'])

    def test_roles_and_gating(self) -> None:
        values = {
            ct.REQUIRES: [opt('T-1'), opt('T-2')],
            ct.GATING: [opt('T-1')],
        }
        view = ct.form_view(meta(roles=2), values, [])
        blocks = blocks_by_id(view)
        self.assertIn(ct.ROLE_NAME + '1', blocks)
        self.assertIn(ct.ROLE_PERSON + '1', blocks)
        gate = gating_block(view)['element']
        self.assertEqual(gate['initial_options'], [opt('T-1')])
        # Checkboxes cannot show more than 10 prerequisites.
        self.assertEqual(gate['type'], 'multi_static_select')
        buttons = [
            e['action_id']
            for b in view['blocks']
            if b['type'] == 'actions'
            for e in b['elements']
        ]
        self.assertEqual(buttons, [ct.ROLE_ADD, ct.ROLE_REMOVE])

    def test_no_add_role_at_the_limit(self) -> None:
        view = ct.form_view(meta(roles=ct.MAX_ROLES), {}, [])
        buttons = [
            e['action_id']
            for b in view['blocks']
            if b['type'] == 'actions'
            for e in b['elements']
        ]
        self.assertEqual(buttons, [ct.ROLE_REMOVE])


class StateTests(helpers.TestCase):
    def test_read_values(self) -> None:
        view = {
            'state': {
                'values': {
                    'a': {'a': {'type': 'plain_text_input', 'value': 'x'}},
                    'b': {'b': {'type': 'datepicker', 'selected_date': 'd'}},
                    'c': {
                        'c': {
                            'type': 'external_select',
                            'selected_option': opt('o'),
                        }
                    },
                    'd': {
                        'd': {
                            'type': 'multi_external_select',
                            'selected_options': None,
                        }
                    },
                    'e': {
                        'e': {
                            'type': 'checkboxes',
                            'selected_options': [opt('t')],
                        }
                    },
                }
            }
        }
        self.assertEqual(
            ct.read_values(view),
            {'a': 'x', 'b': 'd', 'c': opt('o'), 'd': [], 'e': [opt('t')]},
        )

    def test_unchecked_prerequisite_stays_unchecked(self) -> None:
        view = {
            'blocks': [
                {
                    'block_id': ct.GATING + '@1',
                    'element': {
                        'action_id': ct.GATING,
                        'options': [opt('T-1'), opt('T-2')],
                    },
                }
            ]
        }
        values = {
            ct.REQUIRES: [opt('T-1'), opt('T-2'), opt('T-3')],
            ct.GATING: [opt('T-1')],
        }
        # T-2 was unchecked; T-3 is new and gates.
        self.assertEqual(ct.gating(view, values), [opt('T-1'), opt('T-3')])

    def test_check(self) -> None:
        yesterday = datetime.datetime.now(
            datetime.UTC
        ).date() - datetime.timedelta(days=1)
        values = {
            ct.DUE: yesterday.isoformat(),
            ct.ROLE_NAME + '0': 'qa',
            ct.ROLE_PERSON + '1': opt('Bo', 'bo@example.com'),
            ct.PARENT: opt('T-1'),
            ct.REQUIRES: [opt('T-1')],
        }
        self.assertEqual(
            set(ct.check(meta(roles=2), values)),
            {ct.DUE, ct.ROLE_PERSON + '0', ct.ROLE_NAME + '1', ct.PARENT},
        )

    def test_roles(self) -> None:
        values = {
            ct.ROLE_NAME + '0': ' qa ',
            ct.ROLE_PERSON + '0': opt('Bo', 'bo@example.com'),
            ct.ROLE_NAME + '1': 'ignored',
        }
        self.assertEqual(
            ct.roles(meta(roles=2), values), {'qa': 'bo@example.com'}
        )


class CustomFieldTests(helpers.TestCase):
    def test_required_fields(self) -> None:
        later = {
            'scope': 'ticket',
            'required': [],
            'properties': {'count': {'type': 'integer'}},
        }
        fields = ct.required_fields(
            [*SECTIONS, later], {'new': {'type': 'string'}}
        )
        self.assertEqual(
            sorted(fields), ['extra', 'new', 'severity', 'tags', 'urgent']
        )

    def test_values(self) -> None:
        fields = ct.required_fields(SECTIONS, {})
        values = {
            ct.FIELD + 'severity': opt('sev2', '"sev2"'),
            ct.FIELD + 'count': '3',
            ct.FIELD + 'tags': 'a\n\n b \n',
            ct.FIELD + 'extra': '{"k": 1}',
        }
        result, problems = ct.custom_fields(fields, values)
        self.assertEqual(problems, {})
        self.assertEqual(
            result,
            {
                'severity': 'sev2',
                'urgent': False,
                'count': 3,
                'tags': ['a', 'b'],
                'extra': {'k': 1},
            },
        )

    def test_boolean_enum(self) -> None:
        result, _ = ct.custom_fields(
            {'b': {'type': 'boolean', 'enum': [False, True]}},
            {ct.FIELD + 'b': opt('False', 'false')},
        )
        self.assertEqual(result, {'b': False})

    def test_bad_object(self) -> None:
        _, problems = ct.custom_fields(
            {'extra': {'type': 'object'}}, {ct.FIELD + 'extra': '[1]'}
        )
        self.assertEqual(
            problems, {ct.FIELD + 'extra': 'Enter a JSON object.'}
        )


class ApiTestCase(helpers.TestCase):
    """Runs the module against routes of a fake imbi-api."""

    def setUp(self) -> None:
        super().setUp()
        ct._cache.clear()
        self.calls: list[httpx.Request] = []
        self.routes: dict[tuple[str, str], httpx.Response] = {}

    @contextlib.contextmanager
    def api(self) -> typing.Iterator[None]:
        def handler(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            return self.routes.get(
                (request.method, request.url.path), httpx.Response(404)
            )

        transport = httpx.MockTransport(handler)

        class Client(ct.identity.api.Imbi):
            def __init__(self, **kw: typing.Any) -> None:
                super().__init__(**kw)
                self._transport = transport

        with (
            mock.patch.object(ct.identity.api, 'Imbi', Client),
            mock.patch.object(ct.identity, 'mint_token', return_value='tok'),
            mock.patch.object(
                ct.identity, 'resolve', new=mock.AsyncMock(return_value=USER)
            ),
        ):
            yield

    def route(self, method: str, path: str, status: int, body: object) -> None:
        self.routes[(method, path)] = httpx.Response(status, json=body)

    def sent(self, method: str, path: str) -> typing.Any:
        for request in self.calls:
            if (request.method, request.url.path) == (method, path):
                return orjson.loads(request.content)
        raise AssertionError(f'no {method} {path}')


T = '/organizations/acme/tickets'


class CreateTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.route(
            'GET', f'{T}/schema', 200, {'sections': [], 'filterable': []}
        )
        self.values = {
            ct.DESCRIPTION: 'Fix the login page',
            ct.AGENT: opt('Fixer', 'fixer'),
            ct.TYPE: opt('Bug', 'bug'),
            ct.PRIORITY: opt('High', 'high'),
            ct.LABELS: [opt('api')],
            ct.REQUIRES: [opt('T-1'), opt('T-2')],
            ct.GATING: [opt('T-2')],
        }

    async def test_create(self) -> None:
        self.route(
            'POST',
            f'{T}/subject',
            200,
            {'subject': 'Fix login', 'degraded': False},
        )
        self.route(
            'POST',
            f'{T}/',
            201,
            {
                'short_id': 'T-9',
                'title': 'Fix login',
                'status': 'queued',
                'assignee_kind': 'agent',
            },
        )
        with self.api():
            view = await ct.create(USER, meta(), self.values)
        body = self.sent('POST', f'{T}/')
        self.assertEqual(body['agent_slug'], 'fixer')
        self.assertEqual(body['title'], 'Fix login')
        self.assertEqual(body['type'], 'bug')
        self.assertEqual(body['labels'], ['api'])
        self.assertEqual(
            body['requires'],
            [
                {'short_id': 'T-1', 'gates': False},
                {'short_id': 'T-2', 'gates': True},
            ],
        )
        self.assertEqual(view['title']['text'], 'Ticket created')
        self.assertIn('Runs now with Fixer.', str(view['blocks']))

    async def test_person_ticket_with_parent_and_owner(self) -> None:
        self.route(
            'POST',
            f'{T}/',
            201,
            {
                'short_id': 'T-9',
                'title': 'S',
                'status': 'open',
                'assignee_kind': 'person',
            },
        )
        self.route('PUT', f'{T}/T-9/parent', 204, None)
        self.route(
            'POST', f'{T}/T-9/reassign', 403, {'detail': 'Needs ticket:manage'}
        )
        values = {
            ct.SUBJECT: 'S',
            ct.DESCRIPTION: 'Do it',
            ct.KIND: opt('Person', 'person'),
            ct.PERSON: opt('Bo', 'bo@example.com'),
            ct.PARENT: opt('T-5'),
            ct.OWNER: opt('Cy', 'cy@example.com'),
        }
        with self.api():
            view = await ct.create(USER, meta(), values)
        body = self.sent('POST', f'{T}/')
        self.assertEqual(body['assignee'], 'bo@example.com')
        self.assertNotIn('agent_slug', body)
        self.assertEqual(
            self.sent('PUT', f'{T}/T-9/parent'), {'parent': 'T-5'}
        )
        text = str(view['blocks'])
        self.assertIn('Assigned to Bo.', text)
        self.assertIn('T-9 was created, but: Needs ticket:manage', text)

    async def test_missing_custom_field_is_asked_for(self) -> None:
        self.route(
            'POST', f'{T}/subject', 200, {'subject': 'Fix', 'degraded': True}
        )
        self.route(
            'POST',
            f'{T}/',
            422,
            {
                'detail': {
                    'error': 'custom_fields_invalid',
                    'missing': [
                        {'field': 'sev', 'type': 'string', 'title': 'Severity'}
                    ],
                    'invalid': [],
                }
            },
        )
        m = meta()
        with self.api():
            view = await ct.create(USER, m, self.values)
        self.assertEqual(self.sent('POST', f'{T}/')['title'], 'Fix')
        block = blocks_by_id(view)[ct.FIELD + 'sev']
        self.assertEqual(block['hint']['text'], '⚠ Required')
        self.assertIn('sev', orjson.loads(view['private_metadata'])['extra'])

    async def test_other_error_is_a_notice(self) -> None:
        self.route(
            'POST', f'{T}/subject', 200, {'subject': 'S', 'degraded': True}
        )
        self.route('POST', f'{T}/', 422, {'detail': [{'msg': 'bad label'}]})
        with self.api():
            view = await ct.create(USER, meta(), self.values)
        self.assertIn('bad label', view['blocks'][0]['text']['text'])

    async def test_refused_subject_is_a_notice(self) -> None:
        self.route(
            'POST', f'{T}/subject', 403, {'detail': 'Needs ticket:create'}
        )
        with self.api():
            view = await ct.create(USER, meta(), self.values)
        self.assertIn('Needs ticket:create', view['blocks'][0]['text']['text'])
        self.assertFalse(
            any(r.url.path == f'{T}/' for r in self.calls), 'no create'
        )


class SearchTests(ApiTestCase):
    async def test_agents(self) -> None:
        self.route(
            'GET',
            '/organizations/acme/agents/',
            200,
            [
                {'name': 'Zed', 'slug': 'zed', 'enabled': True},
                {
                    'name': 'Fixer',
                    'slug': 'fixer',
                    'enabled': True,
                    'description': 'Fixes bugs',
                },
                {'name': 'Off', 'slug': 'off', 'enabled': False},
            ],
        )
        with self.api():
            options = await ct.search(USER, 'acme', ct.AGENT, '')
            bugs = await ct.search(USER, 'acme', ct.AGENT, 'BUG')
        self.assertEqual([o['value'] for o in options], ['fixer', 'zed'])
        self.assertEqual([o['value'] for o in bugs], ['fixer'])
        # The second search used the cache.
        self.assertEqual(len(self.calls), 1)

    async def test_members(self) -> None:
        self.route(
            'GET',
            '/organizations/acme/members',
            200,
            [
                {
                    'email': 'bo@example.com',
                    'display_name': 'Bo',
                    'is_active': True,
                },
                {'email': 'old@example.com', 'is_active': False},
            ],
        )
        with self.api():
            options = await ct.search(USER, 'acme', ct.ROLE_PERSON + '3', 'bo')
        self.assertEqual(
            options, [opt('Bo (bo@example.com)', 'bo@example.com')]
        )

    async def test_new_label(self) -> None:
        self.route('GET', f'{T}/labels', 200, [{'name': 'api', 'count': 3}])
        with self.api():
            options = await ct.search(USER, 'acme', ct.LABELS, 'Ap')
        self.assertEqual([o['value'] for o in options], ['ap', 'api'])

    async def test_projects_skip_archived(self) -> None:
        self.route(
            'GET',
            '/organizations/acme/projects/',
            200,
            [
                {'id': 'p1', 'slug': 'web'},
                {'id': 'p2', 'slug': 'old-web', 'archived': True},
            ],
        )
        with self.api():
            options = await ct.search(USER, 'acme', ct.PROJECTS, 'web')
        self.assertEqual(options, [opt('web', 'p1')])

    async def test_tickets(self) -> None:
        self.route('GET', f'{T}/', 200, [{'short_id': 'T-1', 'title': 'One'}])
        with self.api():
            options = await ct.search(USER, 'acme', ct.PARENT, 'one')
        self.assertEqual(options, [opt('T-1 · One', 'T-1')])
        self.assertEqual(self.calls[0].url.params['q'], 'one')

    async def test_typed_label_is_normalized(self) -> None:
        self.route(
            'GET', f'{T}/labels', 200, [{'name': 'my-label', 'count': 1}]
        )
        with self.api():
            options = await ct.search(USER, 'acme', ct.LABELS, 'My Label')
            await ct.search(USER, 'acme', ct.LABELS, 'My Label')
        self.assertEqual([o['value'] for o in options], ['my-label'])
        # A search with typed text is not cached.
        self.assertEqual(len(self.calls), 2)


class ListenerTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.route(
            'GET', f'{T}/schema', 200, {'sections': [], 'filterable': []}
        )
        self.slack = mock.AsyncMock()
        self.slack.views_open.return_value = {'view': {'id': 'V1'}}

    def shown(self) -> dict[str, typing.Any]:
        return self.slack.views_update.call_args.kwargs['view']

    async def test_command_opens_the_form(self) -> None:
        self.route(
            'GET',
            '/users/me',
            200,
            {
                'is_admin': False,
                'organizations': [
                    {
                        'organization_slug': 'acme',
                        'organization_name': 'Acme',
                        'permissions': ['ticket:manage'],
                    }
                ],
            },
        )
        ack = mock.AsyncMock()
        with self.api():
            await ct.on_command(
                ack,
                {'trigger_id': 't', 'user_id': 'U1', 'text': ' Fix it '},
                self.slack,
            )
        ack.assert_awaited_once()
        blocks = blocks_by_id(self.shown())
        self.assertEqual(
            blocks[ct.DESCRIPTION]['element']['initial_value'], 'Fix it'
        )
        self.assertIn(ct.OWNER, blocks)
        key = orjson.loads(self.shown()['private_metadata'])['key']
        self.assertTrue(key.startswith('slack:'))

    async def test_command_when_imbi_fails(self) -> None:
        self.route('GET', '/users/me', 500, {})
        with self.api():
            await ct.on_command(
                mock.AsyncMock(),
                {'trigger_id': 't', 'user_id': 'U1'},
                self.slack,
            )
        self.assertIn(ct._UNAVAILABLE, str(self.shown()))

    def body(
        self, view: dict[str, typing.Any], **kw: typing.Any
    ) -> dict[str, typing.Any]:
        return {
            'user': {'id': 'U1'},
            'view': {'id': 'V1', 'hash': 'h', **view},
            **kw,
        }

    async def test_kind_change_shows_the_person_picker(self) -> None:
        view = {
            'private_metadata': orjson.dumps(meta()).decode(),
            'blocks': [],
            'state': {
                'values': {
                    ct.KIND: {
                        ct.KIND: {
                            'type': 'radio_buttons',
                            'selected_option': opt('Person', 'person'),
                        }
                    }
                }
            },
        }
        with self.api():
            await ct.on_action(
                mock.AsyncMock(),
                self.body(view, actions=[{'action_id': ct.KIND}]),
                self.slack,
            )
        self.assertIn(ct.PERSON, blocks_by_id(self.shown()))
        self.assertEqual(self.slack.views_update.call_args.kwargs['hash'], 'h')

    async def test_new_prerequisite_gates_after_rebuild(self) -> None:
        old = ct.form_view(meta(), {ct.REQUIRES: [opt('T-1'), opt('T-2')]}, [])
        old_gate = gating_block(old)
        state = {
            ct.REQUIRES: {
                ct.REQUIRES: {
                    'type': 'multi_external_select',
                    'selected_options': [opt('T-1'), opt('T-2'), opt('T-3')],
                }
            },
            # The person unchecked T-2.
            old_gate['block_id']: {
                ct.GATING: {
                    'type': 'multi_static_select',
                    'selected_options': [opt('T-1')],
                }
            },
        }
        view = {
            'private_metadata': old['private_metadata'],
            'blocks': old['blocks'],
            'state': {'values': state},
        }
        with self.api():
            await ct.on_action(
                mock.AsyncMock(),
                self.body(view, actions=[{'action_id': ct.REQUIRES}]),
                self.slack,
            )
        gate = gating_block(self.shown())
        # A new block id, so Slack shows the new initial options.
        self.assertNotEqual(gate['block_id'], old_gate['block_id'])
        self.assertEqual(
            gate['element']['initial_options'], [opt('T-1'), opt('T-3')]
        )
        # The other inputs keep their block ids.
        self.assertIn(ct.REQUIRES, blocks_by_id(self.shown()))

    async def test_options(self) -> None:
        self.route(
            'GET',
            '/organizations/acme/teams/',
            200,
            [{'name': 'Ops', 'slug': 'ops'}],
        )
        ack = mock.AsyncMock()
        body = self.body(
            {'private_metadata': orjson.dumps(meta()).decode()},
            action_id=ct.TEAM,
            value='op',
        )
        with self.api():
            await ct.on_options(ack, body, self.slack)
        ack.assert_awaited_once_with(options=[opt('Ops', 'ops')])

    async def test_submit_with_problems(self) -> None:
        view = {
            'private_metadata': orjson.dumps(meta()).decode(),
            'state': {
                'values': {
                    ct.DUE: {
                        ct.DUE: {
                            'type': 'datepicker',
                            'selected_date': '2000-01-01',
                        }
                    },
                    ct.PARENT: {
                        ct.PARENT: {
                            'type': 'external_select',
                            'selected_option': opt('T-1'),
                        }
                    },
                    ct.REQUIRES: {
                        ct.REQUIRES: {
                            'type': 'multi_external_select',
                            'selected_options': [opt('T-1')],
                        }
                    },
                }
            },
        }
        ack = mock.AsyncMock()
        with self.api():
            await ct.on_submit(ack, self.body(view), self.slack)
        self.assertEqual(ack.call_args.kwargs['response_action'], 'errors')
        self.assertEqual(
            set(ack.call_args.kwargs['errors']), {ct.DUE, ct.PARENT}
        )
        self.slack.views_update.assert_not_awaited()

    async def test_submit_creates(self) -> None:
        self.route(
            'POST',
            f'{T}/',
            201,
            {
                'short_id': 'T-9',
                'title': 'S',
                'status': 'held',
                'assignee_kind': 'agent',
            },
        )
        state = {
            ct.SUBJECT: {
                ct.SUBJECT: {'type': 'plain_text_input', 'value': 'S'}
            },
            ct.DESCRIPTION: {
                ct.DESCRIPTION: {'type': 'plain_text_input', 'value': 'D'}
            },
            ct.AGENT: {
                ct.AGENT: {
                    'type': 'external_select',
                    'selected_option': opt('A', 'a'),
                }
            },
            ct.REQUIRES: {
                ct.REQUIRES: {
                    'type': 'multi_external_select',
                    'selected_options': [opt('T-1')],
                }
            },
        }
        # No gating input yet: the view was not built again.
        view = {
            'private_metadata': orjson.dumps(meta(key='k1')).decode(),
            'blocks': [],
            'state': {'values': state},
        }
        ack = mock.AsyncMock()
        with self.api():
            await ct.on_submit(ack, self.body(view), self.slack)
        self.assertEqual(ack.call_args.kwargs['response_action'], 'update')
        self.assertIn('Starts held', str(self.shown()))
        body = self.sent('POST', f'{T}/')
        self.assertEqual(
            body['requires'], [{'short_id': 'T-1', 'gates': True}]
        )
        self.assertEqual(body['idempotency_key'], 'k1')


class RegisterTests(helpers.TestCase):
    def test_register(self) -> None:
        app = mock.MagicMock()
        ct.register(app)
        app.command.assert_called_once_with(ct.COMMAND)
        app.view.assert_called_once_with(ct.CALLBACK_ID)
        for action in (ct.KIND, ct.ROLE_ADD, ct.REQUIRES):
            self.assertTrue(ct.DISPATCH.match(action))
        for action in (ct.AGENT, ct.ROLE_PERSON + '2', ct.PARENT):
            self.assertTrue(ct.SEARCH.match(action))
