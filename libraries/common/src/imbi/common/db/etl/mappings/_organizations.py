"""Values that more than one mapping needs: the tenant and organization ids.

The module name starts with ``_``, so discovery does not load it as a
mapping.
"""

import datetime

from imbi.common.db.etl import graph, ids, mapping


def tenant_id(context: mapping.Context) -> str:
    """Return the id of the one tenant (Appendix E, E2)."""
    return ids.derive_id('tenants', context.tenant_slug)


async def created_at(
    context: mapping.Context,
) -> dict[str, datetime.datetime]:
    """Return the ``created_at`` of each organization, by id (E40).

    See :func:`known_created_at`. An organization with no time at all
    takes ``--missing-timestamp``, or stops the ETL without it.

    """
    known = await known_created_at(context)
    result: dict[str, datetime.datetime] = {}
    for org_id, value in known.items():
        result[org_id] = graph.created_at(
            {}, context, value, what=f'Organization {org_id!r}'
        )
    return result


async def known_created_at(
    context: mapping.Context,
) -> dict[str, datetime.datetime | None]:
    """Return the E40 ``created_at`` of each organization, or ``None``.

    An organization with no ``created_at`` and no ``updated_at`` (the
    seeded one) takes the oldest ``created_at`` of its teams, of the
    projects of its teams, and of its memberships (the ``MEMBER_OF``
    edge, or the member ``User``). ``None`` when none of these exists.

    """
    conn, name = context.source, context.graph
    team_orgs = await graph.edge_targets(
        conn, name, 'BELONGS_TO', start_label='Team', end_label='Organization'
    )
    project_teams = await graph.edge_targets(
        conn, name, 'OWNED_BY', start_label='Project', end_label='Team'
    )
    related: dict[str, list[datetime.datetime]] = {}

    def add(org_id: str, *values: object) -> None:
        for value in values:
            parsed = graph.timestamp(value)
            if parsed is not None:
                related.setdefault(org_id, []).append(parsed)

    async for team in graph.read_label(conn, name, 'Team'):
        for org_id in team_orgs.get(team.id, ()):
            add(
                org_id,
                team.properties.get('created_at'),
                team.properties.get('updated_at'),
            )
    async for project in graph.read_label(conn, name, 'Project'):
        for team_id in project_teams.get(project.id, ()):
            for org_id in team_orgs.get(team_id, ()):
                add(
                    org_id,
                    project.properties.get('created_at'),
                    project.properties.get('updated_at'),
                )
    async for edge in graph.read_edges(
        conn, name, 'MEMBER_OF', start_label='User', end_label='Organization'
    ):
        add(
            edge.end.id,
            edge.properties.get('created_at'),
            edge.start.properties.get('created_at'),
            edge.start.properties.get('updated_at'),
        )

    result: dict[str, datetime.datetime | None] = {}
    async for org in graph.read_label(conn, name, 'Organization'):
        own = graph.timestamp(org.properties.get('created_at')) or (
            graph.timestamp(org.properties.get('updated_at'))
        )
        oldest = min(related[org.id]) if org.id in related else None
        result[org.id] = own or oldest
    return result
