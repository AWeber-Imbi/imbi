"""Egress allowlist tests (egress allowlist PRD section 7), run from the
host against the pool that run-kind.sh renders from ``helm/imbi-harness``
with ``networkPolicy.enabled`` and ``manageGlobal``.

kind has no VPC CNI, so nothing enforces the policies, and the startup
self-test cannot pass (the CI host's IMDS answers). run-kind.sh turns
the runner's enforcement off; these tests cover what kind can:

- R9: the runner's projected token labels its own pod (``kube.py``).
- The runner pod-label admission policy: no other pod, no other label,
  no spec change.
- The egress-sync admission policy: Accept only, priority 200, the
  runner namespace only, and never the chart's own policies.
- R11: the egress-sync Deployment writes the policy of the fake API's
  destination and reports it applied.

Environment: ``FAKE_API_URL`` (the fake API's node port), ``KUBE_CONTEXT``.
"""

import json
import subprocess
import textwrap
import typing
import unittest

from test_lifecycle import CONTEXT, NAMESPACE, fake_api, kubectl, wait_for

Row = dict[str, typing.Any]
POOL = 'imbi.aweber.com/pool=general'
SYNC = f'system:serviceaccount:{NAMESPACE}:imbi-harness-egress-sync'
LABEL = 'egress.imbi.aweber.com/kind-test'

#: Run in the runner container as uid 0, with the pod's own token. It
#: sends one PATCH (a dry run unless ``apply``) and prints the status.
PATCH = textwrap.dedent("""
    import os, ssl, sys
    import httpx
    from imbi.harness import kube
    name, body, kind, apply = sys.argv[1:5]
    token = open(kube.TOKEN).read().strip()
    response = httpx.patch(
        f'{kube.API}/api/v1/namespaces/{os.environ["POD_NAMESPACE"]}'
        f'/pods/{name}',
        params={} if apply == '1' else {'dryRun': 'All'},
        content=body,
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': f'application/{kind}+json',
        },
        verify=ssl.create_default_context(cafile=kube.CA),
    )
    print(response.status_code, response.text)
""")


def pool_pod() -> str:
    found = json.loads(kubectl('get', 'pods', '-l', POOL, '-o', 'json'))
    return next(
        pod['metadata']['name']
        for pod in found['items']
        if pod['status'].get('phase') == 'Running'
        and not pod['metadata'].get('deletionTimestamp')
    )


def other_pod() -> str:
    return kubectl(
        'get',
        'pods',
        '-l',
        'app=harness-fake-api',
        '-o',
        'jsonpath={.items[0].metadata.name}',
    )


def patch(
    pod: str, target: str, body: Row | list[Row], *, apply: bool = False
) -> tuple[int, str]:
    """PATCH ``target`` with the token of ``pod``'s runner."""
    kind = 'json-patch' if isinstance(body, list) else 'merge-patch'
    out = kubectl(
        'exec',
        pod,
        '-c',
        'runner',
        '--',
        'python3',
        '-c',
        PATCH,
        target,
        json.dumps(body),
        kind,
        '1' if apply else '0',
    )
    status, _, text = out.strip().partition(' ')
    return int(status), text


def as_sync(*args: str, stdin: str | None = None) -> tuple[bool, str]:
    """``kubectl`` as the egress-sync service account: (allowed,
    output)."""
    result = subprocess.run(  # noqa: S603
        ['kubectl', '--context', CONTEXT, f'--as={SYNC}', *args],  # noqa: S607
        capture_output=True,
        text=True,
        input=stdin,
        check=False,
    )
    return result.returncode == 0, result.stdout + result.stderr


def policy(**changes: typing.Any) -> Row:
    """A valid destination policy, as the sync writes it."""
    body: Row = {
        'apiVersion': 'networking.k8s.aws/v1alpha1',
        'kind': 'ClusterNetworkPolicy',
        'metadata': {
            'name': 'imbi-harness-dest-isolation-g1',
            'labels': {
                'app.kubernetes.io/managed-by': 'imbi-harness-egress-sync'
            },
        },
        'spec': {
            'tier': 'Admin',
            'priority': 200,
            'subject': {
                'pods': {
                    'namespaceSelector': {
                        'matchLabels': {
                            'kubernetes.io/metadata.name': NAMESPACE
                        }
                    },
                    'podSelector': {
                        'matchLabels': {
                            'app.kubernetes.io/name': 'imbi-harness',
                            'egress.imbi.aweber.com/isolation': 'g1',
                        }
                    },
                }
            },
            'egress': [
                {
                    'name': 'isolation',
                    'action': 'Accept',
                    'to': [{'networks': ['10.1.0.0/16']}],
                    'ports': [
                        {'portNumber': {'port': 443, 'protocol': 'TCP'}}
                    ],
                }
            ],
        },
    }
    for path, value in changes.items():
        *parents, last = path.split('__')
        node = body['spec']
        for key in parents:
            node = node[key]
        node[last] = value
    return body


