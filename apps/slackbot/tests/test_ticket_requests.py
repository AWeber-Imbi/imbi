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
        if channel == 'C404':
            raise errors.SlackApiError(
                'channel_not_found', {'error': 'channel_not_found'}
            )
        if channel == 'C500':
            raise errors.SlackApiError(
                'internal_error', {'error': 'internal_error'}
            )
        self.updates.append({'channel': channel, 'ts': ts, 'text': text, **kw})

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


class FakeValkey:
    def __init__(self) -> None:
        self.lists: dict[str, list[bytes]] = {}
        self.values: dict[str, bytes] = {}
        self.stream: list[dict[str, typing.Any]] = []

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    async def xadd(self, stream, fields, **_kw):
        self.stream.append(fields)

    async def get(self, key):
        return self.values.get(key)

    async def rpush(self, key, *values):
        self.lists.setdefault(key, []).extend(values)

    async def expire(self, key, ttl):
        pass

    async def lrange(self, key, start, end):
        return list(self.lists.get(key, []))

    async def delete(self, key):
        self.lists.pop(key, None)
        self.values.pop(key, None)

    async def ltrim(self, key, start, end):
        rest = self.lists.get(key, [])[start:]
        if rest:
            self.lists[key] = rest
        else:
            self.lists.pop(key, None)

    async def llen(self, key):
        return len(self.lists.get(key, []))


