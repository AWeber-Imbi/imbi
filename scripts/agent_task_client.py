"""Reference harness client for agent tasks (ADR 0020).

This works one task from start to end through the harness endpoints,
as the service account of the task's agent. It opens a session, writes
phases, turns, and a tool call, reports usage, and sets the outcome
``done_acted``. With ``--ask`` it opens a feedback request instead and
leaves the task ``blocked``. With ``--ask --wait`` it then reads the log
by seq until a person answers, and finishes the task. The tests use
:class:`HarnessClient` and :func:`run_task`; the dev environment uses
the command line.

Credentials in the dev environment
----------------------------------

Each agent has a service account with the slug ``agent-<agent id>``.
As a person with the ``service_account:update`` permission:

1. Get the agent id::

       GET /api/organizations/<org>/agents/<agent slug>

2. Make a client credential for its service account. The response
   shows ``client_secret`` one time only::

       POST /api/service-accounts/agent-<agent id>/client-credentials
       {"name": "reference-harness"}

3. Make a task for the agent (``POST /api/organizations/<org>/agent-tasks/``)
   and give its short id to this script. The script gets a token with
   ``POST /api/auth/token`` (``grant_type=client_credentials``).

Run::

    IMBI_CLIENT_ID=... IMBI_CLIENT_SECRET=... \\
    uv run --frozen python scripts/agent_task_client.py \\
        --api-url https://<your imbi host>/api --org <org> --task T-1 \\
        --model <AI model slug>
"""

import argparse
import asyncio
import json
import os
import typing
import uuid

import httpx

type Body = dict[str, typing.Any]


class HarnessClient:
    """The harness endpoints of one task. Errors raise
    :class:`httpx.HTTPStatusError`."""

    def __init__(
        self, client: httpx.AsyncClient, org: str, short_id: str
    ) -> None:
        self._client = client
        self._path = f'/organizations/{org}/agent-tasks/{short_id}'

    async def _post(self, path: str, body: typing.Any = None) -> typing.Any:
        response = await self._client.post(f'{self._path}/{path}', json=body)
        response.raise_for_status()
        return response.json()

    async def open_session(
        self, key: str, harness_instance: str = 'reference-client'
    ) -> Body:
        return await self._post(
            'sessions',
            {'session_key': key, 'harness_instance': harness_instance},
        )

    async def heartbeat(self, session_id: str) -> Body:
        return await self._post(f'sessions/{session_id}/heartbeat')

    async def close_session(self, session_id: str, reason: str) -> Body:
        return await self._post(
            f'sessions/{session_id}/close', {'reason': reason}
        )

    async def append(self, session_id: str | None, events: list[Body]) -> Body:
        """Write events. Each event gets an ``event_id`` when it has none.

        The ids are set on the dicts in ``events``, so sending the same
        list again after an error writes nothing two times.
        """
        for event in events:
            event.setdefault('event_id', str(uuid.uuid4()))
        return await self._post(
            'events', {'session_id': session_id, 'events': events}
        )

    async def report_usage(
        self, key: str, model_id: str, **tokens: typing.Any
    ) -> Body:
        return await self._post(
            'usage', {'idempotency_key': key, 'model_id': model_id, **tokens}
        )

    async def open_request(self, **request: typing.Any) -> Body:
        """Open a request. A repeat with the same ``request_key`` returns
        the first request."""
        return await self._post('requests', request)

    async def events(self, after_seq: int, limit: int = 100) -> list[Body]:
        """Read the events of the task with ``seq`` after ``after_seq``."""
        response = await self._client.get(
            f'{self._path}/events',
            params={'after_seq': after_seq, 'limit': limit},
        )
        response.raise_for_status()
        return response.json()

    async def wait_for_answer(
        self, request_id: str, after_seq: int, interval: float = 2.0
    ) -> Body:
        """Read the log by seq until the request is resolved; return the
        ``request.resolved`` event. When the task closes first (a person
        cancels it), return the ``outcome.set`` event.

        This is how a harness gets human input (H7): it polls the events
        after the last ``seq`` that it saw.
        """
        while True:
            page = await self.events(after_seq)
            if not page:
                await asyncio.sleep(interval)
            for event in page:
                after_seq = event['seq']
                if event['type'] == 'outcome.set' or (
                    event['type'] == 'request.resolved'
                    and event['payload']['request_id'] == request_id
                ):
                    return event

    async def set_outcome(
        self, outcome: str, reason: str | None = None
    ) -> Body:
        return await self._post(
            'outcome', {'outcome': outcome, 'reason': reason}
        )


