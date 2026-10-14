"""P5 pool tests, run from the host against a runner pool Deployment
rendered from ``helm/imbi-harness`` (plan P5 verify items 6 and 8).

- A pod deletes itself at the end of its chain, and the ReplicaSet
  starts a new pod that registers.
- Failure paths: the runner is killed during a tool call, the pod gets
  ``SIGTERM`` (as on an eviction), and imbi-api does not answer for one
  lease period. In each case the chain goes back to the queue with an
  ``attempt_marker``, no resolution stays active, and the GitHub token
  of the command gets ``401``.

Environment: ``FAKE_API_URL`` (the fake API's node port), ``KUBE_CONTEXT``.
"""

import json
import subprocess
import time
import typing
import unittest

from test_lifecycle import (
    CONTEXT,
    NAMESPACE,
    fake_api,
    github,
    kubectl,
    long_command,
    state,
    wait_for,
)

Row = dict[str, typing.Any]
POOL = 'imbi.aweber.com/pool=general'


def pods() -> list[str]:
    """The pool pods that are not being deleted."""
    found = json.loads(kubectl('get', 'pods', '-l', POOL, '-o', 'json'))
    return [
        pod['metadata']['name']
        for pod in found['items']
        if not pod['metadata'].get('deletionTimestamp')
    ]


def ready_runner() -> Row:
    """Wait for a pool runner that polls for a claim."""

    def polling() -> Row | None:
        live = set(pods())
        return next(
            (
                r
                for r in state()['runners']
                if r['polling']
                and r['state'] == 'idle'
                and r.get('instance') in live
            ),
            None,
        )

    return wait_for(polling, 180, 'a ready pool runner')


def task_detail(task: Row) -> Row:
    return fake_api('GET', f'/test/task?short_id={task["short_id"]}')


def chain_of(task: Row) -> Row:
    return next(c for c in state()['chains'] if c['id'] == task['chain_id'])


def resolution_of(task: Row) -> Row:
    return next(
        r
        for r in state()['resolutions']
        if r['task_id'] == task['id'] and r['purpose'] == 'github_write'
    )


def start_command(seconds: int) -> tuple[Row, Row, str]:
    """Queue a task whose command runs with a secret; wait until the
    secret is materialized. Return the task, the resolution, and the
    pod that runs it."""
    ready_runner()
    task = fake_api('POST', '/test/tasks', {'script': long_command(seconds)})

    def materialized() -> Row | None:
        for r in state()['resolutions']:
            if (
                r['task_id'] == task['id']
                and r['count'] == 1
                and (r['purpose'] == 'github_write')
            ):
                return r
        return None

    resolution = wait_for(materialized, 180, 'materialization')
    holder = next(
        r for r in state()['runners'] if task['chain_id'] in r['claims']
    )
    return task, resolution, str(holder['instance'])


class PoolTests(unittest.TestCase):
    def assert_requeued(self, task: Row, token: str) -> None:
        """Back in the queue with an attempt_marker, nothing active, the
        token refused; then a new attempt claims the chain."""
        wait_for(
            lambda: chain_of(task)['requeued_at'], 120, 'the chain requeued'
        )
        resolution = resolution_of(task)
        self.assertNotEqual(resolution['state'], 'active')
        self.assertEqual(github(token), 401)
        events = [e['type'] for e in task_detail(task)['events']]
        self.assertIn('attempt_marker', events)
        chain = wait_for(
            lambda: (c := chain_of(task))['attempt'] == 2
            and len(c['claimed_at']) == 2
            and c,
            180,
            'a second attempt',
        )
        self.assertGreater(chain['claimed_at'][1], chain['requeued_at'][0])
        # The second attempt runs the short command to the end.
        wait_for(lambda: chain_of(task)['state'] == 'done', 600, 'done')

    def test_1_pod_deletes_itself_after_its_chain(self) -> None:
        runner = ready_runner()
        old = str(runner['instance'])
        task = fake_api(
            'POST',
            '/test/tasks',
            {
                'script': [
                    {
                        'name': 'Bash',
                        'input': {'command': 'true', 'description': 'x'},
                    }
                ]
            },
        )
        wait_for(lambda: chain_of(task)['state'] == 'done', 180, 'done')
        wait_for(lambda: old not in pods(), 60, 'the old pod gone')
        new = ready_runner()
        self.assertNotEqual(new['instance'], old)

    def test_2_runner_killed_during_a_tool_call(self) -> None:
        task, resolution, pod = start_command(20)
        (token,) = resolution['materials']
        self.assertEqual(github(token), 200)
        # The runner process, not tini: a crash of the runner.
        # The container ends with the runner (tini exits with its child),
        # so this exec can end with SIGKILL too: its status is ignored.
        subprocess.run(  # noqa: S603
            [  # noqa: S607
                'kubectl',
                '--context',
                CONTEXT,
                '-n',
                NAMESPACE,
                'exec',
                pod,
                '-c',
                'runner',
                '--',
                'python3',
                '-c',
                'import os, signal, sys; '
                'sys.path.insert(0, "/opt/isolation"); import probe; '
                'os.kill(probe.harness_pid("runner"), signal.SIGKILL)',
            ],
            capture_output=True,
            check=False,
        )
        self.assert_requeued(task, token)

    def test_3_pod_terminated_during_a_tool_call(self) -> None:
        task, resolution, pod = start_command(20)
        (token,) = resolution['materials']
        started = time.time()
        # The same SIGTERM and grace period as an eviction.
        kubectl('delete', 'pod', pod, '--wait=false')
        requeued = wait_for(
            lambda: chain_of(task)['requeued_at'], 120, 'requeue'
        )[0]
        # The runner closed its session and finished in the grace
        # period, so imbi-api fenced the chain at once: the requeue
        # comes after the grace period (10 s), not after the lease
        # (15 s) and the grace period.
        self.assertLess(requeued - started, 20)
        self.assert_requeued(task, token)

    def test_4_api_outage_for_one_lease(self) -> None:
        task, resolution, _ = start_command(20)
        (token,) = resolution['materials']
        fake_api('POST', '/test/partition', {'on': True})
        try:
            wait_for(lambda: chain_of(task)['requeued_at'], 120, 'requeue')
        finally:
            fake_api('POST', '/test/partition', {'on': False})
        self.assert_requeued(task, token)


if __name__ == '__main__':
    unittest.main()
