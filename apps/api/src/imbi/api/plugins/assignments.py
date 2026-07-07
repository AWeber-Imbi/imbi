"""Effective capability bindings, the default-all rule, and helpers.

This is the one place the ``USES {capability}`` graph model is read for
resolution. A capability is bound to a project through:

* a project-level ``(:Project)-[:USES {capability}]->(:Integration)`` edge
  (an explicit override), or
* a project-type-level
  ``(:ProjectType)-[:USES {capability}]->(:Integration)`` edge on one of
  the project's types, or
* the **default-all rule** (spec §4.2): an Integration whose capability is
  enabled but which has *zero* project-type ``USES {capability}`` edges
  anywhere in its organization applies to every project type -- and hence
  every project -- in that org. Any explicit project-type assignment for
  that capability narrows it back to the assigned types.
"""

import json
import typing

from imbi_common import graph

from imbi_api.plugins import parse_options

#: Enumerated capability kinds that participate in ``USES`` assignment.
CapabilityKind = str


class CapabilityBinding(typing.NamedTuple):
    """One Integration bound to a project for a capability kind."""

    integration: dict[str, typing.Any]  # hydrated Integration node props
    source: typing.Literal['project', 'project_type', 'default_all']
    default: bool
    capability_options: dict[str, typing.Any]
    env_payloads: dict[str, dict[str, typing.Any]]
    identity_integration_id: str | None