def rich_events() -> list[Body]:
    """The events of a long agent run, as the harness writes them.

    They cover what the Conversation tab draws: thinking and warning
    turns, a failed call, a call that policy denied, a subagent with
    its own turn and call nested under the call that started it, and a
    result split into continuation parts. The subagent events come
    before the call that started them, as they do from the harness,
    which writes a call when its result arrives.
    """
    task_call = f'toolu_task_{uuid.uuid4().hex[:8]}'
    big_call = f'toolu_read_{uuid.uuid4().hex[:8]}'
    lines = [f'{n:>4}  line {n} of the file' for n in range(1, 201)]
    return [
        {
            'type': 'turn',
            'payload': {
                'kind': 'thinking',
                'body': 'The build broke after the dependency bump. '
                'Read the failing log before changing anything.',
            },
        },
        {
            'type': 'tool.called',
            'payload': {
                'call_id': f'toolu_{uuid.uuid4().hex[:8]}',
                'tool': 'Bash',
                'mutating': True,
                'arguments': {'command': 'uv run pytest -q'},
                'result': '.F..\nFAILED tests/test_x.py::test_parse\n'
                '1 failed, 3 passed in 0.42s',
                'is_error': True,
                'duration_ms': 4210,
            },
        },
        {
            'type': 'turn',
            'payload': {
                'kind': 'text',
                'body': 'One test fails:\n\n'
                '- `test_parse` rejects the extra field\n'
                '- the others pass\n\n'
                'I will look for every place that parses this model.',
            },
        },
        {
            'type': 'turn',
            'actor_kind': 'subagent',
            'payload': {
                'kind': 'text',
                'body': 'Searching for the parse calls.',
                'parent_call_id': task_call,
            },
        },
        {
            'type': 'tool.called',
            'actor_kind': 'subagent',
            'payload': {
                'call_id': f'toolu_{uuid.uuid4().hex[:8]}',
                'tool': 'Grep',
                'mutating': False,
                'arguments': {'pattern': 'model_validate', 'path': 'src'},
                'result': 'src/feeds.py:88\nsrc/api.py:54',
                'is_error': False,
                'duration_ms': 310,
                'parent_call_id': task_call,
            },
        },
        {
            'type': 'tool.called',
            'payload': {
                'call_id': task_call,
                'tool': 'Task',
                'mutating': False,
                'arguments': {
                    'subagent_type': 'code-search',
                    'description': 'Find the parse calls',
                },
                'result': 'Two call sites: src/feeds.py:88, src/api.py:54',
                'is_error': False,
                'duration_ms': 9800,
            },
        },
        {
            'type': 'tool.called',
            'payload': {
                'call_id': f'toolu_{uuid.uuid4().hex[:8]}',
                'tool': 'Bash',
                'mutating': True,
                'arguments': {'command': 'git push --force'},
                'result': 'Denied by policy.',
                'is_error': True,
                'duration_ms': 3,
                'policy': {
                    'decision': 'deny',
                    'reason': 'Force pushes are blocked on PR branches',
                },
            },
        },
        {
            'type': 'tool.called',
            'payload': {
                'call_id': big_call,
                'tool': 'Read',
                'mutating': False,
                'arguments': {'file_path': 'src/feeds.py'},
                'result': '\n'.join(lines[:100]) + '\n',
                'is_error': False,
                'duration_ms': 40,
                'part': 1,
                'parts': 2,
            },
        },
        {
            'type': 'tool.called',
            'payload': {
                'call_id': big_call,
                'result': '\n'.join(lines[100:]),
                'part': 2,
                'parts': 2,
            },
        },
        {
            'type': 'turn',
            'payload': {
                'kind': 'warning',
                'body': 'Coverage dropped from 91.2% to 90.8%.',
            },
        },
    ]


