"""Egress destinations: the internal hosts that runner pods may reach.

A ClusterNetworkPolicy in the runner namespace denies the internal
ranges to runner pods. A destination is a set of CIDRs and ports that
the egress sync (``imbi-harness egress-sync``) accepts with one policy
for each generation, or a set of host names on port 443 that the
egress proxy accepts (egress proxy plan 5.1). The claim gives a chain
the global destinations and the destinations of its root agent, but
only the generations that have a policy, so a new or narrowed
destination never gives more access than the policy (fail closed). A
host name destination needs no policy: the claim puts its host names
into the proxy token, so each generation is applied at once.
"""

import ipaddress
import typing

import idna
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
#: The most host names of one destination (egress proxy plan 5.1).
MAX_HOSTNAMES = 25


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


def canonical_hostname(name: str) -> str:
    """Return ``name`` in canonical form: IDNA A-labels, lower case, no
    trailing dot. The egress proxy compares this form (contract C3).

    Raises:
        ValueError: ``name`` is not a valid DNS name (a wildcard, a
            ``/``, ``@``, ``:``, ``[``, or ``]`` included), has no dot,
            or is an IP literal.

    """
    try:
        host = idna.encode(name.removesuffix('.'), uts46=True).decode()
    except idna.IDNAError as err:
        raise ValueError(f'{name!r} is not a valid host name') from err
    labels = host.split('.')
    # A top-level label is never numeric, so this also refuses an IPv4
    # literal in every form ("10.1.2.3", "0x0a.1").
    if len(labels) < 2 or not labels[-1][:1].isalpha():
        raise ValueError(f'{name!r} is not a fully qualified host name')
    return host


def check_hostnames(names: list[str]) -> list[str]:
    """Return the host names in canonical form, sorted, without
    duplicates.

    Raises:
        ValueError: A name is not valid (:func:`canonical_hostname`),
            or there are not 1 to :data:`MAX_HOSTNAMES` names.

    """
    hosts = {canonical_hostname(name) for name in names}
    if not 1 <= len(hosts) <= MAX_HOSTNAMES:
        raise ValueError(f'A destination has 1 to {MAX_HOSTNAMES} host names')
    return sorted(hosts)


def check_ports(ports: list[EgressPort]) -> list[EgressPort]:
    """Return the ports sorted, without duplicates.

    Raises:
        ValueError: There is no port.

    """
    unique = {(p.port, p.protocol): p for p in ports}
    if not unique:
        raise ValueError('A destination has at least one port')
    return [unique[key] for key in sorted(unique)]


#: The only ports of a host name destination: the proxy tunnels TLS.
HOSTNAME_PORTS = (EgressPort(port=443, protocol='TCP'),)


def check_kind(
    cidrs: list[str],
    hostnames: list[str],
    ports: list[EgressPort] | list[dict[str, typing.Any]],
) -> None:
    """Check that a destination has CIDRs or host names, and that a
    host name destination has only port 443/TCP.

    Raises:
        ValueError: Both or neither, or other ports.

    """
    if bool(cidrs) == bool(hostnames):
        raise ValueError('A destination has CIDRs or host names, not both')
    found = tuple(EgressPort.model_validate(p) for p in ports)
    if hostnames and found != HOSTNAME_PORTS:
        raise ValueError('A host name destination has only port 443/TCP')


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
    #: Empty for a CIDR destination. The proxy token holds them.
    hostnames: list[str] = []


def proxy_cidrs(egress: list[Grant]) -> list[dict[str, typing.Any]]:
    """The ``cidrs`` claim of a proxy token. Each CIDR of ``egress``
    gets the union of the TCP ports of its grants. The CIDRs with the
    same ports make one ``{"nets", "ports"}`` entry, so the token stays
    small: nets in network order, ports sorted, entries sorted by
    ports. A CIDR with only UDP ports is not in it."""
    ports: dict[ipaddress.IPv4Network, set[int]] = {}
    for grant in egress:
        tcp = {p.port for p in grant.ports if p.protocol == 'TCP'}
        for cidr in grant.cidrs if tcp else ():
            ports.setdefault(ipaddress.IPv4Network(cidr), set()).update(tcp)
    groups: dict[tuple[int, ...], list[str]] = {}
    for net in sorted(ports):
        groups.setdefault(tuple(sorted(ports[net])), []).append(str(net))
    return [
        {'nets': groups[key], 'ports': list(key)} for key in sorted(groups)
    ]


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
                hostnames=row['hostnames'],
            )
        )
    return granted, pending
