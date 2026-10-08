"""Tests for the human actions on agent tasks (ADR 0020, P3).

A person resolves the requests that a harness opens, and replies to the
agent. These run against the live Postgres that ``root:services`` boots.
The caller is the service account of the agent, unless a test says
otherwise.
"""

import asyncio
import datetime
import typing
import uuid

import httpx

from apps.api.tests.endpoints import (
    test_agent_task_harness,
    test_agent_tasks,
)
from imbi.api import agent_tasks, models
from imbi.api.auth import permissions
from scripts import agent_task_client

FEEDBACK = {'kind': 'feedback', 'title': 'Which repo?', 'options': ['a']}
APPROVAL = {
    'kind': 'approval',
    'title': 'Merge 1 file into main',
    'artifacts': [{'name': 'diff', 'digest': 'sha256:ab'}],
    'artifact_digests': ['sha256:ab'],
}


class ActionTestCase(test_agent_task_harness.HarnessTestCase):
    async def open_request(
        self, body: dict[str, typing.Any], **extra: typing.Any
    ) -> dict[str, typing.Any]:
        response = await self.post('requests', {**body, **extra})
        self.assertIn(response.status_code, (200, 201), response.text)
        return response.json()

    async def resolve(
        self, request_id: str, **body: typing.Any
    ) -> httpx.Response:
        return await self.as_user(
            'POST', f'T-1/requests/{request_id}/resolve', json=body
        )

    def act_as_person(self, email: str) -> None:
        """Make the person in :meth:`as_user` someone else."""
        self.user = models.User(
            id=email,
            email=email,
            display_name=email,
            is_active=True,
            is_admin=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )


