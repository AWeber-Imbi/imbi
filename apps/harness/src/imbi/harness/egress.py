"""Egress allowlists of runner pods (egress allowlist PRD).

Amazon VPC CNI ``ClusterNetworkPolicy`` objects block runner pods from
internal addresses, except for the egress destinations of their chain:

- The chart renders the required targets (Admin, priority 100) and the
  Baseline policies (Deny internal ranges, then Accept all).
- ``imbi-harness egress-sync`` (:func:`sync_main`) writes one Admin
  policy (priority 200) for each destination generation. It selects
  the runner pods that have the label of that generation.
- The runner tests at start that its pod is enforced
  (:func:`self_test`), then labels its pod with the destinations of
  its chain (:func:`labels`).
"""

import asyncio
import dataclasses
import http
import ipaddress
import logging
import os
import pathlib
import re
import socket
import ssl
import time
import typing

import httpx

from imbi.harness import api, kube

if typing.TYPE_CHECKING:
    from collections import abc

LOGGER = logging.getLogger(__name__)

type Body = api.Body

LABEL_PREFIX = 'egress.imbi.aweber.com/'
MANAGED_BY = 'imbi-harness-egress-sync'
POLICIES = '/apis/networking.k8s.aws/v1alpha1/clusternetworkpolicies'
#: The slug can have hyphens: the generation is the last ``-g<n>``.
POLICY_NAME = re.compile(r'^imbi-harness-dest-(?P<slug>.+)-g(?P<gen>[0-9]+)$')
IMDS = ('169.254.169.254', 80)
#: Seconds between two sync rounds.
INTERVAL = 30
#: The time for one TCP connection attempt.
CONNECT_SECONDS = 3.0
#: Pods that have ended hold no destination.
ENDED = frozenset({'Succeeded', 'Failed'})


def label(slug: str) -> str:
    return LABEL_PREFIX + slug


def labels(egress: abc.Iterable[Body]) -> dict[str, str]:
    """The pod labels of the destinations of a chain."""
    return {label(str(d['slug'])): f'g{d["generation"]}' for d in egress}


def policy_name(slug: str, generation: int) -> str:
    return f'imbi-harness-dest-{slug}-g{generation}'


# --- Runner -----------------------------------------------------------


async def connects(host: str, port: int) -> bool:
    """Whether a TCP connection to ``host:port`` opens in time."""
    try:
        async with asyncio.timeout(CONNECT_SECONDS):
            _reader, writer = await asyncio.open_connection(host, port)
    except OSError:  # TimeoutError too
        return False
    writer.close()
    return True


async def answers(host: str, port: int) -> bool:
    """Whether ``host:port`` accepts or refuses a TCP connection. A
    network policy drops packets, so only a timeout (or no route)
    shows that the pod is blocked.

    Raises:
        SystemExit: ``host`` does not resolve.

    """
    try:
        async with asyncio.timeout(CONNECT_SECONDS):
            _reader, writer = await asyncio.open_connection(host, port)
    except ConnectionRefusedError:
        return True
    except socket.gaierror as err:
        raise SystemExit(f'{host} does not resolve: {err}') from err
    except OSError:  # TimeoutError too
        return False
    writer.close()
    return True


async def self_test(canary: tuple[str, int], seconds: float = 60) -> None:
    """Return when IMDS and the internal canary do not connect (PRD
    5.3). A new pod has open egress until the network policy agent
    programs it, so try again for up to ``seconds``.

    Raises:
        SystemExit: The pod is not enforced. The pod restarts, and no
            chain runs on it.

    """
    deadline = time.monotonic() + seconds
    while True:
        opened = [
            f'{host}:{port}'
            for host, port in (IMDS, canary)
            if await answers(host, port)
        ]
        if not opened:
            LOGGER.info('Egress self-test passed')
            return
        if time.monotonic() >= deadline:
            raise SystemExit(
                'Egress is not enforced: ' + ', '.join(opened) + ' answered'
            )
        LOGGER.warning('Egress not enforced yet: %s', ', '.join(opened))
        await asyncio.sleep(2)


