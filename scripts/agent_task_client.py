"""Reference harness client for agent tasks (ADR 0020).

This works one task from start to end through the harness endpoints,
as the service account of the task's agent. It opens a session, writes
phases, turns, and a tool call, reports usage, and sets the outcome
``done_acted``. With ``--ask`` it opens a feedback request instead and
leaves the task ``blocked``. The tests use :class:`HarnessClient` and
:func:`run_task`; the dev environment uses the command line.

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
        return await self._post('requests', request)

    async def set_outcome(
        self, outcome: str, reason: str | None = None
    ) -> Body:
        return await self._post(
            'outcome', {'outcome': outcome, 'reason': reason}
        )


async def run_task(
    harness: HarnessClient, *, model_id: str, ask: bool = False
) -> Body:
    """Work a task the way a harness does; return the last task state."""
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
        )
        await harness.close_session(session_id, 'waiting_for_reply')
        return request['task']
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
        return await run_task(
            HarnessClient(client, args.org, args.task),
            model_id=args.model,
            ask=args.ask,
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
    args = parser.parse_args()
    if not args.client_id or not args.client_secret:
        parser.error('give --client-id and --client-secret')
    print(json.dumps(asyncio.run(_main(args)), indent=2))  # noqa: T201


if __name__ == '__main__':
    main()
