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


def resolutions_of(task: Row) -> list[Row]:
    return [
        row
        for row in fake_api('GET', '/test/state')['resolutions']
        if row['task_id'] == task['id']
    ]


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
        self.assertEqual(self.result['model_key'], DENIED)
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
