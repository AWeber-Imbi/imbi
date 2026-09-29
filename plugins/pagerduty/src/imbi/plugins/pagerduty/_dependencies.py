"""Sync Imbi ``DEPENDS_ON`` edges to PagerDuty service dependencies.

Imbi's ``(:Project)-[:DEPENDS_ON]->(:Project)`` maps onto a PagerDuty
technical-service dependency: the depending project's service is the
``dependent_service`` and the depended-on project's service is the
``supporting_service``.  A project reconciles the dependencies it takes
part in, in both directions, so one call converges the pair whichever
side changed.

Removal is deliberately narrow: a PagerDuty dependency is removed only
when the service on the other side is itself bound to an Imbi project
(checked through :attr:`PluginContext.resolve_linked_identifiers`) and
Imbi holds no ``DEPENDS_ON`` between the two.  Dependencies on services
Imbi does not manage, and on business services, are never touched.
Without a resolver nothing is removed.

Used by the lifecycle capability (``on_project_dependencies_changed``)
and the doctor capability (the ``sync-dependencies`` finding and fix).

Open PagerDuty-API assumption to confirm against a live tenant:
``GET /service_dependencies/technical_services/{id}`` returns every
dependency the service takes part in, unpaginated, under
``relationships``.
"""

from __future__ import annotations

import dataclasses
import typing
from collections import abc

import httpx

from imbi.common.plugins.base import PluginContext, ServiceConnection
from imbi.plugins.pagerduty import _provisioning

#: PagerDuty reference type for a technical service in a dependency.
_SERVICE_TYPE = 'service'


@dataclasses.dataclass(frozen=True, order=True)
class Pair:
    """One PagerDuty dependency: ``dependent`` depends on ``supporting``."""

    dependent: str
    supporting: str

    def other(self, service_id: str) -> str:
        """Return the service on the side opposite ``service_id``."""
        if self.dependent == service_id:
            return self.supporting
        return self.dependent

    def as_relationship(self) -> dict[str, typing.Any]:
        return {
            'dependent_service': {
                'id': self.dependent,
                'type': _SERVICE_TYPE,
            },
            'supporting_service': {
                'id': self.supporting,
                'type': _SERVICE_TYPE,
            },
        }


@dataclasses.dataclass
class Plan:
    """The changes that bring PagerDuty in line with Imbi."""

    add: list[Pair] = dataclasses.field(default_factory=list)
    remove: list[Pair] = dataclasses.field(default_factory=list)
    #: Slugs of neighbour projects with no PagerDuty service, which
    #: therefore cannot be expressed as a PagerDuty dependency.
    unlinked: list[str] = dataclasses.field(default_factory=list)

    @property
    def in_sync(self) -> bool:
        return not self.add and not self.remove

    def summary(self) -> str:
        parts: list[str] = []
        if self.add:
            parts.append(f'add {len(self.add)}')
        if self.remove:
            parts.append(f'remove {len(self.remove)}')
        return ', '.join(parts) or 'no changes'


def own_service_id(ctx: PluginContext) -> str | None:
    """Return the project's PagerDuty service id from its EXISTS_IN edge."""
    return _service_id_for(ctx, ctx.service_connections)


def _service_id_for(
    ctx: PluginContext, connections: abc.Iterable[ServiceConnection]
) -> str | None:
    for connection in connections:
        if (
            connection.integration_slug == ctx.integration_slug
            and connection.identifier
        ):
            return connection.identifier
    return None


def desired_pairs(
    ctx: PluginContext, service_id: str
) -> tuple[set[Pair], list[str]]:
    """Return the dependencies Imbi expects, plus unlinked neighbours."""
    desired: set[Pair] = set()
    unlinked: list[str] = []
    for dep in ctx.dependencies:
        other = _service_id_for(ctx, dep.service_connections)
        if other is None:
            unlinked.append(dep.project_slug)
            continue
        if other == service_id:
            continue
        if dep.direction == 'outbound':
            desired.add(Pair(dependent=service_id, supporting=other))
        else:
            desired.add(Pair(dependent=other, supporting=service_id))
    return desired, sorted(unlinked)


async def current_pairs(
    client: httpx.AsyncClient, service_id: str
) -> set[Pair]:
    """Return the technical-service dependencies ``service_id`` is in."""
    response = await client.get(
        f'/service_dependencies/technical_services/{service_id}'
    )
    response.raise_for_status()
    payload: dict[str, typing.Any] = response.json()
    relationships: list[dict[str, typing.Any]] = (
        payload.get('relationships') or []
    )
    pairs: set[Pair] = set()
    for relationship in relationships:
        dependent = _provisioning.as_dict(relationship.get('dependent_service'))
        supporting = _provisioning.as_dict(relationship.get('supporting_service'))
        if (
            dependent.get('type') != _SERVICE_TYPE
            or supporting.get('type') != _SERVICE_TYPE
        ):
            # Business-service links are not modelled in Imbi.
            continue
        dependent_id = str(dependent.get('id') or '')
        supporting_id = str(supporting.get('id') or '')
        if service_id in (dependent_id, supporting_id) and all(
            (dependent_id, supporting_id)
        ):
            pairs.add(Pair(dependent=dependent_id, supporting=supporting_id))
    return pairs


async def plan(
    client: httpx.AsyncClient, ctx: PluginContext, service_id: str
) -> Plan:
    """Compare Imbi and PagerDuty and return the changes to make."""
    desired, unlinked = desired_pairs(ctx, service_id)
    current = await current_pairs(client, service_id)
    extra = sorted(current - desired)
    remove: list[Pair] = []
    if extra and ctx.resolve_linked_identifiers is not None:
        others = sorted({pair.other(service_id) for pair in extra})
        linked = await ctx.resolve_linked_identifiers(others)
        remove = [p for p in extra if p.other(service_id) in linked]
    return Plan(
        add=sorted(desired - current), remove=remove, unlinked=unlinked
    )


async def apply(client: httpx.AsyncClient, changes: Plan) -> None:
    """Associate and disassociate the dependencies in ``changes``."""
    if changes.add:
        response = await client.post(
            '/service_dependencies/associate',
            json={'relationships': [p.as_relationship() for p in changes.add]},
        )
        response.raise_for_status()
    if changes.remove:
        response = await client.post(
            '/service_dependencies/disassociate',
            json={
                'relationships': [p.as_relationship() for p in changes.remove]
            },
        )
        response.raise_for_status()