class ResolveTests(ActionTestCase):
    async def test_answer_unblocks_and_the_client_reads_it(self) -> None:
        session = (await self.open_session())['session']
        opened = await self.open_request(FEEDBACK, session_id=session['id'])
        request_id = opened['request']['id']
        await self.post(f'sessions/{session["id"]}/close', {'reason': 'wait'})

        response = await self.resolve(
            request_id, status='answered', answer='a', constraints=['no prod']
        )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body['request']['status'], 'answered')
        self.assertEqual(body['request']['resolved_by'], self.email)
        self.assertIsNotNone(body['request']['resolved_at'])
        self.assertEqual(
            body['request']['resolution'],
            {
                'answer': 'a',
                'constraints': ['no prod'],
                'artifact_digests': None,
                'channel': 'web',
            },
        )
        # No session is open, so the task waits for a harness again.
        self.assertEqual(body['task']['status'], 'queued')

        # The harness reads the answer by seq, as its service account.
        harness = agent_task_client.HarnessClient(self.client, self.org, 'T-1')
        event = await harness.wait_for_answer(
            request_id, opened['task']['last_seq'], interval=0.01
        )
        self.assertEqual(event['actor_kind'], 'human')
        self.assertEqual(event['actor_id'], self.email)
        self.assertEqual(event['channel'], 'web')
        self.assertEqual(event['payload']['answer'], 'a')
        self.assertEqual(event['payload']['status'], 'answered')
        self.assertEqual(event['payload']['constraints'], ['no prod'])
        events = await harness.events(event['seq'])
        self.assertEqual(
            [(e['type'], e['payload']['to']) for e in events],
            [('state.changed', 'queued')],
        )

    async def test_resolve_with_a_session_open_runs_the_task(self) -> None:
        await self.open_session()
        opened = await self.open_request(FEEDBACK)
        response = await self.resolve(
            opened['request']['id'], status='answered', answer='a'
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['task']['status'], 'running')

    async def test_task_stays_blocked_while_a_request_is_open(self) -> None:
        await self.open_session()
        first = await self.open_request(FEEDBACK)
        await self.open_request(APPROVAL)
        response = await self.resolve(
            first['request']['id'], status='answered', answer='a'
        )
        self.assertEqual(response.json()['task']['status'], 'blocked')

    async def test_approval_binds_to_the_digests(self) -> None:
        opened = await self.open_request(APPROVAL)
        request_id = opened['request']['id']
        response = await self.resolve(
            request_id, status='approved', artifact_digests=['sha256:cd']
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['error'], 'digest_mismatch')
        self.assertEqual((await self.task_row())['status'], 'blocked')
        self.assertNotIn(
            'request.resolved', [e['type'] for e in await self.events()]
        )

        response = await self.resolve(
            request_id, status='approved', artifact_digests=['sha256:ab']
        )
        self.assertEqual(response.status_code, 201, response.text)
        request = response.json()['request']
        self.assertEqual(request['status'], 'approved')
        self.assertEqual(
            request['resolution']['artifact_digests'], ['sha256:ab']
        )

    async def test_reject_needs_no_digests(self) -> None:
        opened = await self.open_request(APPROVAL)
        response = await self.resolve(
            opened['request']['id'], status='rejected', answer='Too big.'
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['request']['status'], 'rejected')
        self.assertIsNone(
            response.json()['request']['resolution']['artifact_digests']
        )

    async def test_second_resolution_collapses(self) -> None:
        opened = await self.open_request(APPROVAL)
        request_id = opened['request']['id']
        response = await self.resolve(
            request_id, status='approved', artifact_digests=['sha256:ab']
        )
        self.assertEqual(response.status_code, 201, response.text)
        last_seq = (await self.task_row())['last_seq']

        # The same person and resolution again: idempotent (I4).
        response = await self.resolve(
            request_id, status='approved', artifact_digests=['sha256:ab']
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['request']['status'], 'approved')

        # Another resolution, or another person: a conflict that names
        # who resolved it.
        response = await self.resolve(request_id, status='rejected')
        self.assertEqual(response.status_code, 409, response.text)
        response = await self.resolve(
            request_id, status='approved', artifact_digests=['sha256:cd']
        )
        self.assertEqual(response.status_code, 409, response.text)
        response = await self.resolve(
            request_id,
            status='approved',
            artifact_digests=['sha256:ab'],
            answer='Ship it.',
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.act_as_person(self.member)
        response = await self.resolve(
            request_id, status='approved', artifact_digests=['sha256:ab']
        )
        self.assertEqual(response.status_code, 409, response.text)
        detail = response.json()['detail']
        self.assertEqual(detail['error'], 'request_resolved')
        self.assertEqual(detail['status'], 'approved')
        self.assertEqual(detail['resolved_by'], self.email)
        self.assertEqual((await self.task_row())['last_seq'], last_seq)

    async def test_resolution_must_fit_the_kind(self) -> None:
        feedback = (await self.open_request(FEEDBACK))['request']['id']
        approval = (await self.open_request(APPROVAL))['request']['id']
        for request_id, body in (
            (feedback, {'status': 'approved', 'artifact_digests': ['x']}),
            (feedback, {'status': 'rejected'}),
            (approval, {'status': 'answered', 'answer': 'yes'}),
            (approval, {'status': 'approved'}),
            (feedback, {'status': 'answered'}),
            (feedback, {'status': 'other'}),
        ):
            with self.subTest(body=body):
                response = await self.resolve(request_id, **body)
                self.assertEqual(response.status_code, 422, response.text)

    async def test_expired_request_cannot_be_resolved(self) -> None:
        opened = await self.open_request(FEEDBACK)
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE agent_runtime.requests'
                " SET expires_at = NOW() - INTERVAL '1 minute' WHERE id = %s",
                (uuid.UUID(opened['request']['id']),),
            )
        response = await self.resolve(
            opened['request']['id'], status='answered', answer='a'
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['error'], 'request_expired')

    async def test_unknown_request_is_404(self) -> None:
        response = await self.resolve(
            str(uuid.uuid4()), status='answered', answer='a'
        )
        self.assertEqual(response.status_code, 404, response.text)

    async def test_closed_task_refuses_resolution(self) -> None:
        opened = await self.open_request(FEEDBACK)
        await self.post('outcome', {'outcome': 'done_acted'})
        response = await self.resolve(
            opened['request']['id'], status='answered', answer='a'
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['error'], 'task_closed')


class ResolveAccessTests(ActionTestCase):
    async def test_unauthorized_user_cannot_approve(self) -> None:
        opened = await self.open_request(APPROVAL)
        self.permissions = set(test_agent_tasks.ALL_PERMISSIONS) - {
            'agent_task:resolve'
        }
        response = await self.resolve(
            opened['request']['id'],
            status='approved',
            artifact_digests=['sha256:ab'],
        )
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn('agent_task:resolve', response.text)
        self.assertEqual((await self.task_row())['status'], 'blocked')

    async def test_agent_cannot_resolve_its_own_request(self) -> None:
        opened = await self.open_request(APPROVAL)

        # Even with the permission, a service account is not a person.
        async def agent_with_permission() -> permissions.AuthContext:
            return permissions.AuthContext(
                service_account=self.account,
                auth_method='client_credentials',
                permissions={'agent_task:resolve'},
            )

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            agent_with_permission
        )
        response = await self.client.post(
            self.url(f'T-1/requests/{opened["request"]["id"]}/resolve'),
            json={'status': 'approved', 'artifact_digests': ['sha256:ab']},
        )
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn('requires user authentication', response.text)
        self.assertEqual((await self.task_row())['status'], 'blocked')


