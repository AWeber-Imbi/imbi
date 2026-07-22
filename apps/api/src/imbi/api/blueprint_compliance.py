"""Blueprint property compliance check for Project Doctor.

Compares a project's current AGE node properties against every
applicable Project blueprint's JSON Schema and emits an
:class:`~imbi_common.plugins.base.AnalysisResultItem` for each
non-conformant property.

This is a *built-in* check — no external plugin or credentials are
required; it queries the graph directly.  The caller is responsible
for wrapping the returned items into :class:`AnalysisResult` objects
(adding ``plugin_slug`` and ``plugin_id``).
"""

from __future__ import annotations

import logging
import re
import typing

from imbi_common import graph, models
from imbi_common.plugins.base import (
    AnalysisResultItem,
    RemediationOffer,
    RemediationResult,
)

from imbi_api.blueprint_attributes import project_blueprints

LOGGER = logging.getLogger(__name__)

BLUEPRINT_PLUGIN_SLUG = 'blueprint-compliance'
BLUEPRINT_PLUGIN_ID = 'built-in'

# Remediation id prefixes round-tripped through ``RemediationOffer.id``;
# the suffix is the property name. ``remediate_blueprint`` dispatches on
# the prefix.
_SET_DEFAULT = 'set-default'
_REMOVE_STALE = 'remove-stale'

_SENTINEL = object()  # distinguishes "not present" from explicit None

# Blueprint property names must be safe to embed in Cypher SET clauses.
# Only allow names that look like identifiers.
_SAFE_PROP_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

_FETCH_PROPS_QUERY = """
MATCH (p:Project {{id: {project_id}}})
RETURN p{{.*}} AS props
"""


async def _fetch_project_props(
    db: graph.Graph, project_id: str
) -> dict[str, typing.Any]:
    rows = await db.execute(
        _FETCH_PROPS_QUERY, {'project_id': project_id}, ['props']
    )
    if not rows:
        return {}
    raw = graph.parse_agtype(rows[0]['props'])
    if not isinstance(raw, dict):
        return {}
    return typing.cast('dict[str, typing.Any]', raw)


def _is_missing(value: typing.Any) -> bool:
    return value is _SENTINEL or value is None or value == ''


def _check_property(
    section_slug: str,
    prop_name: str,
    prop_schema: models.Schema,
    required: bool,
    current_value: typing.Any,
) -> AnalysisResultItem | None:
    """Return a finding for a non-conformant property, or ``None``."""
    display = getattr(prop_schema, 'title', None) or prop_name
    missing = _is_missing(current_value)
    default = getattr(prop_schema, 'default', None)
    set_default_offer = (
        RemediationOffer(
            id=f'{_SET_DEFAULT}:{prop_name}',
            label=f'Set {display} to its blueprint default',
        )
        if default is not None and _SAFE_PROP_RE.match(prop_name)
        else None
    )

    if required and missing:
        hint = (
            'Use the Fix action to set it to the blueprint default.'
            if set_default_offer is not None
            else 'Edit the project to set it.'
        )
        return AnalysisResultItem(
            slug=f'{BLUEPRINT_PLUGIN_SLUG}:{section_slug}:{prop_name}:missing',
            title=f'Required property not set: {display}',
            description=(
                f'`{prop_name}` is required by the **{section_slug}** '
                f'blueprint but has no value. {hint}'
            ),
            status='fail',
            remediation=set_default_offer,
        )

    if not missing:
        enum = getattr(prop_schema, 'enum', None)
        if enum is not None and current_value not in enum:
            choices = ', '.join(f'`{v}`' for v in enum)
            return AnalysisResultItem(
                slug=f'{BLUEPRINT_PLUGIN_SLUG}:{section_slug}:{prop_name}:invalid-enum',
                title=f'Property value not in allowed set: {display}',
                description=(
                    f'`{prop_name}` is `{current_value!r}` but the '
                    f'allowed values are: {choices}. '
                    f'Edit the project to correct it.'
                ),
                status='fail',
            )

        minimum = getattr(prop_schema, 'minimum', None)
        maximum = getattr(prop_schema, 'maximum', None)
        if isinstance(current_value, (int, float)):
            if minimum is not None and current_value < minimum:
                return AnalysisResultItem(
                    slug=f'{BLUEPRINT_PLUGIN_SLUG}:{section_slug}:{prop_name}:below-minimum',
                    title=f'Property below minimum: {display}',
                    description=(
                        f'`{prop_name}` is `{current_value}` but '
                        f'the minimum is `{minimum}`.'
                    ),
                    status='warn',
                )
            if maximum is not None and current_value > maximum:
                return AnalysisResultItem(
                    slug=f'{BLUEPRINT_PLUGIN_SLUG}:{section_slug}:{prop_name}:above-maximum',
                    title=f'Property above maximum: {display}',
                    description=(
                        f'`{prop_name}` is `{current_value}` but '
                        f'the maximum is `{maximum}`.'
                    ),
                    status='warn',
                )

    # Missing but not required — warn when a default is available
    if missing and set_default_offer is not None:
        return AnalysisResultItem(
            slug=f'{BLUEPRINT_PLUGIN_SLUG}:{section_slug}:{prop_name}:use-default',
            title=f'Property not set — default available: {display}',
            description=(
                f'`{prop_name}` has no value. '
                f'The blueprint default is `{default!r}`. '
                f'Use the Fix action to set it.'
            ),
            status='warn',
            remediation=set_default_offer,
        )

    return None