async def run_task(
    harness: HarnessClient,
    *,
    model_id: str,
    ask: bool = False,
    wait: bool = False,
    interval: float = 2.0,
) -> Body:
    """Work a task the way a harness does; return the last task state.

    With ``ask``, open a feedback request. With ``wait`` too, wait for
    the answer in a new session, then finish the task.
    """
    run = uuid.uuid4().hex[:8]
    session_id = (await harness.open_session(f'reference-{run}'))['session'][
        'id'
    ]
    await harness.append(
        session_id,
        [
            {'type': 'phase.changed', 'payload': {'phase': 'investigate'}},
            {'type': 'turn', 'payload': {'body': 'I read the task.'}},
            {
                'type': 'tool.called',
                'payload': {
                    'tool': 'reference.echo',
                    'mutating': False,
                    'arguments': {'text': 'hello'},
                    'result': 'hello',
                    'result_summary': 'hello',
                    'duration_ms': 12,
                },
            },
        ],
    )
    usage = await harness.report_usage(
        f'{run}-1',
        model_id,
        tokens_in=1200,
        tokens_out=300,
        cache_read_tokens=5000,
        cache_write_tokens=800,
        session_id=session_id,
    )
    if usage['task']['status'] == 'closed':
        return usage['task']
    state = await harness.heartbeat(session_id)
    if state['control'] == 'cancel':
        return await harness.set_outcome('cancelled_by_human', 'cancel_seen')
    if ask:
        request = await harness.open_request(
            kind='feedback',
            title='Apply the fix?',
            why='The reference client asks one question.',
            options=['yes', 'no'],
            session_id=session_id,
            request_key=f'{run}-ask',
        )
        await harness.close_session(session_id, 'waiting_for_reply')
        if not wait:
            return request['task']
        answer = await harness.wait_for_answer(
            request['request']['id'], request['task']['last_seq'], interval
        )
        if answer['type'] == 'outcome.set':
            return {
                'status': 'closed',
                'outcome': answer['payload']['outcome'],
                'outcome_reason': answer['payload']['reason'],
            }
        opened = await harness.open_session(f'reference-{run}-2')
        session_id = opened['session']['id']
        # A person can pause the task while the request is open.
        state = opened['task']
        while state['control'] == 'pause':
            await asyncio.sleep(interval)
            state = await harness.heartbeat(session_id)
        if state['control'] == 'cancel':
            return await harness.set_outcome(
                'cancelled_by_human', 'cancel_seen'
            )
        await harness.append(
            session_id,
            [
                {
                    'type': 'turn',
                    'payload': {
                        'body': f'The answer is {answer["payload"]["answer"]}.'
                    },
                }
            ],
        )
    await harness.append(
        session_id,
        [
            {
                'type': 'todos.updated',
                'payload': {'todos': [{'title': 'Report', 'done': True}]},
            },
            {
                'type': 'check.reported',
                'payload': {'name': 'reference', 'verdict': 'pass'},
            },
            {'type': 'phase.changed', 'payload': {'phase': 'done'}},
            {'type': 'turn', 'payload': {'body': 'Done.'}},
        ],
    )
    return await harness.set_outcome('done_acted')


async def run_rich_task(
    harness: HarnessClient, *, model_id: str, ask: bool = False
) -> Body:
    """Write :func:`rich_events` in a session of its own, then work the
    task with :func:`run_task`. With ``ask``, leave it blocked on a
    feedback request."""
    run = uuid.uuid4().hex[:8]
    session = await harness.open_session(f'reference-rich-{run}')
    await harness.append(session['session']['id'], rich_events())
    return await run_task(harness, model_id=model_id, ask=ask)


async def _main(args: argparse.Namespace) -> Body:
    async with httpx.AsyncClient(base_url=args.api_url) as client:
        response = await client.post(
            '/auth/token',
            data={
                'grant_type': 'client_credentials',
                'client_id': args.client_id,
                'client_secret': args.client_secret,
            },
        )
        response.raise_for_status()
        client.headers['Authorization'] = (
            f'Bearer {response.json()["access_token"]}'
        )
        harness = HarnessClient(client, args.org, args.task)
        if args.rich:
            return await run_rich_task(
                harness, model_id=args.model, ask=args.ask
            )
        return await run_task(
            harness, model_id=args.model, ask=args.ask, wait=args.wait
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Work an agent task as its harness.'
    )
    parser.add_argument('--api-url', required=True, help='Ends in /api')
    parser.add_argument('--org', required=True, help='Organization slug')
    parser.add_argument('--task', required=True, help='Short id, e.g. T-1')
    parser.add_argument('--model', required=True, help='AI model slug')
    parser.add_argument(
        '--client-id', default=os.environ.get('IMBI_CLIENT_ID')
    )
    parser.add_argument(
        '--client-secret', default=os.environ.get('IMBI_CLIENT_SECRET')
    )
    parser.add_argument(
        '--ask',
        action='store_true',
        help='Open a feedback request and leave the task blocked',
    )
    parser.add_argument(
        '--wait',
        action='store_true',
        help='With --ask, wait for the answer, then finish the task',
    )
    parser.add_argument(
        '--rich',
        action='store_true',
        help='Also write thinking, failed and denied calls, a subagent, '
        'and a split result, to exercise the Conversation tab',
    )
    args = parser.parse_args()
    if not args.client_id or not args.client_secret:
        parser.error('give --client-id and --client-secret')
    print(json.dumps(asyncio.run(_main(args)), indent=2))  # noqa: T201


if __name__ == '__main__':
    main()