class RequestKeyTests(ActionTestCase):
    async def test_same_key_returns_the_same_request(self) -> None:
        first = await self.open_request(APPROVAL, request_key='merge-1')
        response = await self.post(
            'requests', {**APPROVAL, 'request_key': 'merge-1'}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['request'], first['request'])
        self.assertEqual(
            [e['type'] for e in await self.events()].count('request.opened'),
            1,
        )
        # A resolved request is returned too, with its resolution.
        await self.resolve(
            first['request']['id'],
            status='approved',
            artifact_digests=['sha256:ab'],
        )
        response = await self.post(
            'requests', {**APPROVAL, 'request_key': 'merge-1'}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['request']['status'], 'approved')

    async def test_same_key_with_other_digests_is_a_conflict(self) -> None:
        await self.open_request(APPROVAL, request_key='merge-1')
        response = await self.post(
            'requests',
            {
                **APPROVAL,
                'artifact_digests': ['sha256:cd'],
                'request_key': 'merge-1',
            },
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            response.json()['detail']['error'], 'request_key_conflict'
        )

    async def test_requests_without_a_key_do_not_collide(self) -> None:
        first = await self.open_request(FEEDBACK)
        second = await self.open_request(FEEDBACK)
        self.assertNotEqual(first['request']['id'], second['request']['id'])


class ReplyTests(ActionTestCase):
    async def reply(self, **body: typing.Any) -> httpx.Response:
        return await self.as_user('POST', 'T-1/reply', json=body)

    async def test_reply_is_a_human_turn(self) -> None:
        await self.open_session()
        last_seq = (await self.task_row())['last_seq']
        response = await self.reply(body='Use the staging repo.')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'running')
        self.assertEqual(response.json()['control'], 'run')
        harness = agent_task_client.HarnessClient(self.client, self.org, 'T-1')
        (turn,) = await harness.events(last_seq)
        self.assertEqual(turn['type'], 'turn')
        self.assertEqual(turn['actor_kind'], 'human')
        self.assertEqual(turn['actor_id'], self.email)
        self.assertEqual(turn['channel'], 'web')
        self.assertEqual(turn['payload'], {'body': 'Use the staging repo.'})

    async def test_reply_and_hold_pauses(self) -> None:
        await self.open_session()
        response = await self.reply(body='Stop here.', hold=True)
        self.assertEqual(response.status_code, 200, response.text)
        # A session is open, so the harness acts on the pause.
        self.assertEqual(response.json()['control'], 'pause')
        self.assertEqual(response.json()['status'], 'running')
        self.assertEqual(
            [e['type'] for e in (await self.events())[-2:]],
            ['turn', 'control.changed'],
        )

    async def test_api_key_reply_has_the_api_channel(self) -> None:
        self.auth_method = 'api_key'
        await self.reply(body='Hello.')
        self.assertEqual((await self.events())[-1]['channel'], 'api')

    async def test_reply_needs_a_person(self) -> None:
        response = await self.client.post(
            self.url('T-1/reply'), json={'body': 'Hello.'}
        )
        self.assertEqual(response.status_code, 403, response.text)

    async def test_reply_to_a_closed_task_is_refused(self) -> None:
        await self.post('outcome', {'outcome': 'done_acted'})
        response = await self.reply(body='Hello.')
        self.assertEqual(response.status_code, 409, response.text)

    async def test_reply_and_hold_waits_for_a_cancel(self) -> None:
        await self.open_session()
        await self.as_user('POST', 'T-1/cancel')
        last_seq = (await self.task_row())['last_seq']
        response = await self.reply(body='Stop.', hold=True)
        self.assertEqual(response.status_code, 409, response.text)
        # The turn rolls back with the pause.
        self.assertEqual((await self.task_row())['last_seq'], last_seq)


