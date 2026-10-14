"""P5a lifecycle tests, run from the host against the kind cluster.

These stop a container, so they cannot run inside the pod.

- ``SIGTERM`` to the executor while a ``run_with_secret`` command runs:
  the executor releases the resolution before it exits.
- A partition between the pod and imbi-api only (the fake API stops
  answering the imbi-api routes; the model and GitHub routes still
  answer): the runner fences itself and exits before imbi-api requeues
  the chain, the lease sweep revokes the resolution, and the old token
  gets ``401`` from GitHub.

Environment: ``FAKE_API_URL`` (the fake API's node port), ``KUBE_CONTEXT``.
"""

import json
import os
import subprocess
import time
import typing
import unittest
import urllib.error
import urllib.request

FAKE_API = os.environ.get('FAKE_API_URL', 'http://localhost:30080')
CONTEXT = os.environ.get('KUBE_CONTEXT', 'kind-imbi-harness')
NAMESPACE = 'imbi-harness-test'
REFERENCE = 'secret://production/github/token'

Row = dict[str, typing.Any]


def fake_api(method: str, path: str, body: Row | None = None) -> typing.Any:
    request = urllib.request.Request(  # noqa: S310 - the fake API URL
        FAKE_API + path,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read() or b'null')


def github(token: str) -> int:
    request = urllib.request.Request(  # noqa: S310
        FAKE_API + '/github/write', headers={'Authorization': f'token {token}'}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            return response.status
    except urllib.error.HTTPError as err:
        with err:
            return err.code


def kubectl(*args: str) -> str:
    return subprocess.run(  # noqa: S603
        ['kubectl', '--context', CONTEXT, '-n', NAMESPACE, *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def container(name: str) -> Row:
    pod = json.loads(kubectl('get', 'pod', 'harness', '-o', 'json'))
    return next(
        c for c in pod['status']['containerStatuses'] if c['name'] == name
    )


def runner_exits() -> list[tuple[int, float]]:
    """The exit code and time of each runner process, from the loop of
    the test pod (manifests.yaml)."""
    exits = []
    for line in kubectl('logs', 'harness', '-c', 'runner').splitlines():
        if line.startswith('runner-exit '):
            _, code, at = line.split()
            exits.append((int(code), float(at)))
    return exits


def wait_for(
    check: typing.Callable[[], typing.Any], timeout: float, what: str
) -> typing.Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if value := check():
            return value
        time.sleep(0.5)
    raise AssertionError(f'timed out: {what}')


def state() -> Row:
    return fake_api('GET', '/test/state')


def resolution_of(task: Row) -> Row | None:
    """The ``run_with_secret`` resolution of a task, not a setup secret
    (the model key)."""
    return next(
        (
            r
            for r in state()['resolutions']
            if r['task_id'] == task['id'] and r['purpose'] == 'github_write'
        ),
        None,
    )


def chain_of(task: Row) -> Row:
    return next(c for c in state()['chains'] if c['id'] == task['chain_id'])


def long_command(seconds: int) -> list[Row]:
    return [
        {
            'name': 'mcp__imbi__run_with_secret',
            'input': {
                'command': f'sleep {seconds}',
                'secrets': [
                    {
                        'reference': REFERENCE,
                        'purpose': 'github_write',
                        'env': 'GH_TOKEN',
                    }
                ],
            },
        }
    ]


def setUpModule() -> None:
    """Wait until the node port answers and a runner polls for a claim."""

    def ready() -> bool:
        try:
            runners = state()['runners']
        except OSError:
            return False
        return any(
            r['polling'] and r['state'] == 'idle' and not r['synthetic']
            for r in runners
        )

    wait_for(ready, 120, 'a ready runner')


def start_long_command(seconds: int) -> tuple[Row, Row]:
    """Queue a task whose command runs; wait until it has its secret."""
    task = fake_api('POST', '/test/tasks', {'script': long_command(seconds)})

    def materialized() -> Row | None:
        resolution = resolution_of(task)
        if resolution and resolution['count'] == 1:
            return resolution
        return None

    return task, wait_for(materialized, 120, 'materialization')


def wait_ready(name: str, restarts: int) -> None:
    wait_for(
        lambda: (
            container(name)['restartCount'] > restarts
            and container(name)['ready']
        ),
        120,
        f'{name} restarted and ready',
    )


class LifecycleTests(unittest.TestCase):
    def test_1_sigterm_releases_the_resolution(self) -> None:
        task, _ = start_long_command(300)
        restarts = container('executor')['restartCount']
        kubectl(
            'exec',
            'harness',
            '-c',
            'executor',
            '--',
            'python3',
            '-c',
            'import os, signal; os.kill(1, signal.SIGTERM)',
        )
        resolution = wait_for(
            lambda: (r := resolution_of(task))
            and r['state'] != 'active'
            and r,
            20,
            'release after SIGTERM',
        )
        self.assertEqual(resolution['state'], 'released')
        self.assertEqual(resolution['ended_by'], 'executor')
        wait_ready('executor', restarts)
        wait_for(lambda: chain_of(task)['state'] == 'done', 120, 'chain done')

    def test_2_partition_fences_the_runner(self) -> None:
        task, resolution = start_long_command(40)
        (token,) = resolution['materials']
        self.assertEqual(github(token), 200)
        exits_before = len(runner_exits())
        fake_api('POST', '/test/partition', {'on': True})
        try:
            requeued = wait_for(
                lambda: chain_of(task)['requeued_at'], 90, 'requeue'
            )[0]
            exits = runner_exits()[exits_before:]
        finally:
            fake_api('POST', '/test/partition', {'on': False})
        # The runner process exited (fenced) before the chain went back
        # to the queue. The test pod's loop logs each exit.
        self.assertTrue(exits, 'the runner did not exit')
        code, finished = exits[0]
        self.assertEqual(code, 75)
        self.assertLess(finished, requeued)
        # The lease sweep revoked the token; GitHub refuses it.
        resolution = resolution_of(task)
        assert resolution is not None
        self.assertEqual(resolution['ended_by'], 'lease_sweep')
        self.assertEqual(github(token), 401)
        # A new attempt starts after the runner registers again.
        chain = wait_for(
            lambda: (c := chain_of(task))['attempt'] == 2
            and len(c['claimed_at']) == 2
            and c,
            120,
            'second attempt',
        )
        self.assertGreater(chain['claimed_at'][1], requeued)


if __name__ == '__main__':
    unittest.main()
