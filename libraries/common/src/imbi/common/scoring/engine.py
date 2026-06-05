"""High-level entry point for computing a project's score."""

from __future__ import annotations

import json
import typing

import pydantic

from imbi_common import graph, models
from imbi_common.scoring import attribute, policies
from imbi_common.scoring.models import (
    AnalysisResultPolicy,
    DeploymentStatusPolicy,
    ScoreBreakdown,
)


async def compute_score(
    database: graph.Graph,
    project_id: str,
) -> tuple[float | None, ScoreBreakdown]:
    """Compute the floored score and breakdown for *project_id*.

    Returns ``(None, empty_breakdown)`` when no scoring policies apply to the
    project — the caller should clear any existing score rather than writing a
    new one.
    """
    matches = await database.match(models.Project, {'id': project_id})
    if not matches:
        raise ValueError(f'project {project_id!r} not found')
    project = matches[0]
    return await _compute(database, project)


async def _compute(
    database: graph.Graph,
    project: models.Project,
) -> tuple[float | None, ScoreBreakdown]:
    applicable, extended_cls = await policies.applicable_policies(
        database, project
    )
    if not applicable:
        return None, ScoreBreakdown(base_score=0.0, unfloored_total=0.0)
    # Reload with the extended model so blueprint attribute values are present.
    # db.match(models.Project) uses extra='ignore', silently dropping them.
    extended_matches = await database.match(extended_cls, {'id': project.id})
    if not extended_matches and extended_cls is not models.Project:
        raise ValueError(
            f'project {project.id!r} could not be reloaded as '
            f'{extended_cls.__name__}'
        )
    extended_project = extended_matches[0] if extended_matches else project
    analysis_results: dict[str, str] = {}
    if any(isinstance(p, AnalysisResultPolicy) for p in applicable):
        analysis_results = await _load_analysis_results(database, project.id)
    deployment_statuses: dict[str, str] = {}
    if any(isinstance(p, DeploymentStatusPolicy) for p in applicable):
        deployment_statuses = await _load_deployment_statuses(
            database, project.id
        )
    base_score, contributions = attribute.compute_base_score(
        extended_project, applicable, analysis_results, deployment_statuses
    )
    floored = max(0.0, base_score)
    breakdown = ScoreBreakdown(
        base_score=base_score,
        unfloored_total=base_score,
        attribute_contributions=contributions,
    )
    return floored, breakdown


_ANALYSIS_RESULTS_QUERY: typing.LiteralString = (
    'MATCH (p:Project {{id: {project_id}}})'
    '-[:HAS_ANALYSIS_REPORT]->(:AnalysisReport)'
    '-[:HAS_RESULT]->(r:AnalysisResult)'
    ' RETURN r.slug AS slug, r.status AS status'
)


async def _load_analysis_results(
    database: graph.Graph,
    project_id: str,
) -> dict[str, str]:
    """Fetch the project's latest ``{result_slug: status}`` map.

    Returns an empty dict when no analysis report exists. The Doctor
    feature keeps only the latest report per project, so this is a
    single-pass read with no ordering needed.
    """
    rows = await database.execute(
        _ANALYSIS_RESULTS_QUERY,
        {'project_id': project_id},
        columns=['slug', 'status'],
    )
    out: dict[str, str] = {}
    for row in rows:
        slug = graph.parse_agtype(row['slug'])
        status = graph.parse_agtype(row['status'])
        if isinstance(slug, str) and isinstance(status, str):
            out[slug] = status
    return out


_DEPLOYMENT_STATUS_QUERY: typing.LiteralString = (
    'MATCH (p:Project {{id: {project_id}}})'
    '-[:HAS_RELEASE]->(:Release)'
    '-[d:DEPLOYED_TO]->(e:Environment)'
    ' RETURN e.slug AS slug, d.deployments AS deployments'
)


async def _load_deployment_statuses(
    database: graph.Graph,
    project_id: str,
) -> dict[str, str]:
    """Fetch ``{environment_slug: latest_status}`` for *project_id*.

    For each environment the status is taken from the
    ``DeploymentEvent`` with the latest ``timestamp`` across every
    release the project has deployed there — the same "current per
    environment" derivation the release-train endpoint uses.
    Environments with no parseable events are omitted and scored through
    the policy's ``'missing'`` key.
    """
    rows = await database.execute(
        _DEPLOYMENT_STATUS_QUERY,
        {'project_id': project_id},
        columns=['slug', 'deployments'],
    )
    latest: dict[str, models.DeploymentEvent] = {}
    for row in rows:
        slug = graph.parse_agtype(row['slug'])
        if not isinstance(slug, str):
            continue
        for event in _parse_deployment_events(row['deployments']):
            current = latest.get(slug)
            if current is None or event.timestamp > current.timestamp:
                latest[slug] = event
    return {slug: event.status for slug, event in latest.items()}


def _parse_deployment_events(
    raw: typing.Any,
) -> list[models.DeploymentEvent]:
    """Parse a ``d.deployments`` agtype value into events, tolerantly.

    AGE round-trips the list as a JSON string; malformed entries are
    skipped rather than failing the whole score computation.
    """
    parsed: typing.Any = graph.parse_agtype(raw)
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError:
            return []
    if not isinstance(parsed, list):
        return []
    events: list[models.DeploymentEvent] = []
    for item in parsed:  # pyright: ignore[reportUnknownVariableType]
        try:
            events.append(models.DeploymentEvent.model_validate(item))
        except pydantic.ValidationError:
            continue
    return events
