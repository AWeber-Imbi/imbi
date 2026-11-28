"""Move the global AI model catalog into the organizations (ADR 0018).

Before 2.66, ``AIProvider`` and ``AIModel`` nodes were global. Now each
one belongs to one organization. :func:`migrate` copies each global
provider (with its encrypted key, hint, and timestamps) and each global
model to every organization, as new nodes with new ids, then deletes
the global nodes. A copy of a model keeps only the ``ALLOWED_FOR``
edges to the teams of its organization. Only the copy in the
organization of a workload identity keeps it: each other organization
sets up its own. Slugs do not change.

The ``ai-catalog-org-copy`` maintenance operation runs it, in one
transaction under an advisory lock, so two runs do not copy twice.
When no global node is left, it does nothing. With no organization, it
keeps the global nodes.
"""

import json
import logging
import typing

import nanoid

from imbi.api.graph_sql import props_template
from imbi.common import graph

LOGGER = logging.getLogger(__name__)

_LOCK = 'imbi.api.ai_catalog_orgs'

_ORGS_QUERY: typing.LiteralString = """
MATCH (o:Organization)
RETURN o.id AS id
"""

_GLOBAL_PROVIDERS_QUERY: typing.LiteralString = """
MATCH (p:AIProvider)
WHERE p.org_id IS NULL
RETURN p
"""

_GLOBAL_MODELS_QUERY: typing.LiteralString = """
MATCH (m:AIModel)
WHERE m.org_id IS NULL
OPTIONAL MATCH (m)-[:SERVED_BY]->(p:AIProvider)
RETURN m, p.id AS provider_id
"""

_MODEL_TEAMS_QUERY: typing.LiteralString = """
MATCH (:AIModel {{id: {id}}})-[:ALLOWED_FOR]->(t:Team)
      -[:BELONGS_TO]->(o:Organization)
RETURN t.id AS team_id, o.id AS org_id
"""

_ADD_TEAM_QUERY: typing.LiteralString = """
MATCH (m:AIModel {{id: {id}}})
MATCH (t:Team {{id: {team_id}}})
CREATE (m)-[:ALLOWED_FOR]->(t)
RETURN t.id AS id
"""

_DELETE_GLOBAL_MODELS_QUERY: typing.LiteralString = """
MATCH (m:AIModel)
WHERE m.org_id IS NULL
DETACH DELETE m
"""

_DELETE_GLOBAL_PROVIDERS_QUERY: typing.LiteralString = """
MATCH (p:AIProvider)
WHERE p.org_id IS NULL
DETACH DELETE p
"""


def _value(record: dict[str, typing.Any], key: str) -> typing.Any:
    return graph.parse_agtype(record[key])


async def migrate(db: graph.Graph) -> int:
    """Copy the global AI catalog to every organization.

    Returns:
        The number of global nodes that were replaced.

    """
    return await db.locked(_LOCK, _copy)


async def _copy(execute: graph.CypherExecute) -> int:
    providers = [
        _value(r, 'p')
        for r in await execute(_GLOBAL_PROVIDERS_QUERY, {}, ['p'])
    ]
    found = await execute(_GLOBAL_MODELS_QUERY, {}, ['m', 'provider_id'])
    if not providers and not found:
        return 0
    org_ids = [
        str(_value(r, 'id')) for r in await execute(_ORGS_QUERY, {}, ['id'])
    ]
    if not org_ids:
        LOGGER.warning(
            'No organization exists; the global AI catalog stays global'
        )
        return 0

    # (global provider id, org id) -> id of the copy
    copies: dict[tuple[str, str], str] = {}
    for props in providers:
        for org_id in org_ids:
            copies[props['id'], org_id] = await _create(
                execute, 'AIProvider', _identity_in(props, org_id), org_id
            )
    for record in found:
        props = _value(record, 'm')
        provider_id = _value(record, 'provider_id')
        if not provider_id:
            LOGGER.warning(
                'AI model %s has no provider; it is not copied', props['id']
            )
            continue
        teams = await execute(
            _MODEL_TEAMS_QUERY, {'id': props['id']}, ['team_id', 'org_id']
        )
        for org_id in org_ids:
            model_id = await _create(
                execute,
                'AIModel',
                props,
                org_id,
                copies[str(provider_id), org_id],
            )
            for team in teams:
                if str(_value(team, 'org_id')) == org_id:
                    await execute(
                        _ADD_TEAM_QUERY,
                        {'id': model_id, 'team_id': _value(team, 'team_id')},
                        ['id'],
                    )
    await execute(_DELETE_GLOBAL_MODELS_QUERY, {})
    await execute(_DELETE_GLOBAL_PROVIDERS_QUERY, {})
    total = len(providers) + len(found)
    LOGGER.info(
        'Copied %d global AI providers and models to %d organizations',
        total,
        len(org_ids),
    )
    return total


def _identity_in(
    props: dict[str, typing.Any], org_id: str
) -> dict[str, typing.Any]:
    """Keep a workload identity only on the copy in its organization."""
    raw = props.get('workload_identity')
    if not raw:
        return props
    wif = json.loads(raw) if isinstance(raw, str) else raw
    if wif.get('organization_id') == org_id:
        return props
    return {**props, 'workload_identity': None}


async def _create(
    execute: graph.CypherExecute,
    label: typing.Literal['AIModel', 'AIProvider'],
    props: dict[str, typing.Any],
    org_id: str,
    provider_id: str | None = None,
) -> str:
    """Create a copy of a global node in the organization ``org_id``.

    A model copy is served by ``provider_id``, the copy of its provider.
    """
    new_id = nanoid.generate()
    copy = {**props, 'id': new_id, 'org_id': org_id}
    served_by: typing.LiteralString = (
        ''
        if provider_id is None
        else (
            ' WITH n, o MATCH (p:AIProvider {{id: {provider_id}}})'
            ' CREATE (n)-[:SERVED_BY]->(p)'
        )
    )
    query: typing.LiteralString = (
        'MATCH (o:Organization {{id: {org_id}}})'
        f' CREATE (n:{label} {props_template(copy)})'
        ' CREATE (n)-[:BELONGS_TO]->(o)'
        f'{served_by}'
        ' RETURN n.id AS id'
    )
    await execute(query, {**copy, 'provider_id': provider_id}, ['id'])
    return new_id