def hydrate_integration(props: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Decode an Integration node's JSON-string map fields into dicts.

    AGE stores nested maps (``options``, ``capabilities``,
    ``encrypted_credentials``, ``links``, ``identifiers``) as JSON
    strings, and ``Integration`` has a required edge field so the graph
    client reconstructs it with ``model_construct`` (no validators). This
    normalizes those fields back to dicts for callers.
    """
    out = dict(props)
    for field in (
        'options',
        'capabilities',
        'encrypted_credentials',
        'links',
        'identifiers',
    ):
        out[field] = parse_options(props.get(field))
    return out


def capability_state(
    integration: dict[str, typing.Any], kind: str
) -> dict[str, typing.Any]:
    """Return the ``{enabled, options}`` state for ``kind`` on a hydrated
    Integration, defaulting to ``{}`` when the capability is absent."""
    caps: dict[str, typing.Any] = integration.get('capabilities') or {}
    state: typing.Any = caps.get(kind)
    if isinstance(state, dict):
        return typing.cast('dict[str, typing.Any]', state)
    return {}


def capability_enabled(integration: dict[str, typing.Any], kind: str) -> bool:
    """Whether ``kind`` is enabled on a hydrated Integration."""
    return bool(capability_state(integration, kind).get('enabled'))


def merge_env_payloads(
    ptype_raw: typing.Any,
    project_raw: typing.Any,
) -> dict[str, dict[str, typing.Any]]:
    """Two-tier ``env_payloads`` merge (project edge wins per env slug)."""
    merged: dict[str, dict[str, typing.Any]] = {}
    for slug, payload in parse_options(ptype_raw).items():
        if isinstance(payload, dict):
            merged[slug] = typing.cast('dict[str, typing.Any]', payload)
    for slug, payload in parse_options(project_raw).items():
        if isinstance(payload, dict):
            typed = typing.cast('dict[str, typing.Any]', payload)
            merged[slug] = {**merged.get(slug, {}), **typed}
    return merged


def _coerce_id(raw: typing.Any) -> str | None:
    return str(raw) if isinstance(raw, str) and raw else None


_PROJECT_CONTEXT: typing.LiteralString = """
MATCH (proj:Project {{id: {project_id}}})-[:OWNED_BY]->(:Team)
  -[:BELONGS_TO]->(org:Organization)
OPTIONAL MATCH (proj)-[pe:USES]->(pi:Integration)
  WHERE pe.capability = {kind}
OPTIONAL MATCH (proj)-[:TYPE]->(:ProjectType)-[pte:USES]->(pti:Integration)
  WHERE pte.capability = {kind}
WITH org,
  collect(DISTINCT {{id: pi.id, options: pe.options,
    env_payloads: pe.env_payloads, default: pe.default,
    identity_integration_id: pe.identity_integration_id}}) AS proj_edges,
  collect(DISTINCT {{id: pti.id, options: pte.options,
    env_payloads: pte.env_payloads, default: pte.default,
    identity_integration_id: pte.identity_integration_id}}) AS ptype_edges
RETURN org.slug AS org_slug, proj_edges, ptype_edges
"""

_ORG_INTEGRATIONS: typing.LiteralString = """
MATCH (i:Integration)-[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
RETURN i
"""

_ASSIGNED_TYPE_IDS: typing.LiteralString = """
MATCH (:ProjectType)-[e:USES]->(i:Integration)-[:BELONGS_TO]->
  (:Organization {{slug: {org_slug}}})
WHERE e.capability = {kind}
RETURN collect(DISTINCT i.id) AS ids
"""


async def effective_bindings(
    db: graph.Graph,
    project_id: str,
    kind: str,
) -> list[CapabilityBinding]:
    """Return every Integration bound to ``project_id`` for ``kind``.

    Applies the default-all rule and filters to Integrations whose
    ``capabilities[kind].enabled`` is true. Registry / registration
    filtering is left to :mod:`imbi_api.plugins.resolution`.

    Raises:
        LookupError: the project does not exist.
    """
    records = await db.execute(
        _PROJECT_CONTEXT,
        {'project_id': project_id, 'kind': kind},
        ['org_slug', 'proj_edges', 'ptype_edges'],
    )
    if not records:
        raise LookupError(project_id)
    org_slug = graph.parse_agtype(records[0]['org_slug'])
    if not org_slug:
        raise LookupError(project_id)

    proj_edges = _edges_by_id(records[0]['proj_edges'])
    ptype_edges = _edges_by_id(records[0]['ptype_edges'])

    integrations = await _org_integrations(db, str(org_slug))
    assigned_ids = await _assigned_type_ids(db, str(org_slug), kind)

    bindings: list[CapabilityBinding] = []
    for iid, integration in integrations.items():
        if not capability_enabled(integration, kind):
            continue
        proj_edge = proj_edges.get(iid)
        ptype_edge = ptype_edges.get(iid)
        default_all = iid not in assigned_ids
        if proj_edge is None and ptype_edge is None and not default_all:
            continue

        base_options: typing.Any = capability_state(integration, kind).get(
            'options'
        )
        base: dict[str, typing.Any] = (
            typing.cast('dict[str, typing.Any]', base_options)
            if isinstance(base_options, dict)
            else {}
        )
        capability_options: dict[str, typing.Any] = {
            **base,
            **parse_options((ptype_edge or {}).get('options')),
            **parse_options((proj_edge or {}).get('options')),
        }
        env_payloads = merge_env_payloads(
            (ptype_edge or {}).get('env_payloads'),
            (proj_edge or {}).get('env_payloads'),
        )
        identity_integration_id = _coerce_id(
            (proj_edge or {}).get('identity_integration_id')
        ) or _coerce_id((ptype_edge or {}).get('identity_integration_id'))

        source: typing.Literal['project', 'project_type', 'default_all']
        if proj_edge is not None:
            source = 'project'
            default = bool(proj_edge.get('default'))
        elif ptype_edge is not None:
            source = 'project_type'
            default = bool(ptype_edge.get('default'))
        else:
            source = 'default_all'
            default = False

        bindings.append(
            CapabilityBinding(
                integration=integration,
                source=source,
                default=default,
                capability_options=capability_options,
                env_payloads=env_payloads,
                identity_integration_id=identity_integration_id,
            )
        )
    return bindings


def _edges_by_id(raw: typing.Any) -> dict[str, dict[str, typing.Any]]:
    rows: list[dict[str, typing.Any]] = graph.parse_agtype(raw) or []
    out: dict[str, dict[str, typing.Any]] = {}
    for row in rows:
        iid = row.get('id')
        if iid:
            out[str(iid)] = row
    return out


async def _org_integrations(
    db: graph.Graph, org_slug: str
) -> dict[str, dict[str, typing.Any]]:
    records = await db.execute(
        _ORG_INTEGRATIONS, {'org_slug': org_slug}, ['i']
    )
    out: dict[str, dict[str, typing.Any]] = {}
    for record in records:
        raw: typing.Any = graph.parse_agtype(record['i'])
        if not isinstance(raw, dict):
            continue
        props = typing.cast('dict[str, typing.Any]', raw)
        if props.get('id'):
            out[str(props['id'])] = hydrate_integration(props)
    return out


async def _assigned_type_ids(
    db: graph.Graph, org_slug: str, kind: str
) -> set[str]:
    records = await db.execute(
        _ASSIGNED_TYPE_IDS, {'org_slug': org_slug, 'kind': kind}, ['ids']
    )
    if not records:
        return set()
    ids: list[typing.Any] = graph.parse_agtype(records[0]['ids']) or []
    return {str(i) for i in ids if i}


def encode_options(options: dict[str, typing.Any]) -> str:
    """JSON-encode an options dict for storage on a ``USES`` edge."""
    return json.dumps(options or {})