def entry(**overrides: typing.Any) -> dict[str, typing.Any]:
    return {
        'org_slug': 'aweber',
        'short_id': 'T-7',
        'ticket_title': 'Fix the build',
        'recipient': 'ada@example.com',
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
            ticket_requests.links.settings._slackbot_settings = None
            try:
                spec = ticket_requests.form_spec(entry())
            finally:
                ticket_requests.links.settings._slackbot_settings = None
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
        self.valkey = FakeValkey()
        patcher = mock.patch.object(
            ticket_requests.valkey, 'get_client', return_value=self.valkey
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def stored(self) -> forms.FormRecord:
        (form_id,) = self.store._records
        record = await self.store.get(form_id)
        assert record is not None
        return record


class PostTests(FlowTestCase):
    async def test_recipient_first_even_with_a_channel(self) -> None:
        await ticket_requests.post(
            self.slack, self.runtime, entry(slack_channel='#ops')
        )
        self.assertEqual(['D-U1'], [p['channel'] for p in self.slack.posts])
        record = await self.stored()
        self.assertEqual(
            'r-1', record.metadata['ticket_request']['request_id']
        )

    async def test_earlier_entry_goes_to_the_owner(self) -> None:
        legacy = entry(owner='ada@example.com')
        del legacy['recipient']
        await ticket_requests.post(self.slack, self.runtime, legacy)
        self.assertEqual(['D-U1'], [p['channel'] for p in self.slack.posts])

    async def test_escalation_goes_to_the_channel_by_name(self) -> None:
        await ticket_requests.post(
            self.slack,
            self.runtime,
            entry(slack_channel='#ops', escalation=True),
        )
        self.assertEqual(['C2'], [p['channel'] for p in self.slack.posts])

    async def test_escalation_goes_to_the_channel_by_id(self) -> None:
        await ticket_requests.post(
            self.slack,
            self.runtime,
            entry(slack_channel='C9', escalation=True),
        )
        self.assertEqual(['C9'], [p['channel'] for p in self.slack.posts])

    async def test_channel_when_the_recipient_is_not_in_slack(self) -> None:
        await ticket_requests.post(
            self.slack,
            self.runtime,
            entry(recipient='bob@example.com', slack_channel='ops'),
        )
        self.assertEqual(['C2'], [p['channel'] for p in self.slack.posts])

    async def test_channel_when_the_direct_message_is_rejected(self) -> None:
        rejected = errors.SlackApiError('rejected', {'error': 'rejected'})
        # The direct message channel cannot be opened.
        self.slack.conversations_open = mock.AsyncMock(side_effect=rejected)
        await ticket_requests.post(
            self.slack, self.runtime, entry(slack_channel='ops')
        )
        self.assertEqual(['C2'], [p['channel'] for p in self.slack.posts])

    async def test_channel_when_the_direct_post_is_rejected(self) -> None:
        post = self.slack.chat_postMessage

        async def reject_direct(channel, text=None, **kw):
            if channel.startswith('D-'):
                raise errors.SlackApiError('rejected', {'error': 'rejected'})
            return await post(channel, text, **kw)

        self.slack.chat_postMessage = reject_direct
        await ticket_requests.post(
            self.slack, self.runtime, entry(slack_channel='ops')
        )
        self.assertEqual(['C2'], [p['channel'] for p in self.slack.posts])

    async def test_ambiguous_direct_post_error_is_raised(self) -> None:
        post = self.slack.chat_postMessage

        async def accept_then_fail(channel, text=None, **kw):
            await post(channel, text, **kw)
            raise errors.SlackApiError(
                'internal_error', {'error': 'internal_error'}
            )

        self.slack.chat_postMessage = accept_then_fail
        with self.assertRaises(errors.SlackApiError):
            await ticket_requests.post(
                self.slack, self.runtime, entry(slack_channel='ops')
            )
        self.assertEqual(['D-U1'], [p['channel'] for p in self.slack.posts])

    async def test_non_200_direct_post_error_is_raised(self) -> None:
        post = self.slack.chat_postMessage

        class BadGateway(Resp):
            status_code = 502

        response = BadGateway(ok=False, error='Received a non-JSON response')

        async def accept_then_fail(channel, text=None, **kw):
            await post(channel, text, **kw)
            raise errors.SlackApiError('bad gateway', response)

        self.slack.chat_postMessage = accept_then_fail
        with self.assertRaises(errors.SlackApiError):
            await ticket_requests.post(
                self.slack, self.runtime, entry(slack_channel='ops')
            )
        self.assertEqual(['D-U1'], [p['channel'] for p in self.slack.posts])

    async def test_timeout_on_the_direct_message_is_raised(self) -> None:
        self.slack.conversations_open = mock.AsyncMock(
            side_effect=TimeoutError
        )
        with self.assertRaises(TimeoutError):
            await ticket_requests.post(
                self.slack, self.runtime, entry(slack_channel='ops')
            )
        self.assertEqual([], self.slack.posts)

    async def test_nowhere_to_post(self) -> None:
        for overrides in (
            {'recipient': 'bob@example.com'},
            {'recipient': 'bob@example.com', 'slack_channel': '#nope'},
            {'escalation': True, 'slack_channel': 'C404'},
        ):
            with self.subTest(**overrides):
                await ticket_requests.post(
                    self.slack, self.runtime, entry(**overrides)
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


RESOLVED = {
    'resolved': True,
    'short_id': 'T-7',
    'request_id': 'r-1',
    'status': 'answered',
    'answer': '<!channel> use main',
    'resolved_by': 'ada@example.com',
}


class CloseTests(FlowTestCase):
    async def test_each_message_shows_the_decision(self) -> None:
        await ticket_requests.post(self.slack, self.runtime, entry())
        await ticket_requests.post(
            self.slack,
            self.runtime,
            entry(escalation=True, slack_channel='#ops'),
        )
        await ticket_requests.close(self.slack, RESOLVED)
        self.assertEqual(
            [('D-U1', 'ts1'), ('C2', 'ts2')],
            [(u['channel'], u['ts']) for u in self.slack.updates],
        )
        blocks = self.slack.updates[0]['blocks']
        self.assertEqual('T-7 answered', blocks[0]['text']['text'])
        self.assertIn('Triage Bot asked: **Which branch?**', blocks[1]['text'])
        # The answer is plain text, so it cannot notify the channel.
        self.assertEqual(
            {
                'type': 'plain_text',
                'text': '<!channel> use main',
                'emoji': True,
            },
            blocks[2]['text'],
        )
        self.assertEqual(
            'Answered by ada@example.com', blocks[3]['elements'][0]['text']
        )
        # The channel message does not show the answer.
        channel = self.slack.updates[1]['blocks']
        self.assertEqual(3, len(channel))
        self.assertNotIn('use main', str(channel))
        self.assertEqual({}, self.valkey.lists)

    async def test_failed_update_does_not_stop_the_others(self) -> None:
        key = ticket_requests._messages_key('r-1')
        for channel in ('C404', 'C2'):
            await self.valkey.rpush(
                key,
                orjson.dumps({'channel': channel, 'ts': 't', 'summary': ''}),
            )
        await ticket_requests.close(
            self.slack, RESOLVED | {'status': 'rejected', 'answer': None}
        )
        (update,) = self.slack.updates
        self.assertEqual('C2', update['channel'])
        self.assertEqual(3, len(update['blocks']))
        # A message that is gone is not tried again.
        self.assertEqual({}, self.valkey.lists)

    async def test_temporary_failure_is_tried_again(self) -> None:
        key = ticket_requests._messages_key('r-1')
        for channel in ('C500', 'C2'):
            await self.valkey.rpush(
                key,
                orjson.dumps({'channel': channel, 'ts': 't', 'summary': ''}),
            )
        for tries in range(1, ticket_requests._CLOSE_TRIES):
            with self.assertRaises(ticket_requests._Retry):
                await ticket_requests.close(self.slack, RESOLVED)
            (kept,) = self.valkey.lists[key]
            self.assertEqual(
                {'channel': 'C500', 'ts': 't', 'summary': '', 'tries': tries},
                orjson.loads(kept),
            )
        # The last try drops the message.
        await ticket_requests.close(self.slack, RESOLVED)
        self.assertEqual({}, self.valkey.lists)
        self.assertEqual(['C2'], [u['channel'] for u in self.slack.updates])

    async def test_failed_write_keeps_the_messages(self) -> None:
        key = ticket_requests._messages_key('r-1')
        record = orjson.dumps({'channel': 'C500', 'ts': 't', 'summary': ''})
        await self.valkey.rpush(key, record)
        with (
            mock.patch.object(
                self.valkey, 'rpush', side_effect=ConnectionError
            ),
            self.assertRaises(ticket_requests._Retry),
        ):
            await ticket_requests.close(self.slack, RESOLVED)
        self.assertEqual([record], self.valkey.lists[key])

    async def test_message_added_during_close_is_kept(self) -> None:
        key = ticket_requests._messages_key('r-1')
        late = orjson.dumps({'channel': 'C3', 'ts': 't', 'summary': ''})
        await self.valkey.rpush(
            key, orjson.dumps({'channel': 'C2', 'ts': 't', 'summary': ''})
        )
        update = self.slack.chat_update

        async def chat_update(**kw):
            # A post of the same request remembers its message now.
            await self.valkey.rpush(key, late)
            return await update(**kw)

        with (
            mock.patch.object(self.slack, 'chat_update', chat_update),
            self.assertRaises(ticket_requests._Retry),
        ):
            await ticket_requests.close(self.slack, RESOLVED)
        self.assertEqual([late], self.valkey.lists[key])

    async def test_post_after_close_adds_the_close_again(self) -> None:
        # close() ran before the post kept its message.
        await ticket_requests.close(self.slack, RESOLVED)
        await ticket_requests.post(self.slack, self.runtime, entry())
        (added,) = self.valkey.stream
        self.assertEqual(RESOLVED, orjson.loads(added['request']))
        # The added entry closes the new form.
        await ticket_requests.close(self.slack, RESOLVED)
        self.assertEqual(
            [('D-U1', 'ts1')],
            [(u['channel'], u['ts']) for u in self.slack.updates],
        )
        self.assertEqual({}, self.valkey.lists)

    async def test_concurrent_close_is_tried_again(self) -> None:
        key = ticket_requests._messages_key('r-1')
        record = orjson.dumps({'channel': 'C2', 'ts': 't', 'summary': ''})
        await self.valkey.rpush(key, record)
        await self.valkey.set(f'{key}:closing', b'1')
        with self.assertRaises(ticket_requests._Retry):
            await ticket_requests.close(self.slack, RESOLVED)
        self.assertEqual([], self.slack.updates)
        self.assertEqual([record], self.valkey.lists[key])
        # The lock of the other consumer stays.
        self.assertIn(f'{key}:closing', self.valkey.values)

    async def test_failed_read_is_tried_again(self) -> None:
        with (
            mock.patch.object(
                self.valkey, 'lrange', side_effect=ConnectionError
            ),
            self.assertRaises(ticket_requests._Retry),
        ):
            await ticket_requests.close(self.slack, RESOLVED)

    async def test_unknown_request_changes_nothing(self) -> None:
        await ticket_requests.close(self.slack, RESOLVED)
        self.assertEqual([], self.slack.updates)


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

        class Client(ticket_requests.identity.api.Imbi):
            def __init__(self, **kw: typing.Any) -> None:
                super().__init__(**kw)
                self._transport = transport

        user = identity.ImbiUser('ada@example.com', 'Ada')
        with (
            mock.patch.object(ticket_requests.identity.api, 'Imbi', Client),
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
        client.get.return_value = None
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

    async def test_resolved_entry_closes_the_forms(self) -> None:
        client = mock.AsyncMock()
        client.xautoclaim.return_value = ['0-0', [], []]
        message = (b'1-0', {b'request': orjson.dumps(RESOLVED)})
        client.xreadgroup.side_effect = [
            [[b'imbi:ticket-requests', [message]]],
            asyncio.CancelledError(),
        ]
        close = mock.AsyncMock()
        with (
            mock.patch.object(
                ticket_requests.valkey, 'get_client', return_value=client
            ),
            mock.patch.object(ticket_requests, 'close', close),
            self.assertRaises(asyncio.CancelledError),
        ):
            await ticket_requests.consume(self.slack, self.runtime)
        close.assert_awaited_once_with(self.slack, RESOLVED)
        self.assertEqual([], self.slack.posts)
        client.xack.assert_awaited_once()

    async def test_retry_is_not_acked(self) -> None:
        client = mock.AsyncMock()
        client.xautoclaim.return_value = ['0-0', [], []]
        message = (b'1-0', {b'request': orjson.dumps(RESOLVED)})
        client.xreadgroup.side_effect = [
            [[b'imbi:ticket-requests', [message]]],
            asyncio.CancelledError(),
        ]
        close = mock.AsyncMock(side_effect=ticket_requests._Retry('x'))
        with (
            mock.patch.object(
                ticket_requests.valkey, 'get_client', return_value=client
            ),
            mock.patch.object(ticket_requests, 'close', close),
            self.assertRaises(asyncio.CancelledError),
        ):
            await ticket_requests.consume(self.slack, self.runtime)
        client.xack.assert_not_awaited()
