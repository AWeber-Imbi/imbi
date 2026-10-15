"""The P5a adversarial suite, run in the ``runner`` container.

``kubectl exec harness -c runner -- python3 -m unittest discover
-s /opt/isolation -p test_pod.py -v``

The suite runs as uid 0 with only ``CAP_SETUID`` and ``CAP_SETGID``,
the same as the runner before it drops. It reads other users' files
only through ``setpriv`` as that user.

- ``AgentTests``: the model's ``Bash`` tool, started by the real runner
  through the SDK and the ``setpriv`` wrapper, runs ``probe.py agent``.
- ``ChildTests``: a ``run_with_secret`` command runs ``probe.py child``
  in the executor container.
- ``TranscriptTests``: a ``run_with_secret`` command prints its secret;
  no handle or secret value reaches the model, the runner transcript,
  or the CLI session files.
- ``HandleTests``: the suite acts as the runner on the executor socket
  and sends handles that imbi-api must refuse.
- ``ExecutorTests``: the suite acts as the runner on the socket: the
  workspace check after the switch to ``agent``, the output bound, and
  the timeout of a command whose child holds the pipe open.
- ``EndOfChainTests``: after a chain, no ``agent`` process is left in
  either container, the workspace is gone, and the runner process
  ended after one claim.
- ``TaskFlowTests`` (P5): the workspace build (a private clone with a
  token on a descriptor, a pinned plugin), the model key through a
  ``model_inference`` resolution, the task events with redaction and
  1 MiB parts, the usage reports, and the outcome.
- ``BudgetTests`` and ``CancelTests`` (P5): a task over budget ends as
  ``exceeded_ceiling`` with no more model calls; a cancel stops a
  running command.
"""

import base64
import errno
import json
import os
import pathlib
import subprocess
import sys
import time
import typing
import unittest
import urllib.parse
import urllib.request

import probe

FAKE_API = os.environ.get('FAKE_API_URL', 'http://harness-fake-api:8080')
REFERENCE = 'secret://production/github/token'
NO_CAPABILITIES = '0000000000000000'
DENIED = f'denied:{errno.errorcode[errno.EACCES]}'
_SOCKET_CLIENT = """
import json, socket, sys
try:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect('/run/executor/executor.sock')
except OSError as err:
    print(json.dumps({'connect_error': err.errno}))
    sys.exit()
try:
    sock.sendall(sys.stdin.buffer.read())
    line = sock.makefile('rb').readline()
except OSError:
    line = b''
print(line.decode() or json.dumps({'closed': True}))
"""

type Row = dict[str, typing.Any]


def fake_api(method: str, path: str, body: Row | None = None) -> typing.Any:
    request = urllib.request.Request(  # noqa: S310 - the fake API URL
        FAKE_API + path,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read() or b'null')


