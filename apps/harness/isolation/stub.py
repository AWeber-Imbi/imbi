"""A stub for the P5a isolation suite. Test use only.

It serves three things on one port:

- The imbi-api routes that the runner and the executor call: the pool
  token, register, heartbeat, claim, finish, secret resolutions,
  materializations, and release. They follow the shapes and the refusal
  rules of ``imbi.api.endpoints.harness`` and
  ``imbi.api.secret_broker.broker`` (context, expiry, single use, nonce,
  runner), with one ``fake`` dynamic secret. A lease sweep marks a
  runner offline, revokes its resolutions, and requeues its chain after
  a grace period.
- An Anthropic Messages API that runs a script: each task has a list of
  tool calls, and the model makes them in order, then says "done". It
  keeps every request, so the suite sees what the model saw.
- ``/github/write``: 200 for an issued token that is not revoked, else
  401.

``/test/...`` routes let the suite queue tasks, make resolutions, cut the
runner off ("partition"), and read the state.

The real imbi-api is not used: it needs Postgres with AGE, ClickHouse,
Iggy, and Valkey, and its ``fake`` provider keeps values only in process
memory. ``apps/api/tests/endpoints/test_harness_secrets.py`` covers the
real broker rules.
"""

import datetime
import http.server
import json
import os
import re
import secrets
import signal
import sys
import threading
import time
import typing
import urllib.parse
import uuid

LEASE_SECONDS = int(os.environ.get('LEASE_SECONDS', '15'))
GRACE_SECONDS = int(os.environ.get('GRACE_SECONDS', '10'))
POOL_CLIENT_ID = os.environ['POOL_CLIENT_ID']
POOL_CLIENT_SECRET = os.environ['POOL_CLIENT_SECRET']
MODEL_KEY = os.environ['MODEL_KEY']
REFERENCE = 'secret://production/github/token'
PURPOSES = {'github_write'}
AGENT_ID = 'agent-1'
POOL_ACCESS_TOKEN = 'pool-access-' + secrets.token_hex(8)
_MARKER = re.compile(r'\[\[task:(T-\d+)\]\]')

type Row = dict[str, typing.Any]

LOCK = threading.RLock()
RUNNERS: dict[str, Row] = {}
CHAINS: dict[str, Row] = {}
TASKS: dict[str, Row] = {}
QUEUE: list[str] = []
RESOLUTIONS: dict[str, Row] = {}
NONCES: set[str] = set()
TOKENS: dict[str, str] = {}
MODEL_REQUESTS: list[Row] = []
PARTITION = threading.Event()


class Fail(Exception):
    def __init__(self, status: int, error: str) -> None:
        super().__init__(error)
        self.status = status
        self.error = error


def _iso(at: float) -> str:
    return datetime.datetime.fromtimestamp(at, datetime.UTC).isoformat()


def _new_runner(*, synthetic: bool = False) -> Row:
    runner = {
        'id': str(uuid.uuid4()),
        'synthetic': synthetic,
        'runner_token': 'ihr_' + secrets.token_urlsafe(32),
        'executor_token': 'ihe_' + secrets.token_urlsafe(32),
        'state': 'idle',
        'chain_id': None,
        'registered_at': time.time(),
        'lease_expires_at': time.time() + LEASE_SECONDS,
        'offline_at': None,
    }
    RUNNERS[runner['id']] = runner
    return runner


def _new_resolution(runner: Row, task: Row, purpose: str, ttl: int) -> Row:
    resolution = {
        'id': str(uuid.uuid4()),
        'handle': secrets.token_urlsafe(32),
        'runner_id': runner['id'],
        'task_id': task['id'],
        'agent_id': task['agent_id'],
        'project_id': task['project_id'],
        'purpose': purpose,
        'reference': REFERENCE,
        'expires_at': time.time() + ttl,
        'state': 'active',
        'count': 0,
        'materials': [],
        'revoked': False,
        'ended_by': None,
    }
    RESOLUTIONS[resolution['id']] = resolution
    return resolution


