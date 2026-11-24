"""The custom fields of tickets, which ``Ticket`` blueprints define.

A ``Ticket`` blueprint applies to a ticket when its filter matches the
type, the priority, and the labels of the ticket. Its properties are
the custom fields of the ticket. A create must give each required
field that has no default; a ``PATCH`` checks only the fields that it
sends. A value whose field stops matching stays in the row.
"""

import typing
from collections import abc

from imbi.api import blueprint_attributes, blueprint_sections, blueprint_values
from imbi.common import blueprints, graph, models


async def all_blueprints(db: graph.Graph) -> list[models.Blueprint]:
    """Return the enabled ``Ticket`` blueprints, by priority."""
    return await db.match(
        models.Blueprint,
        {'type': 'Ticket', 'enabled': True},
        order_by='priority',
    )


async def matched(
    db: graph.Graph, type: str, priority: str, labels: abc.Sequence[str]
) -> list[models.Blueprint]:
    """Return the enabled ``Ticket`` blueprints that match a ticket,
    by priority."""
    return await blueprints.matching_blueprints(
        db,
        'Ticket',
        {'ticket_type': type, 'priority': priority, 'label': list(labels)},
    )


async def for_new(
    db: graph.Graph,
    type: str,
    priority: str,
    labels: abc.Sequence[str],
    values: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    """Return the clean custom fields of a new ticket, with the defaults
    of the blueprints that match it, or raise 422 (see
    :func:`blueprint_values.validate`)."""
    return blueprint_values.validate(
        await matched(db, type, priority, labels), values, partial=False
    )


async def declared_values(
    db: graph.Graph,
    type: str,
    priority: str,
    labels: abc.Sequence[str],
    values: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    """Return the values whose keys the blueprints that match a ticket
    declare now. A hidden value (no matching blueprint declares its
    key) is dropped, so a copy of the values does not fail the check."""
    keys = {
        name
        for bp in await matched(db, type, priority, labels)
        for name in bp.json_schema.properties or {}
    }
    return {k: v for k, v in values.items() if k in keys}


async def filterable(
    db: graph.Graph,
) -> dict[str, blueprint_attributes.FilterableAttribute]:
    """Return the custom fields of every ``Ticket`` blueprint that the
    list can filter on."""
    return blueprint_attributes.resolve(await all_blueprints(db), None)


def sections(
    matches: list[models.Blueprint],
) -> list[blueprint_sections.BlueprintSection]:
    """Return the schema sections of the blueprints."""
    return [
        section
        for bp in matches
        if (section := blueprint_sections.build_section(bp, 'ticket'))
    ]
