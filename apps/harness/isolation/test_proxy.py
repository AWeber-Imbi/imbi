"""Egress proxy tests (egress proxy plan 12.5, X4), run from the host
against the proxy that run-kind.sh renders from ``helm/imbi-harness``
with ``egressProxy.enabled``.

- The pod watch: ``/readyz`` after the first list, and the pod map on
  ``/metrics`` follows the runner pods as they start and are deleted.
- A held internal name with the token of the source pod: allowed, and
  the tunnel reaches the target (proxy-manifests.yaml).
- The token from another runner pod, and after its pod is deleted:
  ``407``.
- T15: a new pod that gets the address of a deleted pod, with the token
  of the deleted pod: ``407``. kind gives pod addresses in turn, so the
  test starts pods in batches until one gets the old address. kind.yaml
  gives the node a /26 pod range, so this takes few batches.

The test pods have the runner label, so the proxy watches them; the
pool pods are in the pod map too.

Environment: ``KUBE_CONTEXT``.
"""

import base64
import functools
import hashlib
import hmac
import json
import subprocess
import textwrap
import time
import typing
import unittest
import uuid

from test_lifecycle import CONTEXT, NAMESPACE, kubectl, wait_for

HOST = f'target.{NAMESPACE}.svc.cluster.local'
RUNNER = 'app.kubernetes.io/name=imbi-harness'
TEST = 'imbi.aweber.com/proxy-test'
#: Less than the free addresses of the /26 pod range (61, less about 13
#: suite pods), with room for the pods of the batch before that are
#: still terminating.
BATCH = 20

#: Run in a runner pod: one CONNECT to HOST:443 through the proxy
#: Service. It prints the proxy status and, after a 200, the status
#: line of the target.
CONNECT = textwrap.dedent("""
    import base64, socket, sys
    host, token = sys.argv[1:3]
    auth = base64.b64encode(f'chain:{token}'.encode()).decode()
    s = socket.create_connection(('imbi-egress-proxy', 3128), timeout=15)
    s.sendall(
        f'CONNECT {host}:443 HTTP/1.1\\r\\nHost: {host}:443\\r\\n'
        f'Proxy-Authorization: Basic {auth}\\r\\n\\r\\n'.encode())
    status = s.recv(1024).split(b' ')[1].decode()
    if status != '200':
        print(status)
        sys.exit()
    s.sendall(b'GET / HTTP/1.0\\r\\n\\r\\n')
    print(status, s.recv(1024).split(b'\\r\\n')[0].decode())
""")
ALLOWED = '200 HTTP/1.0 200 OK'


@functools.cache
def key() -> bytes:
    """The proxy token key, from the fixture Secret."""
    data = kubectl(
        'get',
        'secret',
        'imbi-egress-proxy',
        '-o',
        'jsonpath={.data.current}',
    )
    return base64.b64decode(data)


def b64(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b'=')


def token(pod_uid: str) -> str:
    """A proxy token for ``pod_uid`` that holds HOST. The source of
    truth is ``imbi.api.harness.tokens.mint_proxy_token``."""
    now = int(time.time())
    claims = {
        'iss': 'imbi-api',
        'aud': 'imbi-egress-proxy',
        'iat': now,
        'exp': now + 600,
        'chain': str(uuid.uuid4()),
        'attempt': 1,
        'pod': pod_uid,
        'hosts': sorted({HOST}),
        'cidrs': [],
    }
    signed = b'.'.join(
        b64(json.dumps(part, separators=(',', ':')).encode())
        for part in ({'alg': 'HS256', 'typ': 'JWT'}, claims)
    )
    signature = hmac.new(key(), signed, hashlib.sha256).digest()
    return (signed + b'.' + b64(signature)).decode()


@functools.cache
def proxy_pod() -> str:
    return kubectl(
        'get',
        'pods',
        '-l',
        'app.kubernetes.io/name=imbi-egress-proxy',
        '-o',
        'jsonpath={.items[0].metadata.name}',
    )


def admin(path: str) -> str:
    """GET ``path`` on the proxy admin port, through the API server."""
    return kubectl(
        'get',
        '--raw',
        f'/api/v1/namespaces/{NAMESPACE}/pods/{proxy_pod()}:9090/proxy{path}',
    )


def metric(name: str, *labels: str) -> int:
    """The value of the series of ``name`` with every one of ``labels``
    (``key="value"``), or 0 before the series exists."""
    for line in admin('/metrics').splitlines():
        series, _, value = line.rpartition(' ')
        if series.split('{')[0] == name and all(
            label in series for label in labels
        ):
            return int(value)
    return 0


def live_runners() -> int:
    """The runner pods that are running and not being deleted."""
    found = json.loads(kubectl('get', 'pods', '-l', RUNNER, '-o', 'json'))
    return sum(
        pod['status'].get('phase') == 'Running'
        and not pod['metadata'].get('deletionTimestamp')
        for pod in found['items']
    )