def _stale_blueprint_properties(
    all_blueprints: list[models.Blueprint],
    applicable: list[models.Blueprint],
    current_props: dict[str, typing.Any],
) -> list[str]:
    """Return property names set on the project with no applicable blueprint.

    A property is "stale" when it was set by a blueprint that no longer
    applies to this project's type(s). Only considers properties defined in
    *some* blueprint (so core model fields like ``id`` or ``name`` are never
    flagged).
    """
    all_bp_props: set[str] = set()
    for bp in all_blueprints:
        if bp.kind != 'node':
            continue
        for prop_name in bp.json_schema.properties or {}:
            all_bp_props.add(prop_name)

    applicable_props: set[str] = set()
    for bp in applicable:
        for prop_name in bp.json_schema.properties or {}:
            applicable_props.add(prop_name)

    stale = all_bp_props - applicable_props
    return [
        p for p in stale if not _is_missing(current_props.get(p, _SENTINEL))
    ]


def _applicable_blueprints(
    blueprints: list[models.Blueprint],
    type_slug_set: set[str],
) -> list[models.Blueprint]:
    out: list[models.Blueprint] = []
    for bp in blueprints:
        if bp.kind != 'node':
            continue
        f = bp.filter
        if (
            f is not None
            and f.project_type
            and not type_slug_set.intersection(f.project_type)
        ):
            continue
        if bp.json_schema.properties:
            out.append(bp)
    return out


async def check_blueprint_compliance(
    db: graph.Graph,
    project_id: str,
    type_slugs: list[str],
) -> list[AnalysisResultItem]:
    """Return blueprint compliance findings for a project.

    Loads every enabled Project blueprint, filters to those that apply
    to the project's types, and checks each property against the
    project's current AGE node properties.  Returns a single ``pass``
    item when everything is compliant so the Doctor card always shows
    something for this check.
    """
    all_blueprints = await project_blueprints(db)
    if not all_blueprints:
        return [
            AnalysisResultItem(
                slug=f'{BLUEPRINT_PLUGIN_SLUG}:no-blueprints',
                title='No Project blueprints configured',
                description=(
                    'No enabled Project blueprints are defined. '
                    'Add blueprints to track property compliance.'
                ),
                status='pass',
            )
        ]

    type_slug_set = set(type_slugs)
    applicable = _applicable_blueprints(all_blueprints, type_slug_set)

    props = await _fetch_project_props(db, project_id)
    findings: list[AnalysisResultItem] = []

    for bp in applicable:
        schema = bp.json_schema
        required_names: set[str] = set(schema.required or [])
        section_slug = bp.slug or ''
        for prop_name, prop_schema in (schema.properties or {}).items():
            extra = prop_schema.model_extra or {}
            x_ui = dict(extra.get('x-ui') or {})
            required = (
                prop_name in required_names or x_ui.get('required') is True
            )
            current_value = props.get(prop_name, _SENTINEL)
            finding = _check_property(
                section_slug, prop_name, prop_schema, required, current_value
            )
            if finding is not None:
                findings.append(finding)

    # Detect blueprint-managed properties no longer in any applicable
    # blueprint.
    stale = _stale_blueprint_properties(all_blueprints, applicable, props)
    for prop_name in sorted(stale):
        findings.append(
            AnalysisResultItem(
                slug=f'{BLUEPRINT_PLUGIN_SLUG}:stale:{prop_name}',
                title=f'Property not in any applicable blueprint: {prop_name}',
                description=(
                    f'`{prop_name}` is set on this project but is not defined '
                    f'in any currently applicable blueprint. '
                    f'Use the Fix action to remove it.'
                ),
                status='warn',
                remediation=(
                    RemediationOffer(
                        id=f'{_REMOVE_STALE}:{prop_name}',
                        label=f'Remove {prop_name}',
                        destructive=True,
                    )
                    if _SAFE_PROP_RE.match(prop_name)
                    else None
                ),
            )
        )

    if not findings:
        if not applicable:
            return [
                AnalysisResultItem(
                    slug=f'{BLUEPRINT_PLUGIN_SLUG}:no-applicable',
                    title='No blueprints apply to this project type',
                    description=(
                        "No enabled blueprints match this project's type(s)."
                    ),
                    status='pass',
                )
            ]
        return [
            AnalysisResultItem(
                slug=f'{BLUEPRINT_PLUGIN_SLUG}:all-pass',
                title='All blueprint properties are correctly set',
                description=(
                    'Every required and recommended blueprint property '
                    'has a valid value.'
                ),
                status='pass',
            )
        ]
    return findings


