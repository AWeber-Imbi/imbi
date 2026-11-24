import asyncio
import typing
from unittest import mock

import httpx
import orjson
import pydantic
from slack_sdk import errors
from slackwright import forms

from apps.slackbot.tests import helpers
from imbi.slackbot import identity, ticket_requests


class Resp(dict):
    @property
    def data(self):
        return self


class Pages:
    def __init__(self, pages) -> None:
        self._pages = pages

    async def __aiter__(self):
        for page in self._pages:
            yield page


class FakeSlack:
    def __init__(self) -> None:
        self.posts: list[dict[str, typing.Any]] = []
        self.updates: list[dict[str, typing.Any]] = []

    async def chat_postMessage(self, channel, text=None, **kw):
        if channel == 'C404':
            raise errors.SlackApiError(
                'channel_not_found', {'error': 'channel_not_found'}
            )
        self.posts.append({'channel': channel, 'text': text, **kw})
        return Resp(ts=f'ts{len(self.posts)}')

    async def chat_update(self, channel, ts, text=None, **kw):
        self.updates.append({'channel': channel, 'ts': ts, 'text': text})

    async def conversations_list(self, **_kw):
        return Pages(
            [
                Resp(channels=[{'name': 'general', 'id': 'C1'}]),
                Resp(channels=[{'name': 'ops', 'id': 'C2'}]),
            ]
        )

    async def users_lookupByEmail(self, email):
        if email != 'ada@example.com':
            raise errors.SlackApiError('users_not_found', {})
        return Resp(user={'id': 'U1'})

    async def conversations_open(self, users):
        return Resp(channel={'id': f'D-{users}'})


def entry(**overrides: typing.Any) -> dict[str, typing.Any]:
    return {
        'org_slug': 'aweber',
        'short_id': 'T-7',
        'ticket_title': 'Fix the build',
        'owner': 'ada@example.com',
        'agent_name': 'Triage Bot',
        'slack_channel': None,
        'request_id': 'r-1',
        'kind': 'feedback',
        'title': 'Which branch?',
        'why': 'Two branches fail.',
        'options': ['main', 'dev'],
        'artifacts': None,
        'artifact_digests': None,
    } | overrides


def fields(spec: forms.FormSpec) -> dict[str, typing.Any]:
    return {f.id: f for f in spec.fields}