class Runner(typing.NamedTuple):
    name: str
    uid: str
    ip: str


def start(names: list[str], batch: str) -> list[Runner]:
    """Start one runner pod for each name, and wait until all are
    ready."""
    pods = {
        'apiVersion': 'v1',
        'kind': 'List',
        'items': [
            {
                'apiVersion': 'v1',
                'kind': 'Pod',
                'metadata': {
                    'name': name,
                    'labels': {
                        'app.kubernetes.io/name': 'imbi-harness',
                        TEST: batch,
                    },
                },
                'spec': {
                    'terminationGracePeriodSeconds': 0,
                    'containers': [
                        {
                            'name': 'runner',
                            'image': 'python:3.13-alpine',
                            'command': ['sleep', '3600'],
                        }
                    ],
                },
            }
            for name in names
        ],
    }
    command = ['kubectl', '--context', CONTEXT, '-n', NAMESPACE, 'create']
    subprocess.run(  # noqa: S603
        [*command, '-f', '-'],
        input=json.dumps(pods),
        capture_output=True,
        text=True,
        check=True,
    )
    kubectl(
        'wait',
        '--for=condition=Ready',
        'pods',
        '-l',
        f'{TEST}={batch}',
        '--timeout=180s',
    )
    found = json.loads(
        kubectl('get', 'pods', '-l', f'{TEST}={batch}', '-o', 'json')
    )
    return [
        Runner(
            pod['metadata']['name'],
            pod['metadata']['uid'],
            pod['status']['podIP'],
        )
        for pod in found['items']
    ]


def delete(*args: str) -> None:
    kubectl('delete', 'pods', '--wait=false', *args)


def connect(runner: Runner, proxy_token: str) -> str:
    return kubectl(
        'exec', runner.name, '--', 'python3', '-c', CONNECT, HOST, proxy_token
    ).strip()


class ProxyTests(unittest.TestCase):
    def setUp(self) -> None:
        # The pool pods are in the pod map too.
        def pool() -> tuple[int] | None:
            n = live_runners()
            return (n,) if n == metric('imbi_egress_proxy_pods') else None

        [self.pool] = wait_for(pool, 60, 'the pod map holds the runner pods')

    def tearDown(self) -> None:
        delete('-l', TEST)
        self.pod_map_is(0)

    def pod_map_is(self, size: int) -> None:
        wait_for(
            lambda: metric('imbi_egress_proxy_pods') == self.pool + size,
            60,
            f'{size} test pods in the pod map',
        )

    def assert_refused(
        self, runner: Runner, proxy_token: str, reason: str
    ) -> None:
        def count() -> int:
            return metric(
                'imbi_egress_proxy_decisions_total',
                f'reason="{reason}"',
                'result="407"',
            )

        before = count()
        self.assertEqual(connect(runner, proxy_token), '407')
        self.assertEqual(count(), before + 1)

    def test_pod_watch(self) -> None:
        self.assertEqual(admin('/readyz'), 'ok\n')
        self.assertEqual(metric('imbi_egress_proxy_watch_up'), 1)
        [a] = start(['runner-a'], 'a')
        self.pod_map_is(1)
        [b] = start(['runner-b'], 'b')
        self.pod_map_is(2)
        token_a = token(a.uid)

        self.assertEqual(connect(a, token_a), ALLOWED)
        # Another runner pod with the token of a.
        self.assert_refused(b, token_a, 'pod_address')

        delete(a.name)
        self.pod_map_is(1)
        self.assert_refused(b, token_a, 'pod_unknown')
        self.assertEqual(connect(b, token(b.uid)), ALLOWED)

    def test_reused_address(self) -> None:
        """T15: the token of a deleted pod, from a new pod that has its
        address."""
        [old] = start(['runner-old'], 'old')
        old_token = token(old.uid)
        self.assertEqual(connect(old, old_token), ALLOWED)
        delete(old.name)
        # The /26 pod range has 61 addresses: 4 batches go round it.
        for n in range(8):
            batch = f'new-{n}'
            names = [f'runner-{batch}-{i}' for i in range(BATCH)]
            new = next(
                (r for r in start(names, batch) if r.ip == old.ip), None
            )
            if new:
                delete(
                    '-l',
                    f'{TEST}={batch}',
                    f'--field-selector=metadata.name!={new.name}',
                )
                break
            delete('-l', f'{TEST}={batch}')
        else:
            self.fail(f'no new pod got the address {old.ip}')
        print(
            f'\nT15: {new.name} ({new.uid}) has the address {new.ip} '
            f'of {old.name} ({old.uid}), after {n + 1} batches'
        )
        self.assert_refused(new, old_token, 'pod_unknown')
        self.assertEqual(connect(new, token(new.uid)), ALLOWED)