def _blueprint_default(
    applicable: list[models.Blueprint], prop_name: str
) -> typing.Any:
    """Return the blueprint default for ``prop_name`` (later wins), or None."""
    default: typing.Any = None
    for bp in applicable:
        prop_schema = (bp.json_schema.properties or {}).get(prop_name)
        if prop_schema is None:
            continue
        value = getattr(prop_schema, 'default', None)
        if value is not None:
            default = value
    return default


async def remediate_blueprint(
    db: graph.Graph,
    project_id: str,
    type_slugs: list[str],
    remediation_id: str,
) -> RemediationResult:
    """Apply a single blueprint-compliance fix.

    ``remediation_id`` is ``set-default:<prop>`` (set an unset property
    to its blueprint default) or ``remove-stale:<prop>`` (drop a property
    no longer defined by any applicable blueprint). Idempotent: returns a
    ``noop`` when the property is already in the desired state.
    """
    action, _, prop_name = remediation_id.partition(':')
    if not prop_name or not _SAFE_PROP_RE.match(prop_name):
        return RemediationResult(
            status='failed',
            message=f'Invalid blueprint remediation id {remediation_id!r}.',
        )

    props = await _fetch_project_props(db, project_id)

    if action == _REMOVE_STALE:
        if _is_missing(props.get(prop_name, _SENTINEL)):
            return RemediationResult(
                status='noop', message=f'`{prop_name}` is already unset.'
            )
        all_blueprints = await project_blueprints(db)
        applicable = _applicable_blueprints(all_blueprints, set(type_slugs))
        stale = _stale_blueprint_properties(all_blueprints, applicable, props)
        if prop_name not in stale:
            return RemediationResult(
                status='failed',
                message=(
                    f'`{prop_name}` is no longer stale; refusing to remove it.'
                ),
            )
        await db.execute(
            'MATCH (p:Project {{id: {project_id}}}) '
            f'SET p.{prop_name} = null RETURN p.id AS id',
            {'project_id': project_id},
            ['id'],
        )
        LOGGER.info('Removed stale property %r from %s', prop_name, project_id)
        return RemediationResult(
            status='fixed', message=f'Removed `{prop_name}`.'
        )

    if action == _SET_DEFAULT:
        if not _is_missing(props.get(prop_name, _SENTINEL)):
            return RemediationResult(
                status='noop', message=f'`{prop_name}` is already set.'
            )
        all_blueprints = await project_blueprints(db)
        applicable = _applicable_blueprints(all_blueprints, set(type_slugs))
        default = _blueprint_default(applicable, prop_name)
        if default is None:
            return RemediationResult(
                status='failed',
                message=f'No blueprint default available for `{prop_name}`.',
            )
        await db.execute(
            'MATCH (p:Project {{id: {project_id}}}) '
            f'SET p.{prop_name} = {{value}} RETURN p.id AS id',
            {'project_id': project_id, 'value': default},
            ['id'],
        )
        LOGGER.info(
            'Set property %r to its default on %s', prop_name, project_id
        )
        return RemediationResult(
            status='fixed',
            message=f'Set `{prop_name}` to its blueprint default.',
        )

    return RemediationResult(
        status='failed',
        message=f'Unknown blueprint remediation {remediation_id!r}.',
    )