def create(body: Row) -> tuple[bool, str]:
    return as_sync(
        'create', '--dry-run=server', '-f', '-', stdin=json.dumps(body)
    )


class RunnerLabelTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.pod = pool_pod()

    def test_runner_labels_its_own_pod(self) -> None:
        """R9: the runner code path (``kube.label_own_pod``) with the
        pod's projected token, the Role, and the admission policy."""
        out = kubectl(
            'exec',
            self.pod,
            '-c',
            'runner',
            '--',
            'python3',
            '-c',
            'import asyncio; from imbi.harness import kube; '
            f'print(asyncio.run(kube.label_own_pod({{"{LABEL}": "g1"}})))',
        )
        self.assertEqual(out.strip().splitlines()[-1], 'True', out)
        labels = json.loads(kubectl('get', 'pod', self.pod, '-o', 'json'))[
            'metadata'
        ]['labels']
        self.assertEqual(labels.get(LABEL), 'g1')

    def test_admission_policy(self) -> None:
        other = other_pod()
        allowed = {'metadata': {'labels': {LABEL: 'g2'}}}
        for target, body, message in (
            (other, allowed, 'only its own pod'),
            (self.pod, {'metadata': {'labels': {'x': 'y'}}}, 'labels'),
            (
                self.pod,
                [
                    {
                        'op': 'remove',
                        'path': '/metadata/labels/app.kubernetes.io~1name',
                    }
                ],
                'labels',
            ),
            (self.pod, {'spec': {'activeDeadlineSeconds': 5}}, 'spec'),
        ):
            with self.subTest(target=target, body=body):
                status, text = patch(self.pod, target, body)
                self.assertEqual(status, 422, text)
                self.assertIn(message, text)
        status, text = patch(self.pod, self.pod, allowed)
        self.assertEqual(status, 200, text)


class SyncAdmissionTestCase(unittest.TestCase):
    def test_valid_policy(self) -> None:
        allowed, out = create(policy())
        self.assertTrue(allowed, out)

    def test_refused(self) -> None:
        for name, body, message in (
            (
                'deny rule',
                policy(
                    egress=[
                        {**policy()['spec']['egress'][0], 'action': 'Deny'}
                    ]
                ),
                'Accept',
            ),
            ('priority', policy(priority=150), 'priority 200'),
            (
                'other namespace',
                policy(
                    subject__pods__namespaceSelector={
                        'matchLabels': {'kubernetes.io/metadata.name': 'pse'}
                    }
                ),
                'subject',
            ),
        ):
            with self.subTest(name):
                allowed, out = create(body)
                self.assertFalse(allowed, out)
                self.assertIn(message, out)

    def test_cannot_delete_the_chart_policies(self) -> None:
        allowed, out = as_sync(
            'delete',
            '--dry-run=server',
            'clusternetworkpolicy',
            'imbi-harness-required',
        )
        self.assertFalse(allowed, out)
        self.assertIn('imbi-harness-dest-<slug>-g<generation>', out)


class SyncTestCase(unittest.TestCase):
    def test_writes_and_reports_the_destination(self) -> None:
        """R11: the sync writes the fake API's destination; the sync
        admission policy accepts the sync's own policy."""
        wait_for(
            lambda: subprocess.run(  # noqa: S603
                [  # noqa: S607
                    'kubectl',
                    '--context',
                    CONTEXT,
                    'get',
                    'clusternetworkpolicy',
                    'imbi-harness-dest-kind-test-g1',
                ],
                capture_output=True,
                check=False,
            ).returncode
            == 0,
            90,
            'the policy of the kind-test destination',
        )
        applied = wait_for(
            lambda: fake_api('GET', '/test/egress-applied'),
            90,
            'the applied report',
        )
        self.assertEqual(applied, [{'slug': 'kind-test', 'generation': 1}])