async def probe(egress: abc.Iterable[Body], seconds: float = 30) -> list[str]:
    """The slugs of the TCP destinations that did not connect in
    ``seconds`` (PRD 5.7). A hint only: the probe tries the first host
    of the first CIDR on the first TCP port, and a UDP-only destination
    is not tried.
    """
    targets: dict[str, tuple[str, int]] = {}
    for destination in egress:
        port = next(
            (
                int(p['port'])
                for p in destination['ports']
                if p['protocol'] == 'TCP'
            ),
            None,
        )
        if port is None or not destination['cidrs']:
            continue
        network = ipaddress.ip_network(destination['cidrs'][0], strict=False)
        host = str(next(iter(network.hosts()), network.network_address))
        targets[str(destination['slug'])] = (host, port)
    deadline = time.monotonic() + seconds
    while True:
        results = await asyncio.gather(
            *(connects(*target) for target in targets.values())
        )
        targets = {
            slug: target
            for (slug, target), ok in zip(
                targets.items(), results, strict=True
            )
            if not ok
        }
        if not targets or time.monotonic() >= deadline:
            return list(targets)
        await asyncio.sleep(1)


# --- Sync -------------------------------------------------------------


@dataclasses.dataclass
class Plan:
    #: The live destinations that have no policy.
    create: list[Body]
    #: The names of the managed policies to delete.
    delete: list[str]
    #: ``{slug, generation}`` of each live destination with a policy.
    applied: list[Body]
    #: The names of the superseded policies that no pod holds.
    unheld: list[str] = dataclasses.field(default_factory=list)


def plan(
    destinations: abc.Iterable[Body],
    policies: abc.Iterable[Body],
    held: abc.Set[tuple[str, str]],
    unheld_before: abc.Set[str] = frozenset(),
) -> Plan:
    """What one sync round does (PRD 5.6).

    ``policies`` are the cluster's policies; only those with the
    managed-by label are changed. ``held`` is each ``(label, value)``
    that a running pod has: its policy stays until the pod ends.
    ``unheld_before`` is ``Plan.unheld`` of the previous round. A
    policy is deleted only when it is unheld in two rounds in a row,
    because a runner gets its claim before it labels its pod.
    """
    managed = {
        str(p['metadata']['name'])
        for p in policies
        if _labels(p).get('app.kubernetes.io/managed-by') == MANAGED_BY
    }
    wanted = {
        policy_name(str(d['slug']), int(d['generation'])): d
        for d in destinations
        if not d.get('deleted')
    }
    result = Plan([], [], [])
    for name, destination in wanted.items():
        if name in managed:
            result.applied.append(_applied(destination))
        else:
            result.create.append(destination)
    for name in sorted(managed - wanted.keys()):
        match = POLICY_NAME.match(name)
        if match and (label(match['slug']), f'g{match["gen"]}') not in held:
            result.unheld.append(name)
            if name in unheld_before:
                result.delete.append(name)
    return result


def _applied(destination: Body) -> Body:
    return {
        'slug': str(destination['slug']),
        'generation': int(destination['generation']),
    }


def policy(destination: Body, namespace: str) -> Body:
    """The Admin Accept policy of one destination generation."""
    slug = str(destination['slug'])
    generation = int(destination['generation'])
    return {
        'apiVersion': 'networking.k8s.aws/v1alpha1',
        'kind': 'ClusterNetworkPolicy',
        'metadata': {
            'name': policy_name(slug, generation),
            'labels': {'app.kubernetes.io/managed-by': MANAGED_BY},
        },
        'spec': {
            'tier': 'Admin',
            'priority': 200,
            'subject': {
                'pods': {
                    'namespaceSelector': {
                        'matchLabels': {
                            'kubernetes.io/metadata.name': namespace
                        }
                    },
                    'podSelector': {
                        'matchLabels': {
                            'app.kubernetes.io/name': 'imbi-harness',
                            label(slug): f'g{generation}',
                        }
                    },
                }
            },
            'egress': [
                {
                    'name': slug,
                    'action': 'Accept',
                    'to': [{'networks': list(destination['cidrs'])}],
                    'ports': [
                        {
                            'portNumber': {
                                'port': int(p['port']),
                                'protocol': str(p['protocol']),
                            }
                        }
                        for p in destination['ports']
                    ],
                }
            ],
        },
    }