def as_user(
    user: str, argv: list[str], stdin: str = '', groups: str = ''
) -> subprocess.CompletedProcess[str]:
    """Run ``argv`` as ``user``, with no capabilities."""
    group_flag = f'--groups={groups}' if groups else '--clear-groups'
    return subprocess.run(  # noqa: S603
        [  # noqa: S607
            'setpriv',
            f'--reuid={user}',
            f'--regid={user}',
            group_flag,
            '--inh-caps=-all',
            *argv,
        ],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def socket_call(message: Row, user: str = 'runner') -> Row:
    groups = 'harness-ipc' if user in {'runner', 'executor'} else ''
    result = as_user(
        user,
        [sys.executable, '-c', _SOCKET_CLIENT],
        json.dumps(message) + '\n',
        groups,
    )
    return json.loads(result.stdout)


def wait_for_runner(timeout: float = 120) -> None:
    """Wait until the fake API answers and a runner polls for a claim.

    The runner polls only after it gave the executor its credential.
    One runner process runs one chain, so between chains no runner is
    live for a moment.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            runners = fake_api('GET', '/test/state')['runners']
        except OSError:
            runners = []
        if any(
            r['polling'] and r['state'] == 'idle' and not r['synthetic']
            for r in runners
        ):
            return
        time.sleep(0.25)
    raise AssertionError('no runner is ready')


def setUpModule() -> None:
    wait_for_runner()


def run_task(script: list[Row], timeout: float = 180) -> Row:
    """Queue a task, wait until the runner finishes its chain."""
    task = fake_api('POST', '/test/tasks', {'script': script})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        chains = fake_api('GET', '/test/state')['chains']
        chain = next(c for c in chains if c['id'] == task['chain_id'])
        if chain['state'] == 'done':
            return task
        time.sleep(1)
    raise AssertionError(f'task {task["short_id"]} did not end')


def tool_results(task: Row) -> list[str]:
    """The text of each tool result that the model got, in order."""
    requests = fake_api('GET', f'/test/model-requests?task={task["short_id"]}')
    texts: list[str] = []
    for message in requests[-1]['messages']:
        content = message.get('content')
        if not isinstance(content, list):
            continue
        for block in content:
            if block.get('type') != 'tool_result':
                continue
            inner = block.get('content')
            if isinstance(inner, list):
                inner = ''.join(part.get('text', '') for part in inner)
            texts.append(str(inner))
    return texts


def probe_result(text: str) -> Row:
    return json.loads(text[text.index('{') :])


def resolutions_of(task: Row, purpose: str = 'github_write') -> list[Row]:
    """The resolutions of a task for one purpose. Each task also has a
    ``model_inference`` resolution for its model key."""
    return [
        row
        for row in fake_api('GET', '/test/state')['resolutions']
        if row['task_id'] == task['id'] and row['purpose'] == purpose
    ]


def task_of(task: Row) -> Row:
    """The task with its events and usage reports."""
    return fake_api('GET', f'/test/task?short_id={task["short_id"]}')


def model_key() -> str:
    return fake_api('GET', '/test/model-key')['key']


def run_with_secret(command: str) -> Row:
    return {
        'name': 'mcp__imbi__run_with_secret',
        'input': {
            'command': command,
            'secrets': [
                {
                    'reference': REFERENCE,
                    'purpose': 'github_write',
                    'env': 'GH_TOKEN',
                }
            ],
        },
    }


class AgentTests(unittest.TestCase):
    """The CLI's tools, as ``agent`` in the ``runner`` container."""

    result: typing.ClassVar[Row]

    @classmethod
    def setUpClass(cls) -> None:
        task = run_task(
            [
                {
                    'name': 'Bash',
                    'input': {
                        'command': 'python3 /opt/isolation/probe.py agent',
                        'description': 'Run the isolation probe',
                    },
                }
            ]
        )
        cls.result = probe_result(tool_results(task)[0])

    def test_runs_as_agent_without_capabilities(self) -> None:
        identity = self.result['identity']
        agent = [10003, 10003, 10003]
        self.assertEqual(identity['uid'], agent)
        self.assertEqual(identity['gid'], agent)
        self.assertEqual(identity['groups'], [])
        for field in ('CapPrm', 'CapEff', 'CapInh', 'CapAmb'):
            self.assertEqual(identity[field], NO_CAPABILITIES, field)
        self.assertEqual(identity['NoNewPrivs'], '1')

    def test_cannot_read_runner_credential(self) -> None:
        self.assertEqual(self.result['runner_credential'], DENIED)
        self.assertEqual(self.result['credential_dir'], DENIED)

    def test_cannot_read_runner_memory_or_environment(self) -> None:
        self.assertIsNotNone(self.result['runner_pid'])
        self.assertEqual(self.result['runner_environ'], DENIED)
        self.assertEqual(self.result['runner_mem'], DENIED)

    def test_cannot_read_pool_credential_or_model_key(self) -> None:
        self.assertEqual(self.result['pool_credential'], DENIED)
        # The model key is only in the runner's memory (from a
        # model_inference resolution), never in a file; the memory test
        # above covers it.
        self.assertEqual(
            self.result['model_key'],
            f'denied:{errno.errorcode[errno.ENOENT]}',
        )
        self.assertTrue(self.result['cli_key_is_placeholder'])

    def test_cannot_read_service_account_token(self) -> None:
        self.assertEqual(self.result['service_account_token'], DENIED)

    def test_cannot_connect_to_executor(self) -> None:
        self.assertEqual(self.result['executor_socket'], DENIED)

    def test_cannot_see_executor_processes(self) -> None:
        self.assertEqual(self.result['executor_processes'], [])

    def test_cannot_regain_privilege(self) -> None:
        self.assertEqual(
            self.result['setuid_0'], f'denied:{errno.errorcode[errno.EPERM]}'
        )
        self.assertEqual(self.result['setuid_files'], [])


class ChildTests(unittest.TestCase):
    """A ``run_with_secret`` command, as ``agent`` in the executor."""

    result: typing.ClassVar[Row]
    task: typing.ClassVar[Row]

    @classmethod
    def setUpClass(cls) -> None:
        cls.task = run_task(
            [run_with_secret('python3 /opt/isolation/probe.py child')]
        )
        text = tool_results(cls.task)[0]
        assert text.startswith('exit code 0'), text
        cls.result = probe_result(text)

    def test_runs_as_agent_without_capabilities(self) -> None:
        identity = self.result['identity']
        self.assertEqual(identity['uid'], [10003, 10003, 10003])
        self.assertEqual(identity['groups'], [])
        self.assertEqual(identity['CapEff'], NO_CAPABILITIES)
        self.assertEqual(identity['CapPrm'], NO_CAPABILITIES)
        self.assertEqual(identity['NoNewPrivs'], '1')

    def test_cannot_read_executor_credential(self) -> None:
        self.assertEqual(self.result['executor_credential'], DENIED)
        self.assertEqual(self.result['credential_dir'], DENIED)

    def test_cannot_read_executor_memory_or_environment(self) -> None:
        self.assertIsNotNone(self.result['executor_pid'])
        self.assertEqual(self.result['executor_environ'], DENIED)
        self.assertEqual(self.result['executor_mem'], DENIED)

    def test_cannot_connect_to_executor(self) -> None:
        self.assertEqual(self.result['executor_socket'], DENIED)

    def test_clean_environment_with_the_secret(self) -> None:
        names = set(self.result['environment'])
        self.assertIn('GH_TOKEN', names)
        # PWD, SHLVL and _ come from /bin/sh, LC_CTYPE from the C locale
        # coercion of the probe's Python.
        self.assertLessEqual(
            names,
            {'GH_TOKEN', 'HOME', 'LC_CTYPE', 'PATH', 'PWD', 'SHLVL', '_'},
        )
        self.assertGreater(self.result['secret_length'], 0)

    def test_executor_released_the_resolution(self) -> None:
        (resolution,) = resolutions_of(self.task)
        self.assertEqual(resolution['state'], 'released')
        self.assertEqual(resolution['ended_by'], 'executor')
        self.assertEqual(resolution['count'], 1)


class TranscriptTests(unittest.TestCase):
    """No handle or secret value reaches the model or the transcripts."""

    task: typing.ClassVar[Row]
    command = (
        'echo "length=${#GH_TOKEN}"; echo "$GH_TOKEN"; '
        'printf %s "$GH_TOKEN" | base64; echo "$GH_TOKEN" | base64; '
        'printf %s "$GH_TOKEN" | od -An -tx1 | tr -d " \\n"; echo; '
        'python3 -c "import os, urllib.parse; '
        "print(urllib.parse.quote(os.environ['GH_TOKEN'], safe=''))\""
    )

    @classmethod
    def setUpClass(cls) -> None:
        # The runner removes the workspace at the end of the chain, so
        # the second step copies the CLI session files out of it.
        cls.task = run_task(
            [
                run_with_secret(cls.command),
                {
                    'name': 'Bash',
                    'input': {
                        # The CLI writes its session file a moment later.
                        'command': 'for i in $(seq 60); do grep -rqs '
                        'REDACTED "$CLAUDE_CONFIG_DIR/projects" && break; '
                        'sleep 0.5; done; '
                        'cp -r "$CLAUDE_CONFIG_DIR/projects" '
                        f'/work/session-{cls.task_marker()}',
                        'description': 'Copy the session files',
                    },
                },
            ]
        )

    @classmethod
    def task_marker(cls) -> str:
        return 'transcript'

    def forbidden(self) -> list[str]:
        (resolution,) = resolutions_of(self.task)
        (material,) = resolution['materials']
        raw = material.encode()
        return [
            resolution['handle'],
            material,
            base64.b64encode(raw).decode()[:-4],
            raw.hex(),
            urllib.parse.quote(material, safe=''),
            model_key(),
        ]

    def check(self, haystack: str, where: str) -> None:
        self.assertTrue(haystack, f'{where} is empty')
        for value in self.forbidden():
            self.assertNotIn(value, haystack, where)

    def test_model_got_filtered_output(self) -> None:
        text = tool_results(self.task)[0]
        self.assertIn('length=40', text)
        self.assertGreaterEqual(text.count('[REDACTED]'), 5, text)

    def test_model_requests(self) -> None:
        requests = fake_api(
            'GET', f'/test/model-requests?task={self.task["short_id"]}'
        )
        self.check(json.dumps(requests), 'model requests')

    def test_task_events(self) -> None:
        self.check(json.dumps(task_of(self.task)['events']), 'task events')

    def test_runner_transcript(self) -> None:
        path = f'/run/creds/runner/transcripts/{self.task["id"]}.jsonl'
        result = as_user('runner', ['cat', path])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('tool_use_id', result.stdout)
        self.check(result.stdout, 'runner transcript')

    def test_session_files(self) -> None:
        result = as_user(
            'agent',
            [
                'find',
                f'/work/session-{self.task_marker()}',
                '-name',
                '*.jsonl',
                '-exec',
                'cat',
                '{}',
                '+',
            ],
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('[REDACTED]', result.stdout)
        self.check(result.stdout, 'session files')


class HandleTests(unittest.TestCase):
    """The suite is the runner on the socket; imbi-api refuses."""

    workspace = pathlib.Path('/work/handle-tests')

    def setUp(self) -> None:
        # The handles are for the current runner, whose credential the
        # executor holds.
        wait_for_runner()

    @classmethod
    def setUpClass(cls) -> None:
        as_user('agent', ['mkdir', '-p', str(cls.workspace)])

    def send(
        self, resolution: Row, marker: str, task_id: str | None = None
    ) -> Row:
        return socket_call(
            {
                'op': 'run',
                'command': f'touch {self.workspace}/{marker}',
                'cwd': str(self.workspace),
                'context': {
                    'task_id': task_id or resolution['task_id'],
                    'agent_id': resolution['agent_id'],
                    'project_id': resolution['project_id'],
                },
                'secrets': [
                    {
                        'handle': resolution['handle'],
                        'resolution_id': resolution['id'],
                        'purpose': resolution['purpose'],
                        'delivery': resolution['delivery'],
                    }
                ],
            }
        )

    def assert_refused(self, reply: Row, error: str, marker: str) -> None:
        self.assertEqual(reply, {'error': error})
        self.assertFalse((self.workspace / marker).exists())

    def test_valid_handle_then_replay(self) -> None:
        resolution = fake_api('POST', '/test/resolutions', {})
        self.assertEqual(self.send(resolution, 'first')['exit_code'], 0)
        self.assertTrue((self.workspace / 'first').exists())
        self.assert_refused(
            self.send(resolution, 'replay'),
            'resolution_already_used',
            'replay',
        )

    def test_expired_handle(self) -> None:
        resolution = fake_api('POST', '/test/resolutions', {'ttl_seconds': 1})
        time.sleep(2.5)
        self.assert_refused(
            self.send(resolution, 'expired'), 'resolution_expired', 'expired'
        )

    def test_handle_for_another_task(self) -> None:
        resolution = fake_api('POST', '/test/resolutions', {})
        reply = self.send(
            resolution, 'other-task', task_id=os.urandom(16).hex()
        )
        self.assert_refused(reply, 'resolution_context_mismatch', 'other-task')

    def test_handle_of_another_runner(self) -> None:
        resolution = fake_api('POST', '/test/resolutions', {'runner': 'other'})
        self.assert_refused(
            self.send(resolution, 'other-runner'),
            'resolution_context_mismatch',
            'other-runner',
        )

    def test_setup_purpose_is_never_run(self) -> None:
        resolution = fake_api(
            'POST', '/test/resolutions', {'purpose': 'model_inference'}
        )
        reply = self.send(resolution, 'setup-purpose')
        self.assert_refused(reply, 'purpose_not_allowed', 'setup-purpose')
        (row,) = [
            r
            for r in fake_api('GET', '/test/state')['resolutions']
            if r['id'] == resolution['id']
        ]
        self.assertEqual(row['count'], 0)
        self.assertEqual(row['state'], 'released')

    def test_peer_that_is_not_the_runner(self) -> None:
        # In the harness-ipc group, so only the SO_PEERCRED check stops it.
        # An unknown op: if the check failed, the reply is an error.
        reply = socket_call({'op': 'peer-test'}, 'executor')
        self.assertEqual(reply, {'closed': True})
        reply = socket_call({'op': 'peer-test'}, 'agent')
        self.assertEqual(reply, {'connect_error': errno.EACCES})


if __name__ == '__main__':
    unittest.main()


def agent_processes() -> list[list[str]]:
    """The ``agent`` processes of this (the runner) container."""
    found = []
    for pid, argv in probe.processes().items():
        try:
            status = pathlib.Path(f'/proc/{pid}/status').read_text()
        except OSError:
            continue
        if any(
            line.startswith('Uid:') and '10003' in line.split()
            for line in status.splitlines()
        ):
            found.append(argv)
    return found


class ExecutorTests(unittest.TestCase):
    """The suite is the runner on the socket, with no secrets."""

    workspace = pathlib.Path('/work/executor-tests')

    @classmethod
    def setUpClass(cls) -> None:
        as_user('agent', ['mkdir', '-p', str(cls.workspace / 'home')])

    def run_command(
        self, command: str, cwd: str | None = None, timeout: int | None = None
    ) -> Row:
        message: Row = {
            'op': 'run',
            'command': command,
            'cwd': cwd or str(self.workspace),
            'context': {},
            'secrets': [],
        }
        if timeout is not None:
            message['timeout_seconds'] = timeout
        reply = socket_call(message)
        self.assertIn('output', reply, reply)
        return reply

    def test_runs_in_the_workspace_with_home(self) -> None:
        reply = self.run_command('pwd -P; echo "$HOME"')
        self.assertEqual(reply['exit_code'], 0, reply)
        self.assertEqual(
            reply['output'],
            f'{self.workspace}\n{self.workspace}/home\n',
        )

    def test_symlink_in_place_of_the_workspace(self) -> None:
        # agent can make any entry in /work. The check runs after the
        # switch to agent, so the swap gives agent nothing.
        as_user('agent', ['ln', '-sfn', '/etc', '/work/swapped'])
        reply = self.run_command('pwd -P; cat hostname', cwd='/work/swapped')
        self.assertEqual(reply['exit_code'], 126, reply)
        self.assertIn('not in /work', reply['output'])
        self.assertNotIn('/etc', reply['output'])

    def test_large_output_is_bounded(self) -> None:
        reply = self.run_command("head -c 50000000 /dev/zero | tr '\\0' x")
        self.assertEqual(reply['exit_code'], 0, reply.get('error'))
        output = reply['output']
        self.assertTrue(output.endswith('\n[output truncated]'))
        self.assertLessEqual(len(output), 64 * 1024 + 20)

    def test_child_holding_the_pipe_ends_at_the_timeout(self) -> None:
        started = time.monotonic()
        reply = self.run_command('setsid sleep 1000 & echo started', timeout=3)
        elapsed = time.monotonic() - started
        self.assertIn('started', reply['output'])
        self.assertGreaterEqual(elapsed, 3)
        self.assertLess(elapsed, 15)
        reply = self.run_command('python3 /opt/isolation/probe.py processes')
        self.assertEqual(json.loads(reply['output']), [])


class EndOfChainTests(unittest.TestCase):
    """One chain per runner process; nothing of the chain stays."""

    task: typing.ClassVar[Row]
    before: typing.ClassVar[int | None]

    @classmethod
    def setUpClass(cls) -> None:
        wait_for_runner()
        deadline = time.monotonic() + 60
        while (before := probe.harness_pid('runner')) is None:
            if time.monotonic() > deadline:
                raise AssertionError('no runner process')
            time.sleep(0.2)
        cls.before = before
        cls.task = run_task(
            [
                {
                    'name': 'Bash',
                    'input': {
                        'command': 'setsid sleep 1000 '
                        '</dev/null >/dev/null 2>&1 &',
                        'description': 'Leave a process',
                    },
                },
                run_with_secret(
                    'setsid sleep 1001 </dev/null >/dev/null 2>&1 &'
                ),
            ]
        )
        deadline = time.monotonic() + 60
        while probe.harness_pid('runner') in (None, cls.before):
            if time.monotonic() > deadline:
                raise AssertionError('no new runner process')
            time.sleep(0.5)

    def test_the_runner_process_ended(self) -> None:
        self.assertIsNotNone(self.before)
        self.assertFalse(pathlib.Path(f'/proc/{self.before}').exists())

    def test_one_claim_per_runner(self) -> None:
        runners = fake_api('GET', '/test/state')['runners']
        (runner,) = [
            r for r in runners if self.task['chain_id'] in r['claims']
        ]
        self.assertEqual(runner['claims'], [self.task['chain_id']])
        self.assertEqual(runner['state'], 'offline')
        for other in runners:
            self.assertLessEqual(len(other['claims']), 1, other)

    def test_no_agent_process_in_the_runner_container(self) -> None:
        self.assertEqual(agent_processes(), [])

    def test_no_agent_process_in_the_executor_container(self) -> None:
        as_user('agent', ['mkdir', '-p', '/work/end-of-chain'])
        reply = socket_call(
            {
                'op': 'run',
                'command': 'python3 /opt/isolation/probe.py processes',
                'cwd': '/work/end-of-chain',
                'context': {},
                'secrets': [],
            }
        )
        self.assertEqual(json.loads(reply['output']), [])

    def test_workspace_removed(self) -> None:
        self.assertFalse(
            pathlib.Path(f'/work/{self.task["chain_id"]}').exists()
        )


def bash(command: str) -> Row:
    return {
        'name': 'Bash',
        'input': {'command': command, 'description': 'A test step'},
    }


class TaskFlowTests(unittest.TestCase):
    """A task with a repository, a pinned plugin, and a GitHub App."""

    task: typing.ClassVar[Row]
    detail: typing.ClassVar[Row]
    results: typing.ClassVar[list[str]]
    known = 'ghp_' + 'A' * 36
    text_bytes = 2_500_000

    @classmethod
    def setUpClass(cls) -> None:
        wait_for_runner()
        cls.task = fake_api(
            'POST',
            '/test/tasks',
            {
                'repository': True,
                'plugin': True,
                'binding': True,
                'final_text_bytes': cls.text_bytes,
                'script': [
                    bash(
                        'pwd; git log -1 --format=%s; cat .git/config; '
                        'ls "$CLAUDE_CONFIG_DIR"'
                    ),
                    {
                        'name': 'TodoWrite',
                        'input': {
                            'todos': [
                                {
                                    'content': 'Check the clone',
                                    'status': 'completed',
                                    'activeForm': 'Checking the clone',
                                }
                            ]
                        },
                    },
                    bash(f'echo {cls.known}'),
                    {
                        'name': 'Write',
                        'input': {
                            'file_path': '/work/written-by-a-denied-tool',
                            'content': 'x',
                        },
                    },
                ],
            },
        )
        deadline = time.monotonic() + 240
        while task_of(cls.task)['status'] != 'closed':
            if time.monotonic() > deadline:
                raise AssertionError('the task did not close')
            time.sleep(1)
        cls.detail = task_of(cls.task)
        cls.results = tool_results(cls.task)

    def events(self, kind: str) -> list[Row]:
        return [e for e in self.detail['events'] if e['type'] == kind]

    def test_outcome(self) -> None:
        self.assertEqual(
            (self.detail['outcome'], self.detail['outcome_reason']),
            ('done_acted', None),
        )

    def test_clone_in_the_workspace_without_a_credential(self) -> None:
        text = self.results[0]
        self.assertIn(f'/work/{self.task["chain_id"]}/repos/app', text)
        self.assertIn('app: first commit', text)
        self.assertIn('url = http://harness-fake-api:8080/git/app', text)
        self.assertNotIn('ghs_', text)
        self.assertNotIn('x-access-token', text)
        self.assertIn('settings.json', text)
        self.assertIn('CLAUDE.md', text)

    def test_setup_secrets_were_used_once_and_released(self) -> None:
        for purpose in (
            'model_inference',
            'workspace_checkout',
            'marketplace_fetch',
        ):
            with self.subTest(purpose=purpose):
                (resolution,) = resolutions_of(self.task, purpose)
                self.assertEqual(resolution['count'], 1)
                self.assertEqual(resolution['state'], 'released')
                self.assertEqual(resolution['ended_by'], 'executor')
        for purpose in ('workspace_checkout', 'marketplace_fetch'):
            (resolution,) = resolutions_of(self.task, purpose)
            self.assertGreaterEqual(resolution.get('git_uses', 0), 1)
            self.assertTrue(resolution['revoked'])

    def test_plugin_loaded(self) -> None:
        path = f'/run/creds/runner/transcripts/{self.task["id"]}.jsonl'
        result = as_user('runner', ['cat', path])
        self.assertEqual(result.returncode, 0, result.stderr)
        init = next(
            json.loads(line)
            for line in result.stdout.splitlines()
            if '"subtype": "init"' in line
        )
        paths = [p['path'] for p in init['data']['plugins']]
        self.assertTrue(
            any(p.endswith('/plugins/hello') for p in paths), paths
        )

    def test_tool_and_todo_events(self) -> None:
        calls = self.events('tool.called')
        self.assertEqual(
            [c['payload']['tool'] for c in calls],
            ['Bash', 'TodoWrite', 'Bash', 'Write'],
        )
        self.assertIn('app: first commit', calls[0]['payload']['result'])
        self.assertTrue(calls[0]['payload']['mutating'])
        (todos,) = self.events('todos.updated')
        self.assertEqual(
            todos['payload']['todos'],
            [
                {
                    'title': 'Check the clone',
                    'status': 'completed',
                    'done': True,
                }
            ],
        )

    def test_repository_settings_do_not_widen_the_policy(self) -> None:
        write = self.events('tool.called')[3]['payload']
        self.assertTrue(write['is_error'], write)
        self.assertFalse(
            pathlib.Path('/work/written-by-a-denied-tool').exists()
        )

    def test_repository_instructions_are_loaded(self) -> None:
        requests = json.dumps(
            fake_api(
                'GET', f'/test/model-requests?task={self.task["short_id"]}'
            )
        )
        self.assertIn('REPO-CLAUDE-MARKER', requests)
        self.assertIn('REPO-AGENTS-MARKER', requests)

    def test_known_formats_are_redacted(self) -> None:
        events = json.dumps(self.detail['events'])
        self.assertNotIn(self.known, events)
        self.assertIn(
            '[REDACTED]', self.events('tool.called')[2]['payload']['result']
        )
        # The model got the output: the CLI holds no redactor.
        self.assertIn(self.known, self.results[2])

    def test_large_turn_is_in_parts(self) -> None:
        parts = [e for e in self.events('turn') if 'parts' in e['payload']]
        self.assertGreaterEqual(len(parts), 3)
        (call_id,) = {p['payload']['call_id'] for p in parts}
        self.assertTrue(call_id)
        self.assertEqual(
            [p['payload']['part'] for p in parts],
            list(range(1, len(parts) + 1)),
        )
        body = ''.join(p['payload']['body'] for p in parts)
        self.assertEqual(body, 'y' * self.text_bytes)

    def test_usage_for_each_model_call(self) -> None:
        requests = fake_api(
            'GET', f'/test/model-requests?task={self.task["short_id"]}'
        )
        usage = self.detail['usage']
        self.assertGreaterEqual(len(usage), len(requests))
        self.assertEqual(len(requests), 5)
        for report in usage:
            self.assertEqual(report['tokens_in'], 10)
            self.assertEqual(report['tokens_out'], 5)
            self.assertEqual(report['cache_read_tokens'], 0)
            self.assertEqual(report['cache_write_tokens'], 0)
        self.assertNotIn({'bad_key': True}, requests)


class BudgetTests(unittest.TestCase):
    def test_over_budget_ends_with_no_more_model_calls(self) -> None:
        wait_for_runner()
        task = fake_api(
            'POST',
            '/test/tasks',
            {
                # One fake call costs 15 tokens at 0.000001 USD.
                'budget': '0.00001',
                'script': [bash('true'), bash('true'), bash('true')],
            },
        )
        run_task_until_done(task)
        detail = task_of(task)
        self.assertEqual(
            (detail['outcome'], detail['outcome_reason']),
            ('exceeded_ceiling', 'budget'),
        )
        requests = fake_api(
            'GET', f'/test/model-requests?task={task["short_id"]}'
        )
        self.assertEqual(len(requests), 1)


class CancelTests(unittest.TestCase):
    def test_cancel_stops_a_running_command(self) -> None:
        wait_for_runner()
        task = fake_api('POST', '/test/tasks', {'script': [bash('sleep 300')]})
        deadline = time.monotonic() + 120
        while not fake_api(
            'GET', f'/test/model-requests?task={task["short_id"]}'
        ):
            if time.monotonic() > deadline:
                raise AssertionError('the task did not start')
            time.sleep(0.5)
        time.sleep(3)
        fake_api(
            'POST',
            '/test/control',
            {'short_id': task['short_id'], 'control': 'cancel'},
        )
        started = time.monotonic()
        run_task_until_done(task, 90)
        self.assertLess(time.monotonic() - started, 60)
        detail = task_of(task)
        self.assertEqual(detail['outcome'], 'cancelled_by_human')
        self.assertEqual(agent_processes(), [])


def run_task_until_done(task: Row, timeout: float = 180) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        chains = fake_api('GET', '/test/state')['chains']
        if next(c for c in chains if c['id'] == task['chain_id'])['state'] == (
            'done'
        ):
            return
        time.sleep(1)
    raise AssertionError(f'task {task["short_id"]} did not end')


# --- P5 slice 2: tool policy, requests, child tasks ---------------------


def wait_for_event(task: Row, kind: str, timeout: float = 120) -> Row:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for event in task_of(task)['events']:
            if event['type'] == kind:
                return event
        time.sleep(0.5)
    raise AssertionError(f'no {kind} event in {task["short_id"]}')


def queue(body: Row) -> Row:
    wait_for_runner()
    return fake_api('POST', '/test/tasks', body)


def resolve(task: Row, status: str, answer: str | None = None) -> None:
    fake_api(
        'POST',
        '/test/resolve',
        {'short_id': task['short_id'], 'status': status, 'answer': answer},
    )


def tool_calls(task: Row) -> list[Row]:
    return [
        e['payload']
        for e in task_of(task)['events']
        if e['type'] == 'tool.called'
    ]


def children_of(task: Row) -> list[Row]:
    return [
        t
        for t in fake_api('GET', '/test/state')['tasks']
        if t['origin'].get('task_id') == task['id']
    ]


def child_task(**changes: typing.Any) -> Row:
    return {
        'name': 'mcp__imbi__create_child_task',
        'input': {
            'agent_slug': 'reviewer',
            'title': 'Review',
            'instruction': 'Review the change.',
        }
        | changes,
    }


class ApprovalTests(unittest.TestCase):
    """A webhook task: its text is untrusted, and Bash needs approval."""

    def run_approval(self, status: str) -> tuple[Row, list[str], Row]:
        task = queue(
            {
                'origin': 'webhook',
                'approval_tools': ['Bash'],
                'script': [bash('echo approved-run')],
            }
        )
        opened = wait_for_event(task, 'request.opened')
        self.assertEqual(task_of(task)['status'], 'blocked')
        self.assertEqual(opened['payload']['kind'], 'approval')
        self.assertTrue(
            opened['payload']['artifact_digests'][0].startswith('sha256:')
        )
        # The CLI waits in the hook while the task is blocked.
        time.sleep(3)
        resolve(task, status)
        run_task_until_done(task)
        return task, tool_results(task), opened

    def test_approved_call_runs(self) -> None:
        task, results, opened = self.run_approval('approved')
        self.assertIn('approved-run', results[0])
        (call,) = tool_calls(task)
        self.assertEqual(
            call['policy'],
            {
                'approval': True,
                'request_id': opened['payload']['request_id'],
                'decision': 'allow',
                'reason': None,
            },
        )
        self.assertEqual(task_of(task)['outcome'], 'done_acted')
        requests = json.dumps(
            fake_api('GET', f'/test/model-requests?task={task["short_id"]}')
        )
        self.assertIn('<untrusted source=\\"webhook\\">', requests)

    def test_rejected_call_does_not_run(self) -> None:
        task, results, _ = self.run_approval('rejected')
        self.assertIn('approval_rejected', results[0])
        self.assertNotIn('approved-run\n', results[0])
        (call,) = tool_calls(task)
        self.assertEqual(call['policy']['decision'], 'deny')
        self.assertTrue(call['is_error'])


class RequestInputTests(unittest.TestCase):
    def test_answer_reaches_the_model(self) -> None:
        task = queue(
            {
                'script': [
                    {
                        'name': 'mcp__imbi__request_input',
                        'input': {'question': 'Which color?'},
                    }
                ]
            }
        )
        opened = wait_for_event(task, 'request.opened')
        self.assertEqual(opened['payload']['kind'], 'feedback')
        self.assertEqual(opened['payload']['title'], 'Which color?')
        resolve(task, 'answered', 'blue')
        run_task_until_done(task)
        self.assertEqual(tool_results(task), ['blue'])


class RateLimitTests(unittest.TestCase):
    def test_second_call_is_refused(self) -> None:
        task = queue(
            {
                'tools': {
                    'imbi.run_with_secret': {
                        'rate_limit': {'count': 1, 'per': 'hour'}
                    }
                },
                'script': [run_with_secret('true'), run_with_secret('true')],
            }
        )
        run_task_until_done(task)
        first, second = tool_results(task)
        self.assertTrue(first.startswith('exit code 0'), first)
        self.assertIn('rate_limited', second)
        self.assertEqual(len(resolutions_of(task)), 1)


class ChildTaskTests(unittest.TestCase):
    """A child task for a second agent runs in the same pod and sees the
    parent's clone (plan P5 verify item 5)."""

    task: typing.ClassVar[Row]
    child: typing.ClassVar[Row]

    @classmethod
    def setUpClass(cls) -> None:
        cls.task = queue(
            {
                'repository': True,
                # The repositories are private: a checkout token.
                'binding': True,
                'child': {'script': [bash('cat from-parent.txt; pwd')]},
                'script': [
                    bash('echo hi-from-parent > from-parent.txt'),
                    child_task(),
                ],
            }
        )
        run_task_until_done(cls.task, 240)
        (cls.child,) = children_of(cls.task)

    def test_child_sees_the_parent_clone(self) -> None:
        (result,) = tool_results(self.child)
        self.assertIn('hi-from-parent', result)
        self.assertIn(f'/work/{self.task["chain_id"]}/repos/app', result)

    def test_both_end_done(self) -> None:
        self.assertEqual(task_of(self.child)['outcome'], 'done_acted')
        self.assertEqual(task_of(self.task)['outcome'], 'done_acted')
        summary = json.loads(tool_results(self.task)[1])
        self.assertEqual(summary['short_id'], self.child['short_id'])
        self.assertEqual(summary['outcome'], 'done_acted')

    def test_child_runs_as_its_own_agent_in_the_same_runner(self) -> None:
        (key,) = resolutions_of(self.child, 'model_inference')
        self.assertEqual(key['agent_id'], 'agent-2')
        runners = fake_api('GET', '/test/state')['runners']
        (runner,) = [
            r for r in runners if self.task['chain_id'] in r['claims']
        ]
        self.assertEqual(runner['claims'], [self.task['chain_id']])


class SwappedWorkspaceTests(unittest.TestCase):
    """The parent's model swaps the repository for a symlink to /etc
    before a child task starts. The child's CLI changes to its
    directory as agent and refuses a path outside the chain."""

    def test_child_does_not_start_outside_the_chain(self) -> None:
        task = queue(
            {
                'repository': True,
                # The repositories are private: a checkout token.
                'binding': True,
                'child': {'script': [bash('pwd')]},
                'script': [
                    bash('cd .. && mv app app.real && ln -s /etc app'),
                    child_task(),
                ],
            }
        )
        run_task_until_done(task, 240)
        (child,) = children_of(task)
        self.assertEqual(task_of(child)['outcome'], 'failed_external')
        self.assertEqual(
            fake_api('GET', f'/test/model-requests?task={child["short_id"]}'),
            [],
        )
        summary = json.loads(tool_results(task)[1])
        self.assertEqual(summary['outcome'], 'failed_external')


class AgentCliTests(unittest.TestCase):
    """``agent-cli`` changes to HARNESS_CWD as agent and checks it."""

    chain = '/work/agent-cli-chain'

    @classmethod
    def setUpClass(cls) -> None:
        as_user(
            'agent',
            ['mkdir', '-p', f'{cls.chain}/repo', f'{cls.chain}/scratch'],
        )
        as_user('agent', ['ln', '-sfn', '/etc', f'{cls.chain}/link'])

    def run_cli(self, cwd: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ['/usr/local/bin/agent-cli', '--version'],
            env={
                'PATH': '/usr/local/bin:/usr/bin:/bin',
                'HARNESS_CWD': cwd,
                'HARNESS_CHAIN': self.chain,
                'HARNESS_TMPDIR': f'{self.chain}/scratch',
                'HOME': f'{self.chain}/scratch',
            },
            cwd='/',
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def test_starts_in_the_chain(self) -> None:
        result = self.run_cli(f'{self.chain}/repo')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Claude Code', result.stdout)

    def test_symlink_out_of_the_chain_is_refused(self) -> None:
        result = self.run_cli(f'{self.chain}/link')
        self.assertEqual(result.returncode, 126)
        self.assertIn('not in the chain', result.stderr)

    def test_other_chain_is_refused(self) -> None:
        as_user('agent', ['mkdir', '-p', '/work/agent-cli-chainx'])
        result = self.run_cli('/work/agent-cli-chainx')
        self.assertEqual(result.returncode, 126)


class ModelKeyRequestTests(unittest.TestCase):
    """The model asks run_with_secret for the model key: refused, and
    the key reaches no output, event, or model request."""

    def test_model_key_is_refused(self) -> None:
        wait_for_runner()
        step = {
            'name': 'mcp__imbi__run_with_secret',
            'input': {
                'command': 'echo "key=$K"',
                'secrets': [
                    {
                        'reference': 'secret://production/anthropic/key',
                        'purpose': 'model_inference',
                        'env': 'K',
                    }
                ],
            },
        }
        task = run_task([step])
        (result,) = tool_results(task)
        self.assertIn('harness only', result)
        self.assertNotIn('key=', result)
        key = model_key()
        self.assertNotIn(key, json.dumps(task_of(task)['events']))
        self.assertNotIn(
            key,
            json.dumps(
                fake_api(
                    'GET', f'/test/model-requests?task={task["short_id"]}'
                )
            ),
        )
        # Only the runner's own model key resolution exists.
        (only,) = resolutions_of(task, 'model_inference')
        self.assertEqual(only['ended_by'], 'executor')


# --- P7.1: the Imbi relay ---------------------------------------------


def mcp_tool(name: str, **arguments: typing.Any) -> Row:
    return {'name': f'mcp__imbi_api__{name}', 'input': arguments}


def jti(token: str) -> str:
    payload = token.split('.')[1]
    padded = payload + '=' * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))['jti']


class RelayTests(unittest.TestCase):
    """The agent's mapped Imbi tools, relayed to a fake apps/mcp."""

    task: typing.ClassVar[Row]
    results: typing.ClassVar[list[str]]
    calls: typing.ClassVar[list[Row]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.task = queue(
            {
                'tools': {
                    'imbi.list_projects': {},
                    'imbi.update_project': {},
                },
                'script': [
                    mcp_tool('list_projects', org='test'),
                    # Longer than a runner heartbeat: the token renews.
                    bash('sleep 8'),
                    mcp_tool('list_projects', org='test'),
                    mcp_tool('delete_everything'),
                ],
            }
        )
        run_task_until_done(cls.task)
        cls.results = tool_results(cls.task)
        cls.calls = [
            call
            for call in fake_api('GET', '/test/mcp-calls')
            if call['task'] == cls.task['short_id']
        ]

    def test_relayed_result_is_untrusted(self) -> None:
        first = self.results[0]
        self.assertTrue(
            first.startswith('<untrusted source="mcp:imbi_api">'), first
        )
        self.assertIn('billing', first)
        self.assertIn('&lt;/untrusted>', first)

    def test_unmapped_tool_is_not_offered(self) -> None:
        self.assertNotIn('billing', self.results[3])
        self.assertEqual(
            [call['tool'] for call in self.calls],
            ['list_projects', 'list_projects'],
        )

    def test_the_token_is_renewed(self) -> None:
        first, second = (call['token'] for call in self.calls)
        self.assertNotEqual(first, second)

    def test_audit_fields_on_tool_called(self) -> None:
        relayed = [
            e['payload']
            for e in task_of(self.task)['events']
            if e['type'] == 'tool.called'
            and e['payload']['tool'] == 'mcp__imbi_api__list_projects'
        ]
        self.assertEqual(len(relayed), 2)
        for event, call in zip(relayed, self.calls, strict=True):
            audit = event['relay']
            self.assertEqual(audit['server'], 'imbi_api')
            self.assertEqual(audit['status'], 'ok')
            self.assertEqual(audit['token_jti'], jti(call['token']))
            self.assertTrue(audit['input_digest'].startswith('sha256:'))
            self.assertGreater(audit['bytes_out'], 0)
            self.assertIn('latency_ms', audit)

    def test_the_token_is_in_no_output(self) -> None:
        tokens = [call['token'] for call in self.calls]
        requests = json.dumps(
            fake_api(
                'GET', f'/test/model-requests?task={self.task["short_id"]}'
            )
        )
        events = json.dumps(task_of(self.task)['events'])
        path = f'/run/creds/runner/transcripts/{self.task["id"]}.jsonl'
        transcript = as_user('runner', ['cat', path]).stdout
        for token in tokens:
            for where, text in (
                ('model requests', requests),
                ('events', events),
                ('transcript', transcript),
            ):
                self.assertNotIn(token, text, where)
