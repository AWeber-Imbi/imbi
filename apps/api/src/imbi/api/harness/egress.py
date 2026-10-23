"""Egress destinations: the internal hosts that runner pods may reach.

A ClusterNetworkPolicy in the runner namespace denies the internal
ranges to runner pods. Each destination is a set of CIDRs and ports
that the egress sync (``imbi-harness egress-sync``) accepts with one
policy for each generation. The claim gives a chain the global
destinations and the destinations of its root agent, but only the
generations that have a policy, so a new or narrowed destination never
gives more access than the policy (fail closed).
"""

import ipaddress
import typing

import pydantic

from imbi.common import models

#: The ranges that a destination CIDR must be in. The chart denies
#: these (and link-local) to runner pods.
INTERNAL_RANGES = tuple(
    ipaddress.IPv4Network(cidr)
    for cidr in (
        '10.0.0.0/8',
        '172.16.0.0/12',
        '192.168.0.0/16',
        '100.64.0.0/10',
    )
)
#: The ranges that no destination may overlap: loopback and link-local
#: (the EC2 instance metadata service).
FORBIDDEN_RANGES = tuple(
    ipaddress.IPv4Network(cidr) for cidr in ('127.0.0.0/8', '169.254.0.0/16')
)
#: The VPC CNI limits (PRD constraint 5).
MAX_CIDRS = 25
MAX_PORTS_PER_CIDR = 24


class EgressPort(pydantic.BaseModel):
    port: int = pydantic.Field(ge=1, le=65535)
    protocol: typing.Literal['TCP', 'UDP'] = 'TCP'


def check_cidrs(cidrs: list[str]) -> list[str]:
    """Return the CIDRs in canonical form, sorted, without duplicates.

    Raises:
        ValueError: A CIDR does not parse, is not IPv4, is not inside
            an internal range, or overlaps loopback or link-local.

    """
    networks: set[ipaddress.IPv4Network] = set()
    for cidr in cidrs:
        try:
            network = ipaddress.ip_network(cidr, strict=True)
        except ValueError as err:
            raise ValueError(f'{cidr!r} is not a valid CIDR') from err
        if not isinstance(network, ipaddress.IPv4Network):
            raise ValueError(f'{cidr!r} is not an IPv4 CIDR')
        if any(network.overlaps(forbidden) for forbidden in FORBIDDEN_RANGES):
            raise ValueError(f'{cidr!r} overlaps loopback or link-local')
        if not any(network.subnet_of(r) for r in INTERNAL_RANGES):
            raise ValueError(f'{cidr!r} is not inside an internal range')
        networks.add(network)
    if not 1 <= len(networks) <= MAX_CIDRS:
        raise ValueError(f'A destination has 1 to {MAX_CIDRS} CIDRs')
    return [str(network) for network in sorted(networks)]


def check_ports(ports: list[EgressPort]) -> list[EgressPort]:
    """Return the ports sorted, without duplicates.

    Raises:
        ValueError: There is no port.

    """
    unique = {(p.port, p.protocol): p for p in ports}
    if not unique:
        raise ValueError('A destination has at least one port')
    return [unique[key] for key in sorted(unique)]


def port_pairs_over_limit(
    destinations: list[dict[str, typing.Any]],
) -> list[str]:
    """The CIDRs that get more than :data:`MAX_PORTS_PER_CIDR`
    port/protocol pairs across ``destinations`` (``cidrs``, ``ports``).
    The VPC CNI counts them per CIDR across every policy."""
    pairs: dict[str, set[tuple[int, str]]] = {}
    for row in destinations:
        for cidr in row['cidrs']:
            pairs.setdefault(str(cidr), set()).update(
                (int(p['port']), str(p['protocol'])) for p in row['ports']
            )
    return sorted(
        cidr
        for cidr, found in pairs.items()
        if len(found) > MAX_PORTS_PER_CIDR
    )


class Grant(pydantic.BaseModel):
    """A destination generation that a chain's pod gets."""

    slug: models.EgressDestinationSlug
    generation: int
    cidrs: list[str]
    ports: list[EgressPort]


class Pending(pydantic.BaseModel):
    """A destination that a claim left out, and why."""

    slug: str
    #: ``not_applied``: the policy of the current generation does not
    #: exist yet. ``organization_not_allowed``: the destination is not
    #: for the organization of the task. ``unknown``: no such live
    #: destination.
    reason: typing.Literal[
        'not_applied', 'organization_not_allowed', 'unknown'
    ]
    generation: int | None = None
    applied_generation: int | None = None


def grants(
    rows: list[dict[str, typing.Any]],
    slugs: list[str],
    organization_id: str,
) -> tuple[list[Grant], list[Pending]]:
    """Split the destinations of a claim into grants and left-out ones.

    ``rows`` are the live destinations; ``slugs`` are the agent's. The
    claim gets every global destination and each of ``slugs``, when
    its current generation is applied and it is for the organization.
    """
    by_slug = {row['slug']: row for row in rows}
    wanted = {row['slug'] for row in rows if row['is_global']} | set(slugs)
    granted: list[Grant] = []
    pending: list[Pending] = []
    for slug in sorted(wanted):
        row = by_slug.get(slug)
        if row is None:
            pending.append(Pending(slug=slug, reason='unknown'))
            continue
        orgs: list[str] = row['organization_ids']
        if not row['is_global'] and orgs and organization_id not in orgs:
            pending.append(
                Pending(slug=slug, reason='organization_not_allowed')
            )
            continue
        if row['applied_generation'] != row['generation']:
            pending.append(
                Pending(
                    slug=slug,
                    reason='not_applied',
                    generation=row['generation'],
                    applied_generation=row['applied_generation'],
                )
            )
            continue
        granted.append(
            Grant(
                slug=slug,
                generation=row['generation'],
                cidrs=row['cidrs'],
                ports=row['ports'],
            )
        )
    return granted, pending