def held_labels(pods: abc.Iterable[Body]) -> set[tuple[str, str]]:
    """Each egress ``(label, value)`` of a pod that has not ended."""
    return {
        (key, str(value))
        for pod in pods
        if typing.cast('Body', pod.get('status') or {}).get('phase')
        not in ENDED
        for key, value in _labels(pod).items()
        if key.startswith(LABEL_PREFIX)
    }


def _labels(item: Body) -> dict[str, str]:
    return typing.cast('dict[str, str]', item['metadata'].get('labels') or {})


class Sync:
    """``imbi-harness egress-sync``: one replica in the runner
    namespace, with its own service account token (no uid split)."""

    def __init__(
        self, api_url: str, credential: tuple[str, str], namespace: str
    ) -> None:
        self.api = api.Api(api_url)
        self.credential = credential
        self.namespace = namespace
        self.unheld: set[str] = set()

    async def serve(self) -> None:
        while True:
            try:
                await self.round()
            except (api.Refused, httpx.HTTPError, OSError, KeyError) as err:
                LOGGER.warning('Egress sync failed: %r', err)
            await asyncio.sleep(INTERVAL)

    async def round(self) -> None:
        token = await self.api.pool_token(*self.credential)
        destinations = await self.api.egress_destinations(token)
        async with self._kube() as client:
            policies = await _items(
                client,
                POLICIES,
                f'app.kubernetes.io/managed-by={MANAGED_BY}',
            )
            pods = await _items(
                client,
                f'/api/v1/namespaces/{self.namespace}/pods',
                'app.kubernetes.io/name=imbi-harness',
            )
            todo = plan(destinations, policies, held_labels(pods), self.unheld)
            self.unheld = set(todo.unheld)
            for destination in todo.create:
                body = policy(destination, self.namespace)
                response = await client.post(POLICIES, json=body)
                if response.is_success:
                    LOGGER.info('Created %s', body['metadata']['name'])
                    todo.applied.append(_applied(destination))
                else:
                    # 409: a policy without the label has the name.
                    LOGGER.warning(
                        'Create %s refused: %s',
                        body['metadata']['name'],
                        response.status_code,
                    )
            for name in todo.delete:
                response = await client.delete(f'{POLICIES}/{name}')
                if (
                    response.is_success
                    or response.status_code == http.HTTPStatus.NOT_FOUND
                ):
                    LOGGER.info('Deleted %s', name)
                else:
                    LOGGER.warning(
                        'Delete %s refused: %s', name, response.status_code
                    )
        # Every round: it is the sync heartbeat too.
        await self.api.report_applied(token, todo.applied)

    def _kube(self) -> httpx.AsyncClient:
        token = pathlib.Path(kube.TOKEN).read_text(encoding='utf-8').strip()
        return httpx.AsyncClient(
            base_url=kube.API,
            verify=ssl.create_default_context(cafile=kube.CA),
            headers={'Authorization': f'Bearer {token}'},
            timeout=10,
        )


async def _items(
    client: httpx.AsyncClient, path: str, selector: str
) -> list[Body]:
    response = await client.get(path, params={'labelSelector': selector})
    response.raise_for_status()
    return api.items(response.json(), 'items')


def sync_main() -> None:
    sync = Sync(
        os.environ['IMBI_API_URL'],
        (
            os.environ['IMBI_HARNESS_CLIENT_ID'],
            os.environ['IMBI_HARNESS_CLIENT_SECRET'],
        ),
        os.environ['POD_NAMESPACE'],
    )
    asyncio.run(sync.serve())