class ClientWaitTests(ActionTestCase):
    async def test_client_waits_for_the_answer_and_finishes(self) -> None:
        slug = f'opus-{uuid.uuid4().hex[:8]}'
        await self.make_model(slug, slug)
        harness = agent_task_client.HarnessClient(self.client, self.org, 'T-1')

        async def answer() -> None:
            while True:
                async with self.pool.connection() as conn:
                    cursor = await conn.execute(
                        'SELECT id FROM agent_runtime.requests'
                        " WHERE task_id = %s AND status = 'open'",
                        (uuid.UUID(self.task['id']),),
                    )
                    row = await cursor.fetchone()
                if row is not None:
                    break
                await asyncio.sleep(0.01)
            await self.store.resolve_request(
                self.org,
                'T-1',
                row[0],
                agent_tasks.Resolution('answered', 'yes', None, None),
                agent_tasks.Actor('human', self.email, 'web'),
            )

        state, _ = await asyncio.wait_for(
            asyncio.gather(
                agent_task_client.run_task(
                    harness, model_id=slug, ask=True, wait=True, interval=0.01
                ),
                answer(),
            ),
            timeout=30,
        )
        self.assertEqual(state['status'], 'closed')
        self.assertEqual(state['outcome'], 'done_acted')
        turns = [
            e['payload']['body']
            for e in await self.events()
            if e['type'] == 'turn'
        ]
        self.assertIn('The answer is yes.', turns)

    async def wait_for_open_request(self) -> uuid.UUID:
        while True:
            async with self.pool.connection() as conn:
                cursor = await conn.execute(
                    'SELECT id FROM agent_runtime.requests'
                    " WHERE task_id = %s AND status = 'open'",
                    (uuid.UUID(self.task['id']),),
                )
                row = await cursor.fetchone()
            if row is not None:
                return row[0]
            await asyncio.sleep(0.01)

    async def run_client(self, person: typing.Any) -> dict[str, typing.Any]:
        slug = f'opus-{uuid.uuid4().hex[:8]}'
        await self.make_model(slug, slug)
        harness = agent_task_client.HarnessClient(self.client, self.org, 'T-1')
        state, _ = await asyncio.wait_for(
            asyncio.gather(
                agent_task_client.run_task(
                    harness, model_id=slug, ask=True, wait=True, interval=0.01
                ),
                person(),
            ),
            timeout=30,
        )
        return state

    async def test_client_stops_when_the_task_is_cancelled(self) -> None:
        human = agent_tasks.Actor('human', self.email, 'web')

        async def cancel() -> None:
            await self.wait_for_open_request()
            await self.store.set_control(self.org, 'T-1', 'cancel', human)

        state = await self.run_client(cancel)
        self.assertEqual(state['status'], 'closed')
        self.assertEqual(state['outcome'], 'cancelled_by_human')

    async def test_client_waits_for_run_after_a_pause(self) -> None:
        human = agent_tasks.Actor('human', self.email, 'web')

        async def pause_then_run() -> None:
            request_id = await self.wait_for_open_request()
            await self.store.set_control(self.org, 'T-1', 'pause', human)
            await self.store.resolve_request(
                self.org,
                'T-1',
                request_id,
                agent_tasks.Resolution('answered', 'yes', None, None),
                human,
            )
            # Read the database, not the API: the API client is the
            # harness's client while run_task works.
            task_id = uuid.UUID(self.task['id'])
            while True:
                async with self.pool.connection() as conn:
                    cursor = await conn.execute(
                        'SELECT count(*) FROM agent_runtime.sessions'
                        " WHERE task_id = %s AND session_key LIKE '%%-2'",
                        (task_id,),
                    )
                    row = await cursor.fetchone()
                if row and row[0]:
                    break
                await asyncio.sleep(0.01)
            # The paused client writes no work.
            async with self.pool.connection() as conn:
                cursor = await conn.execute(
                    'SELECT count(*) FROM agent_runtime.events'
                    " WHERE task_id = %s AND type = 'turn'"
                    " AND payload->>'body' = 'The answer is yes.'",
                    (task_id,),
                )
                row = await cursor.fetchone()
            self.assertEqual(row, (0,))
            await self.store.set_control(self.org, 'T-1', 'run', human)

        state = await self.run_client(pause_then_run)
        self.assertEqual(state['outcome'], 'done_acted')


class SizeTests(ActionTestCase):
    """Human input is bounded like harness input."""

    #: Fewer characters than the field limit, more bytes than the payload
    #: limit: each 'é' is two bytes of JSON.
    WIDE = 'é' * 40_000

    async def test_resolution_is_bounded(self) -> None:
        request_id = (await self.open_request(FEEDBACK))['request']['id']
        response = await self.resolve(
            request_id, status='answered', answer=self.WIDE
        )
        self.assertEqual(response.status_code, 413, response.text)
        self.assertEqual(
            response.json()['detail']['error'], 'payload_too_large'
        )
        for body in (
            {'answer': 'x' * 70_000},
            {'answer': 'a', 'constraints': ['x'] * 51},
            {'answer': 'a', 'constraints': ['x' * 1001]},
            {'answer': 'a', 'constraints': ['']},
        ):
            with self.subTest(body=list(body)):
                response = await self.resolve(
                    request_id, status='answered', **body
                )
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual((await self.task_row())['status'], 'blocked')

    async def test_reply_is_bounded(self) -> None:
        last_seq = (await self.task_row())['last_seq']
        response = await self.as_user(
            'POST', 'T-1/reply', json={'body': self.WIDE}
        )
        self.assertEqual(response.status_code, 413, response.text)
        response = await self.as_user(
            'POST', 'T-1/reply', json={'body': 'x' * 70_000}
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual((await self.task_row())['last_seq'], last_seq)