class FormSpecTests(helpers.TestCase):
    def test_options_are_a_choice_or_text(self) -> None:
        spec = ticket_requests.form_spec(entry())
        by_id = fields(spec)
        self.assertEqual('radio', by_id['choice'].type)
        self.assertEqual(['main', 'dev'], by_id['choice'].options)
        self.assertFalse(by_id['choice'].required)
        self.assertFalse(by_id['other'].required)
        self.assertEqual('T-7 needs input', spec.title)
        self.assertEqual('anyone', spec.respondents)
        self.assertIn('Triage Bot asks: **Which branch?**', spec.intro)
        self.assertIn('Two branches fail.', spec.intro)

    def test_many_options_are_a_select(self) -> None:
        options = [f'o{i}' for i in range(11)]
        spec = ticket_requests.form_spec(entry(options=options))
        self.assertEqual('select', fields(spec)['choice'].type)

    def test_long_options_are_listed_with_a_text_box(self) -> None:
        spec = ticket_requests.form_spec(entry(options=['x' * 80, 'y']))
        self.assertEqual(['answer'], list(fields(spec)))
        self.assertIn('- ' + 'x' * 80, spec.intro)

    def test_empty_option_is_a_text_box(self) -> None:
        spec = ticket_requests.form_spec(entry(options=['', 'main']))
        self.assertEqual(['answer'], list(fields(spec)))

    def test_no_options_is_a_text_box(self) -> None:
        spec = ticket_requests.form_spec(entry(options=None))
        self.assertEqual(['answer'], list(fields(spec)))
        self.assertTrue(fields(spec)['answer'].required)

    def test_approval(self) -> None:
        spec = ticket_requests.form_spec(
            entry(
                kind='approval',
                options=None,
                artifacts=[{'name': 'diff'}],
                artifact_digests=['sha256:ab'],
            )
        )
        decision = fields(spec)['decision']
        self.assertEqual(['Approve', 'Reject'], decision.options)
        self.assertTrue(decision.required)
        self.assertIn('asks for approval', spec.intro)
        self.assertIn('{"name":"diff"}', spec.intro)

    def test_ticket_link(self) -> None:
        with self.override_environment(IMBI_UI_URL='https://imbi.test'):
            ticket_requests.settings._slackbot_settings = None
            try:
                spec = ticket_requests.form_spec(entry())
            finally:
                ticket_requests.settings._slackbot_settings = None
        self.assertIn(
            '[T-7](https://imbi.test/tickets/aweber/T-7)', spec.intro
        )

    def test_secret_question_is_refused(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            ticket_requests.form_spec(entry(title='Which API key?'))


class ResolutionTests(helpers.TestCase):
    def test_text_wins_over_the_choice(self) -> None:
        self.assertEqual(
            {'status': 'answered', 'answer': 'release'},
            ticket_requests.resolution(
                entry(), {'choice': 'main', 'other': ' release '}
            ),
        )

    def test_choice(self) -> None:
        self.assertEqual(
            {'status': 'answered', 'answer': 'main'},
            ticket_requests.resolution(
                entry(), {'choice': 'main', 'other': None}
            ),
        )

    def test_no_answer(self) -> None:
        self.assertIsNone(
            ticket_requests.resolution(entry(), {'choice': None, 'other': ''})
        )

    def test_approve_binds_the_digests(self) -> None:
        approval = entry(kind='approval', artifact_digests=['sha256:ab'])
        self.assertEqual(
            {'status': 'approved', 'artifact_digests': ['sha256:ab']},
            ticket_requests.resolution(approval, {'decision': 'Approve'}),
        )
        self.assertEqual(
            {'status': 'rejected'},
            ticket_requests.resolution(approval, {'decision': 'Reject'}),
        )


class FlowTestCase(helpers.TestCase):
    def setUp(self) -> None:
        super().setUp()
        ticket_requests._channels.clear()
        ticket_requests._misses.clear()
        self.slack = FakeSlack()
        self.store = forms.MemoryFormStore()
        self.runtime = forms.Runtime(self.store, mock.AsyncMock())

    async def stored(self) -> forms.FormRecord:
        (form_id,) = self.store._records
        record = await self.store.get(form_id)
        assert record is not None
        return record


class PostTests(FlowTestCase):
    async def test_agent_channel_by_name(self) -> None:
        await ticket_requests.post(
            self.slack, self.runtime, entry(slack_channel='#ops')
        )
        self.assertEqual('C2', self.slack.posts[0]['channel'])
        record = await self.stored()
        self.assertEqual(
            'r-1', record.metadata['ticket_request']['request_id']
        )

    async def test_agent_channel_by_id(self) -> None:
        await ticket_requests.post(
            self.slack, self.runtime, entry(slack_channel='C9')
        )
        self.assertEqual('C9', self.slack.posts[0]['channel'])

    async def test_owner_when_no_channel(self) -> None:
        await ticket_requests.post(self.slack, self.runtime, entry())
        self.assertEqual('D-U1', self.slack.posts[0]['channel'])

    async def test_owner_when_the_channel_is_unknown(self) -> None:
        await ticket_requests.post(
            self.slack, self.runtime, entry(slack_channel='#nope')
        )
        self.assertEqual('D-U1', self.slack.posts[0]['channel'])

    async def test_owner_when_channels_cannot_be_listed(self) -> None:
        self.slack.conversations_list = mock.AsyncMock(
            side_effect=errors.SlackApiError(
                'missing_scope', {'error': 'missing_scope'}
            )
        )
        await ticket_requests.post(
            self.slack, self.runtime, entry(slack_channel='#ops')
        )
        self.assertEqual('D-U1', self.slack.posts[0]['channel'])

    async def test_owner_when_the_channel_id_is_stale(self) -> None:
        await ticket_requests.post(
            self.slack, self.runtime, entry(slack_channel='C404')
        )
        self.assertEqual('D-U1', self.slack.posts[0]['channel'])

    async def test_owner_not_in_slack(self) -> None:
        await ticket_requests.post(
            self.slack, self.runtime, entry(owner='bob@example.com')
        )
        self.assertEqual([], self.slack.posts)

    async def test_refused_form_is_a_message(self) -> None:
        await ticket_requests.post(
            self.slack, self.runtime, entry(title='Which API key?')
        )
        text = self.slack.posts[0]['markdown_text']
        self.assertIn('Answer it in Imbi.', text)
        self.assertNotIn('API key', text)

    async def test_refused_form_title_cannot_broadcast(self) -> None:
        await ticket_requests.post(
            self.slack,
            self.runtime,
            entry(title='Which API key?', ticket_title='Fix @here <!channel>'),
        )
        text = self.slack.posts[0]['markdown_text']
        self.assertNotIn('@here', text)
        self.assertNotIn('<!channel>', text)
        self.assertEqual({}, self.store._records)


class AnswerTests(helpers.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.calls: list[httpx.Request] = []

    async def answer(
        self,
        response: httpx.Response,
        values: dict[str, typing.Any],
        metadata: dict[str, typing.Any] | None = None,
    ) -> bool:
        def handler(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            return response

        transport = httpx.MockTransport(handler)

        class Client(ticket_requests.api.Imbi):
            def __init__(self, **kw: typing.Any) -> None:
                super().__init__(**kw)
                self._transport = transport

        user = identity.ImbiUser('ada@example.com', 'Ada')
        with (
            mock.patch.object(ticket_requests.api, 'Imbi', Client),
            mock.patch.object(
                ticket_requests.identity,
                'resolve',
                new=mock.AsyncMock(return_value=user),
            ),
            mock.patch.object(
                ticket_requests.identity, 'mint_token', return_value='tok'
            ),
        ):
            return await ticket_requests.answer(
                FakeSlack(),
                forms.Submission(
                    form_id='F1',
                    spec=ticket_requests.form_spec(entry()),
                    values=values,
                    user_id='U2',
                    channel_id='D-U1',
                    thread_ts=None,
                    metadata=(
                        {'ticket_request': entry()}
                        if metadata is None
                        else metadata
                    ),
                ),
            )

    async def rejected(
        self, response: httpx.Response, values: dict[str, typing.Any]
    ) -> forms.Rejected:
        with self.assertRaises(forms.Rejected) as raised:
            await self.answer(response, values)
        return raised.exception

    async def test_answer_resolves_the_request(self) -> None:
        handled = await self.answer(
            httpx.Response(201, json={}), {'choice': 'main', 'other': None}
        )
        self.assertTrue(handled)
        (request,) = self.calls
        self.assertTrue(
            request.url.path.endswith(
                '/organizations/aweber/tickets/T-7/requests/r-1/resolve'
            )
        )
        self.assertEqual('Bearer tok', request.headers['Authorization'])
        self.assertEqual(
            {'status': 'answered', 'answer': 'main'},
            orjson.loads(request.content),
        )

    async def test_forbidden_opens_the_form_again(self) -> None:
        error = await self.rejected(
            httpx.Response(403, json={'detail': 'no'}),
            {'choice': 'main', 'other': None},
        )
        self.assertIn('ticket:resolve', error.message)
        self.assertTrue(error.retry)

    async def test_empty_answer_opens_the_form_again(self) -> None:
        error = await self.rejected(
            httpx.Response(201), {'choice': None, 'other': ''}
        )
        self.assertEqual([], self.calls)
        self.assertEqual('Pick an answer or write one.', error.message)
        self.assertTrue(error.retry)

    async def test_answered_elsewhere_closes_the_form(self) -> None:
        detail = {'error': 'request_resolved', 'resolved_by': 'bob@x.io'}
        error = await self.rejected(
            httpx.Response(409, json={'detail': detail}),
            {'choice': 'main', 'other': None},
        )
        self.assertEqual('bob@x.io answered it first.', error.message)
        self.assertFalse(error.retry)

    async def test_identity_failure_opens_the_form_again(self) -> None:
        resolve = mock.AsyncMock(side_effect=RuntimeError('graph down'))
        with (
            mock.patch.object(ticket_requests.identity, 'resolve', resolve),
            self.assertLogs(ticket_requests.LOGGER, 'ERROR'),
            self.assertRaises(forms.Rejected) as raised,
        ):
            await ticket_requests.answer(
                FakeSlack(),
                forms.Submission(
                    form_id='F1',
                    spec=ticket_requests.form_spec(entry()),
                    values={'choice': 'main', 'other': None},
                    user_id='U2',
                    channel_id='D-U1',
                    thread_ts=None,
                    metadata={'ticket_request': entry()},
                ),
            )
        self.assertTrue(raised.exception.retry)
        self.assertEqual([], self.calls)

    async def test_other_forms_are_not_handled(self) -> None:
        self.assertFalse(
            await self.answer(httpx.Response(201), {'choice': 'main'}, {})
        )
        self.assertEqual([], self.calls)


class ConsumeTests(FlowTestCase):
    async def test_posts_and_acks_each_entry(self) -> None:
        client = mock.AsyncMock()
        message = (b'1-0', {b'request': orjson.dumps(entry())})
        # A claimed entry of a stopped consumer, with decoded keys.
        claimed = ('0-9', {'request': orjson.dumps(entry())})
        client.xautoclaim.return_value = ['0-0', [claimed], []]
        client.xreadgroup.side_effect = [
            [[b'imbi:ticket-requests', [message]]],
            asyncio.CancelledError(),
        ]
        with (
            mock.patch.object(
                ticket_requests.valkey, 'get_client', return_value=client
            ),
            self.assertRaises(asyncio.CancelledError),
        ):
            await ticket_requests.consume(self.slack, self.runtime)
        self.assertEqual('0', client.xgroup_create.await_args.kwargs['id'])
        self.assertEqual(
            ['0-9', b'1-0'],
            [c.args[2] for c in client.xack.await_args_list],
        )
        self.assertEqual(2, len(self.slack.posts))
