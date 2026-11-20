"""Tests for ticket type, due date, labels, roles, and backlog rank."""

import typing
import unittest
from unittest import mock

import httpx

from apps.api.tests.endpoints import test_person_tickets
from imbi.api.endpoints import tickets as tickets_api
from imbi.api.llm.dependencies import _get_anthropic_client
from imbi.api.tickets import store
from imbi.common.llm import AnthropicClient, CompletionResult
from imbi.common.prompts import system as system_prompts


class NormalizeLabelTests(unittest.TestCase):
    def test_normalize(self) -> None:
        for raw, want in [
            ('API', 'api'),
            ('api-', 'api'),
            (' Api ', 'api'),
            ('Front_End  work', 'front-end-work'),
            ('a--b', 'a-b'),
            ('--x.y--', 'x.y'),
            ('!!!', ''),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(store.normalize_label(raw), want)

    def test_normalize_labels_drops_repeats(self) -> None:
        self.assertEqual(
            store.normalize_labels(['API', 'api-', 'web']), ['api', 'web']
        )


class TicketAttributeTests(test_person_tickets.PersonTicketTestCase):
    async def make(self, **body: typing.Any) -> dict[str, typing.Any]:
        response = await self.create_person(**body)
        self.assertEqual(response.status_code, 201, response.text)
        return typing.cast(dict[str, typing.Any], response.json())

    async def rank(self, short_id: str, after: str | None) -> httpx.Response:
        return await self.client.post(
            self.url(f'{short_id}/rank'), json={'after': after}
        )

    async def backlog(self) -> list[str]:
        response = await self.client.get(
            self.url(), params={'group': 'queued'}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return [t['short_id'] for t in response.json()]

    async def test_create_defaults(self) -> None:
        task = await self.make()
        self.assertEqual(task['type'], 'task')
        self.assertIsNone(task['due_date'])
        self.assertEqual(task['labels'], [])
        self.assertEqual(task['roles'], {})
        self.assertIsNone(task['backlog_rank'])

    async def test_create_normalizes_labels_and_roles(self) -> None:
        task = await self.make(
            type='bug',
            due_date='2026-12-01',
            labels=['API', 'api-', 'Front End'],
            roles={'Code Reviewer': self.member},
        )
        self.assertEqual(task['type'], 'bug')
        self.assertEqual(task['due_date'], '2026-12-01')
        self.assertEqual(task['labels'], ['api', 'front-end'])
        self.assertEqual(task['roles'], {'code-reviewer': self.member})

    async def test_create_refuses_bad_values(self) -> None:
        for body in (
            {'labels': ['!!!']},
            {'labels': ['x' * 51]},
            {'roles': {'QA': self.member, 'qa': self.email}},
            {'type': 'epic'},
        ):
            with self.subTest(body=body):
                response = await self.create_person(**body)
                self.assertEqual(response.status_code, 422, response.text)

    async def test_create_refuses_role_outside_org(self) -> None:
        response = await self.create_person(
            roles={'qa': 'stranger@example.com'}
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn('stranger@example.com', response.text)

    async def test_update_writes_one_event_per_change(self) -> None:
        task = await self.make(labels=['api'])
        response = await self.client.patch(
            self.url(task['short_id']),
            json={
                'type': 'feature',
                'due_date': '2027-01-02',
                'labels': ['API', 'Docs'],
                'roles': {'QA': self.member},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['type'], 'feature')
        self.assertEqual(body['labels'], ['api', 'docs'])
        self.assertEqual(body['roles'], {'qa': self.member})
        events = await self.store.events(task['id'], 0, 100)
        changes = {
            e['type']: e['payload']
            for e in events
            if e['type'].endswith('.changed')
        }
        self.assertEqual(
            changes['labels.changed'],
            {'from': ['api'], 'to': ['api', 'docs']},
        )
        self.assertEqual(
            changes['due_date.changed'], {'from': None, 'to': '2027-01-02'}
        )
        self.assertEqual(
            changes['type.changed'], {'from': 'task', 'to': 'feature'}
        )
        self.assertIn('roles.changed', changes)

    async def test_update_leaves_unsent_fields(self) -> None:
        task = await self.make(type='bug', due_date='2026-12-01')
        response = await self.client.patch(
            self.url(task['short_id']), json={'due_date': None}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()['due_date'])
        self.assertEqual(response.json()['type'], 'bug')
        response = await self.client.patch(
            self.url(task['short_id']), json={'labels': None}
        )
        self.assertEqual(response.status_code, 422)

    async def test_update_needs_manage(self) -> None:
        task = await self.make()
        self.permissions.discard('ticket:manage')
        response = await self.client.patch(
            self.url(task['short_id']), json={'type': 'bug'}
        )
        self.assertEqual(response.status_code, 403)

    async def test_label_filter_and_suggestions(self) -> None:
        a = await self.make(labels=['api', 'web'])
        await self.make(labels=['api'])
        await self.make(labels=['api-docs'])
        response = await self.client.get(
            self.url(), params=[('label', 'API'), ('label', 'web')]
        )
        self.assertEqual(
            [t['short_id'] for t in response.json()], [a['short_id']]
        )
        response = await self.client.get(
            self.url('labels'), params={'q': 'API'}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            [{'name': 'api', 'count': 2}, {'name': 'api-docs', 'count': 1}],
        )

    async def test_rank_orders_the_backlog(self) -> None:
        t1 = (await self.make())['short_id']
        t2 = (await self.make())['short_id']
        t3 = (await self.make())['short_id']
        # Unranked: newest first.
        self.assertEqual(await self.backlog(), [t3, t2, t1])
        response = await self.rank(t1, None)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(await self.backlog(), [t1, t3, t2])
        # After an unranked ticket: the ones down to it get ranks too.
        response = await self.rank(t3, t2)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(await self.backlog(), [t1, t2, t3])
        response = await self.rank(t3, t1)
        self.assertEqual(await self.backlog(), [t1, t3, t2])
        events = await self.store.events(response.json()['id'], 0, 100)
        self.assertEqual(events[-1]['type'], 'rank.changed')
        self.assertEqual(events[-1]['payload']['after'], t1)

    async def test_rank_renumbers_when_ranks_meet(self) -> None:
        t1 = (await self.make())['short_id']
        t2 = (await self.make())['short_id']
        t3 = (await self.make())['short_id']
        await self.rank(t1, None)
        await self.rank(t2, t1)
        await self.rank(t3, t2)
        # Each move halves the gap after t1, until a renumber.
        for _ in range(40):
            await self.rank(t3, t1)
            await self.rank(t2, t1)
        self.assertEqual(await self.backlog(), [t1, t2, t3])

    async def test_rank_after_unknown_ticket(self) -> None:
        task = await self.make()
        response = await self.rank(task['short_id'], 'T-999')
        self.assertEqual(response.status_code, 422)
        response = await self.rank(task['short_id'], task['short_id'])
        self.assertEqual(response.status_code, 422)
        response = await self.rank('T-999', None)
        self.assertEqual(response.status_code, 404)


class SubjectFromTests(unittest.TestCase):
    def test_first_line_without_links(self) -> None:
        self.assertEqual(
            tickets_api.subject_from(
                'Fix the crash https://sentry.io/issues/1\nmore'
            ),
            'Fix the crash',
        )
        self.assertEqual(
            tickets_api.subject_from('https://x.y/z'), 'Work from a link'
        )
        self.assertEqual(len(tickets_api.subject_from('x' * 200)), 96)


class TicketSubjectTests(test_person_tickets.PersonTicketTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.anthropic = mock.MagicMock(spec=AnthropicClient)
        self.test_app.dependency_overrides[_get_anthropic_client] = lambda: (
            self.anthropic
        )
        self.addCleanup(
            self.test_app.dependency_overrides.pop, _get_anthropic_client
        )

    async def suggest(self, description: str) -> httpx.Response:
        return await self.client.post(
            self.url('subject'), json={'description': description}
        )

    async def test_uses_the_model_answer(self) -> None:
        self.anthropic.complete_json = mock.AsyncMock(
            return_value=CompletionResult(
                data=tickets_api.TicketSubject(
                    subject='Handle a null owner team in the deployments list'
                ),
                degraded=False,
            )
        )
        response = await self.suggest('The deployments list returns 500.')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {
                'subject': 'Handle a null owner team in the deployments list',
                'degraded': False,
            },
        )
        call = self.anthropic.complete_json.call_args
        self.assertEqual(call.args[0], 'The deployments list returns 500.')
        # Not seeded in the test graph: the packaged prompt.
        self.assertTrue(
            call.kwargs['system'].startswith(
                system_prompts.TICKET_SUBJECT.text()
            )
        )
        self.assertIn('JSON object', call.kwargs['system'])

    async def test_sends_only_the_start_of_a_long_description(self) -> None:
        self.anthropic.complete_json = mock.AsyncMock(
            return_value=CompletionResult(
                data=tickets_api.TicketSubject(subject='Build the map site'),
                degraded=False,
            )
        )
        response = await self.suggest('Build it\n' + 'x' * 30_000)
        self.assertEqual(response.status_code, 200, response.text)
        sent = self.anthropic.complete_json.call_args.args[0]
        self.assertEqual(len(sent), tickets_api.SUBJECT_INPUT_LENGTH)

    async def test_falls_back_to_the_first_line(self) -> None:
        async def degraded(
            *_args: typing.Any, fallback: typing.Any, **_kwargs: typing.Any
        ) -> CompletionResult[typing.Any]:
            return CompletionResult(data=fallback, degraded=True)

        self.anthropic.complete_json = mock.AsyncMock(side_effect=degraded)
        response = await self.suggest('Rotate the key\nIt expires soon.')
        self.assertEqual(
            response.json(), {'subject': 'Rotate the key', 'degraded': True}
        )

    async def test_no_model_reads_no_prompt(self) -> None:
        self.anthropic.available = False
        with mock.patch.object(system_prompts, 'load_system_prompt') as load:
            response = await self.suggest('Rotate the key\nIt expires.')
        self.assertEqual(
            response.json(), {'subject': 'Rotate the key', 'degraded': True}
        )
        load.assert_not_called()
        self.anthropic.complete_json.assert_not_called()

    async def test_needs_create(self) -> None:
        self.permissions.discard('ticket:create')
        response = await self.suggest('x')
        self.assertEqual(response.status_code, 403)