def _bearer(headers: typing.Any) -> str:
    value = str(headers.get('Authorization') or '')
    return value.split(' ', 1)[1] if ' ' in value else ''


def _runner(runner_id: str, token: str) -> Row:
    runner = RUNNERS.get(runner_id)
    if (
        runner is None
        or runner['runner_token'] != token
        or runner['state'] == 'offline'
    ):
        raise Fail(401, 'invalid_runner_credential')
    return runner


def _executor(token: str) -> Row:
    for runner in RUNNERS.values():
        if runner['executor_token'] == token and runner['state'] != 'offline':
            return runner
    raise Fail(401, 'invalid_executor_credential')


def _end(resolution: Row, state: str, by: str) -> None:
    if resolution['state'] == 'active':
        resolution['state'] = state
        resolution['revoked'] = True
        resolution['ended_by'] = by
        resolution['ended_at'] = time.time()


def sweep() -> None:
    """The lease sweep and the requeue after the grace period."""
    while True:
        time.sleep(0.25)
        now = time.time()
        with LOCK:
            for runner in RUNNERS.values():
                if runner['state'] != 'offline' and (
                    runner['lease_expires_at'] < now
                ):
                    runner['state'] = 'offline'
                    runner['offline_at'] = now
                    for resolution in RESOLUTIONS.values():
                        if resolution['runner_id'] == runner['id']:
                            _end(resolution, 'expired', 'lease_sweep')
                    chain = CHAINS.get(runner['chain_id'] or '')
                    if chain and chain['state'] == 'running':
                        chain['state'] = 'fenced'
                        chain['fenced_at'] = now
            for chain in CHAINS.values():
                if (
                    chain['state'] == 'fenced'
                    and now >= chain['fenced_at'] + GRACE_SECONDS
                ):
                    chain['state'] = 'queued'
                    chain['attempt'] += 1
                    chain['runner_id'] = None
                    chain['agent_token'] = None
                    chain['requeued_at'].append(now)
                    QUEUE.append(chain['id'])


def _claim(runner: Row, wait: int) -> Row | None:
    deadline = time.time() + wait
    while True:
        with LOCK:
            if runner['state'] != 'idle':
                raise Fail(409, 'runner_busy')
            if QUEUE:
                chain = CHAINS[QUEUE.pop(0)]
                chain['state'] = 'running'
                chain['runner_id'] = runner['id']
                chain['agent_token'] = 'iat_' + secrets.token_urlsafe(32)
                chain['claimed_at'].append(time.time())
                runner['state'] = 'busy'
                runner['chain_id'] = chain['id']
                task = chain['task']
                return {
                    'chain_id': chain['id'],
                    'attempt': chain['attempt'],
                    'organization_slug': 'test',
                    'task': {
                        key: task[key]
                        for key in (
                            'id',
                            'short_id',
                            'agent_id',
                            'project_id',
                            'title',
                            'description',
                        )
                    },
                    'bundle': {'agent_id': AGENT_ID, 'agent_version': 1},
                    'agent_token': chain['agent_token'],
                    'agent_token_expires_at': _iso(time.time() + 3600),
                }
        if time.time() >= deadline:
            return None
        time.sleep(0.25)


def _materialize(token: str, body: Row) -> Row:
    runner = _executor(token)
    resolution = next(
        (
            row
            for row in RESOLUTIONS.values()
            if row['handle'] == body.get('handle')
        ),
        None,
    )
    if resolution is None:
        raise Fail(404, 'resolution_not_found')
    context = (
        body.get('task_id'),
        body.get('agent_id'),
        body.get('project_id'),
        body.get('purpose'),
    )
    if resolution['runner_id'] != runner['id'] or context != (
        resolution['task_id'],
        resolution['agent_id'],
        resolution['project_id'],
        resolution['purpose'],
    ):
        raise Fail(403, 'resolution_context_mismatch')
    if resolution['state'] == 'expired' or resolution['expires_at'] < (
        time.time()
    ):
        raise Fail(410, 'resolution_expired')
    if resolution['state'] != 'active' or resolution['count'] >= 1:
        raise Fail(409, 'resolution_already_used')
    nonce = str(body.get('nonce') or '')
    if len(nonce) < 16 or nonce in NONCES:
        raise Fail(409, 'resolution_already_used')
    NONCES.add(nonce)
    resolution['count'] += 1
    material = 'ghs_' + secrets.token_hex(18)
    resolution['materials'].append(material)
    TOKENS[material] = resolution['id']
    return {
        'resolution_id': resolution['id'],
        'encoding': 'utf8',
        'material': material,
        'delivery': resolution['delivery'],
        'resolution_expires_at': _iso(resolution['expires_at']),
        'credential_expires_at': _iso(resolution['expires_at']),
    }


def _sse(event: str, data: Row) -> bytes:
    return f'event: {event}\ndata: {json.dumps(data)}\n\n'.encode()


def _model_reply(body: Row) -> tuple[Row, list[Row]]:
    """Return the next content block of the script, and the SSE events."""
    messages = json.dumps(body.get('messages') or [])
    match = _MARKER.search(messages)
    script: list[Row] = []
    if match:
        task = TASKS.get(match.group(1))
        script = task['script'] if task else []
    step = messages.count('"tool_result"')
    if step < len(script):
        call = script[step]
        block: Row = {
            'type': 'tool_use',
            'id': f'toolu_{step}_{secrets.token_hex(6)}',
            'name': call['name'],
            'input': call['input'],
        }
        delta = {'type': 'input_json_delta', 'partial_json': ''}
        deltas = [{**delta, 'partial_json': json.dumps(call['input'])}]
        start = {**block, 'input': {}}
        stop_reason = 'tool_use'
    else:
        block = {'type': 'text', 'text': 'done'}
        deltas = [{'type': 'text_delta', 'text': 'done'}]
        start = {'type': 'text', 'text': ''}
        stop_reason = 'end_turn'
    message = {
        'id': 'msg_' + secrets.token_hex(8),
        'type': 'message',
        'role': 'assistant',
        'model': body.get('model', 'stub'),
        'content': [block],
        'stop_reason': stop_reason,
        'stop_sequence': None,
        'usage': {'input_tokens': 10, 'output_tokens': 5},
    }
    events = [
        {
            'type': 'message_start',
            'message': {
                **message,
                'content': [],
                'stop_reason': None,
                'usage': {'input_tokens': 10, 'output_tokens': 1},
            },
        },
        {'type': 'content_block_start', 'index': 0, 'content_block': start},
        *(
            {'type': 'content_block_delta', 'index': 0, 'delta': d}
            for d in deltas
        ),
        {'type': 'content_block_stop', 'index': 0},
        {
            'type': 'message_delta',
            'delta': {'stop_reason': stop_reason, 'stop_sequence': None},
            'usage': {'output_tokens': 5},
        },
        {'type': 'message_stop'},
    ]
    return message, events


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: typing.Any) -> None:  # noqa: A002
        pass

    def _json(self, status: int, body: typing.Any) -> None:
        data = json.dumps(body, default=sorted).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> Row:
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length else b''
        if self.headers.get('Content-Type', '').startswith(
            'application/x-www-form-urlencoded'
        ):
            return dict(urllib.parse.parse_qsl(raw.decode()))
        return json.loads(raw) if raw else {}

    def do_HEAD(self) -> None:
        self.send_response(200)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self) -> None:
        url = urllib.parse.urlsplit(self.path)
        query = dict(urllib.parse.parse_qsl(url.query))
        try:
            with LOCK:
                if url.path == '/healthz':
                    return self._json(200, {'ok': True})
                if url.path == '/test/state':
                    return self._json(200, self._state())
                if url.path == '/test/model-requests':
                    marker = f'[[task:{query["task"]}]]'
                    return self._json(
                        200,
                        [
                            row
                            for row in MODEL_REQUESTS
                            if marker in json.dumps(row)
                        ],
                    )
                if url.path == '/github/write':
                    return self._github()
            return self._json(404, {'detail': 'not found'})
        except Fail as err:
            return self._json(err.status, {'detail': {'error': err.error}})

    def _state(self) -> Row:
        return {
            'runners': list(RUNNERS.values()),
            'chains': [
                {key: value for key, value in chain.items() if key != 'task'}
                for chain in CHAINS.values()
            ],
            'tasks': list(TASKS.values()),
            'resolutions': list(RESOLUTIONS.values()),
            'partition': PARTITION.is_set(),
            'now': time.time(),
        }

    def _github(self) -> None:
        token = _bearer(self.headers)
        resolution = RESOLUTIONS.get(TOKENS.get(token, ''))
        if resolution is None or resolution['revoked']:
            raise Fail(401, 'bad_credentials')
        return self._json(200, {'ok': True})

    def do_POST(self) -> None:
        url = urllib.parse.urlsplit(self.path)
        if PARTITION.is_set() and url.path.startswith(('/auth', '/harness')):
            # A black hole: no reply until the client gives up.
            time.sleep(120)
            self.close_connection = True
            return
        try:
            body = self._body()
            if url.path == '/v1/messages':
                return self._messages(body)
            with LOCK:
                status, reply = self._route(url, body)
            if status == 204:
                self.send_response(204)
                self.end_headers()
                return None
            return self._json(status, reply)
        except Fail as err:
            return self._json(err.status, {'detail': {'error': err.error}})

    def _route(
        self, url: urllib.parse.SplitResult, body: Row
    ) -> tuple[int, typing.Any]:
        path = url.path
        token = _bearer(self.headers)
        parts = path.strip('/').split('/')
        if path == '/auth/token':
            if (body.get('client_id'), body.get('client_secret')) != (
                POOL_CLIENT_ID,
                POOL_CLIENT_SECRET,
            ):
                raise Fail(401, 'invalid_client')
            return 200, {
                'access_token': POOL_ACCESS_TOKEN,
                'token_type': 'bearer',
            }
        if path == '/harness/runners':
            if token != POOL_ACCESS_TOKEN:
                raise Fail(401, 'not_authenticated')
            runner = _new_runner()
            return 201, {
                'runner_id': runner['id'],
                'runner_token': runner['runner_token'],
                'executor_token': runner['executor_token'],
                'labels': [],
                'lease_seconds': LEASE_SECONDS,
                'lease_expires_at': _iso(runner['lease_expires_at']),
            }
        if parts[:2] == ['harness', 'runners'] and len(parts) >= 4:
            runner = _runner(parts[2], token)
            action = '/'.join(parts[3:])
            if action == 'heartbeat':
                runner['lease_expires_at'] = time.time() + LEASE_SECONDS
                return 200, {
                    'state': runner['state'],
                    'chain_id': runner['chain_id'],
                    'lease_seconds': LEASE_SECONDS,
                    'lease_expires_at': _iso(runner['lease_expires_at']),
                }
            if action == 'claim':
                wait = int(
                    dict(urllib.parse.parse_qsl(url.query)).get('wait', 0)
                )
                LOCK.release()
                try:
                    claim = _claim(runner, min(wait, 30))
                finally:
                    LOCK.acquire()
                return (204, None) if claim is None else (200, claim)
            if action == 'finish':
                runner['state'] = 'offline'
                runner['offline_at'] = time.time()
                chain = CHAINS.get(runner['chain_id'] or '')
                if chain and chain['state'] == 'running':
                    chain['state'] = 'done'
                return 200, {'chain_state': chain and chain['state']}
        if path == '/harness/secret-resolutions':
            chain = next(
                (
                    c
                    for c in CHAINS.values()
                    if c['agent_token'] == token and c['state'] == 'running'
                ),
                None,
            )
            if chain is None:
                raise Fail(401, 'stale_attempt')
            task = chain['task']
            if body.get('short_id') != task['short_id']:
                raise Fail(403, 'task_forbidden')
            if body.get('reference') != REFERENCE:
                raise Fail(404, 'secret_binding_not_found')
            if body.get('purpose') not in PURPOSES:
                raise Fail(403, 'secret_access_denied')
            ttl = int(body.get('ttl_seconds', 300))
            if not 1 <= ttl <= 900:
                raise Fail(422, 'requested_ttl_too_large')
            resolution = _new_resolution(
                RUNNERS[chain['runner_id']], task, body['purpose'], ttl
            )
            resolution['delivery'] = body.get('delivery')
            return 201, {
                'resolution_id': resolution['id'],
                'handle': resolution['handle'],
                'state': 'active',
                'expires_at': _iso(resolution['expires_at']),
                'delivery': resolution['delivery'],
            }
        if path == '/harness/executor/secret-materializations':
            return 200, _materialize(token, body)
        if (
            parts[:3] == ['harness', 'executor', 'secret-resolutions']
            and parts[-1] == 'release'
        ):
            runner = _executor(token)
            resolution = RESOLUTIONS.get(parts[3])
            if resolution is None or resolution['runner_id'] != runner['id']:
                raise Fail(404, 'resolution_not_found')
            _end(resolution, 'released', 'executor')
            return 200, {
                'resolution_id': resolution['id'],
                'state': resolution['state'],
                'revocation_state': 'succeeded',
            }
        return self._test_route(path, body)

    def _test_route(self, path: str, body: Row) -> tuple[int, typing.Any]:
        if path == '/test/tasks':
            short_id = f'T-{len(TASKS) + 1}'
            chain_id = str(uuid.uuid4())
            task = {
                'id': str(uuid.uuid4()),
                'short_id': short_id,
                'agent_id': AGENT_ID,
                'project_id': None,
                'title': body.get('title', short_id),
                'description': f'{body.get("instruction", "Work.")}\n\n'
                f'[[task:{short_id}]]',
                'chain_id': chain_id,
                'script': body.get('script', []),
            }
            TASKS[short_id] = task
            CHAINS[chain_id] = {
                'id': chain_id,
                'task': task,
                'short_id': short_id,
                'state': 'queued',
                'runner_id': None,
                'attempt': 1,
                'agent_token': None,
                'claimed_at': [],
                'requeued_at': [],
                'fenced_at': None,
            }
            QUEUE.append(chain_id)
            return 201, task
        if path == '/test/resolutions':
            if body.get('runner') == 'other':
                runner = _new_runner(synthetic=True)
            else:
                runner = max(
                    (
                        r
                        for r in RUNNERS.values()
                        if r['state'] != 'offline' and not r['synthetic']
                    ),
                    key=lambda r: r['registered_at'],
                )
            task = {
                'id': body.get('task_id') or str(uuid.uuid4()),
                'agent_id': AGENT_ID,
                'project_id': None,
            }
            resolution = _new_resolution(
                runner,
                task,
                body.get('purpose', 'github_write'),
                int(body.get('ttl_seconds', 300)),
            )
            resolution['delivery'] = {
                'mode': 'environment',
                'target': body.get('target', 'GH_TOKEN'),
            }
            return 201, resolution
        if path == '/test/partition':
            if body.get('on'):
                PARTITION.set()
            else:
                PARTITION.clear()
            return 200, {'partition': PARTITION.is_set()}
        raise Fail(404, 'not_found')

    def _messages(self, body: Row) -> None:
        if self.headers.get('x-api-key') != MODEL_KEY:
            with LOCK:
                MODEL_REQUESTS.append({'bad_key': True})
            self._json(
                401,
                {
                    'type': 'error',
                    'error': {
                        'type': 'authentication_error',
                        'message': 'invalid x-api-key',
                    },
                },
            )
            return
        with LOCK:
            MODEL_REQUESTS.append(body)
            message, events = _model_reply(body)
        if not body.get('stream'):
            self._json(200, message)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        for event in events:
            self.wfile.write(_sse(event['type'], event))
        self.wfile.flush()


def main() -> None:
    # PID 1 ignores SIGTERM without a handler.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    threading.Thread(target=sweep, daemon=True).start()
    server = http.server.ThreadingHTTPServer(
        ('0.0.0.0', int(os.environ.get('PORT', '8080'))),  # noqa: S104
        Handler,
    )
    server.daemon_threads = True
    server.serve_forever()


if __name__ == '__main__':
    main()
