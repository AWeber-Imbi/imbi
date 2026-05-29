"""Project Doctor — analysis report endpoints.

Project Doctor surfaces a per-project ``AnalysisReport`` made up of
``AnalysisResult`` items emitted by every applicable analysis plugin.
The endpoints below let the UI fetch the latest persisted report and
re-run analysis on demand.  Plugin discovery is delegated to
:func:`imbi_api.plugins.resolution.resolve_analysis_plugins` so it
covers project / project-type ``USES_PLUGIN`` edges plus
``ThirdPartyService`` ``HAS_PLUGIN`` edges via ``EXISTS_IN``.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import typing

import fastapi
import nanoid
import pydantic
from imbi_common import graph
from imbi_common.plugins.base import (
    AnalysisPlugin,
    AnalysisResultItem,
    PluginContext,
)
from imbi_common.plugins.errors import PluginCredentialsMissing

from imbi_api.auth import permissions
from imbi_api.endpoints._helpers import (
    lookup_project_links,
    lookup_project_slugs,
    lookup_project_type_slugs,
)
from imbi_api.plugins import call_with_timeout
from imbi_api.plugins.credentials import get_plugin_credentials
from imbi_api.plugins.resolution import (
    ResolvedPlugin,
    resolve_analysis_plugins,
)

LOGGER = logging.getLogger(__name__)

project_analysis_router = fastapi.APIRouter(tags=['Project: Doctor'])


AnalysisResultStatus = typing.Literal['pass', 'warn', 'fail']

#: Status ordering used to compute an :class:`AnalysisReport`'s overall
#: status — the *worst* observed result wins.
_STATUS_RANK: dict[str, int] = {'pass': 0, 'warn': 1, 'fail': 2}


class AnalysisResult(pydantic.BaseModel):
    """A single finding belonging to an :class:`AnalysisReport`."""

    slug: str
    title: str
    description: str
    status: AnalysisResultStatus
    plugin_slug: str
    plugin_id: str


class AnalysisReport(pydantic.BaseModel):
    """The latest analysis report for a project."""

    id: str
    project_id: str
    created_at: datetime.datetime
    overall_status: AnalysisResultStatus
    triggered_by_user_id: str | None = None
    results: list[AnalysisResult]


def _handler(resolved: ResolvedPlugin) -> AnalysisPlugin:
    """Instantiate and type-narrow an analysis plugin handler."""
    return typing.cast('AnalysisPlugin', resolved.entry.handler_cls())


async def _build_context(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
    resolved: ResolvedPlugin,
) -> PluginContext:
    project_slug, team_slug = await lookup_project_slugs(db, project_id)
    project_links = await lookup_project_links(db, project_id)
    project_type_slugs = await lookup_project_type_slugs(db, project_id)
    return PluginContext(
        project_id=project_id,
        project_slug=project_slug,
        org_slug=org_slug,
        team_slug=team_slug,
        assignment_options=resolved.options,
        project_links=project_links,
        project_type_slugs=project_type_slugs,
    )


async def _credentials_for(
    db: graph.Graph, resolved: ResolvedPlugin
) -> dict[str, str]:
    """Return decrypted credentials for ``resolved`` or ``{}`` when absent.

    Unlike the deployment path, analysis plugins are allowed to run
    without credentials — many of them inspect public project metadata
    only. Missing credentials therefore surface as an empty dict
    instead of an HTTP error.
    """
    try:
        return await get_plugin_credentials(
            db, resolved.plugin_id, resolved.entry
        )
    except PluginCredentialsMissing:
        return {}


async def _run_one(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
    resolved: ResolvedPlugin,
) -> list[AnalysisResult]:
    """Invoke a single plugin's ``analyze`` and shape the response.

    Plugin exceptions are captured as a synthetic ``fail`` result so
    one misbehaving plugin can't sink the whole report.
    """
    try:
        ctx = await _build_context(db, org_slug, project_id, resolved)
        credentials = await _credentials_for(db, resolved)
        handler = _handler(resolved)
        items: list[AnalysisResultItem] = await call_with_timeout(
            handler.analyze(ctx, credentials)
        )
    except Exception as exc:
        LOGGER.exception(
            'Analysis plugin %r (id=%s) raised',
            resolved.plugin_slug,
            resolved.plugin_id,
        )
        return [
            AnalysisResult(
                slug=f'{resolved.plugin_slug}:plugin-error',
                title=f'{resolved.plugin_slug} analysis failed',
                description=(
                    f'`{type(exc).__name__}`: {exc}\n\n'
                    'See server logs for the full traceback.'
                ),
                status='fail',
                plugin_slug=resolved.plugin_slug,
                plugin_id=resolved.plugin_id,
            )
        ]
    return [
        AnalysisResult(
            slug=item.slug,
            title=item.title,
            description=item.description,
            status=item.status,
            plugin_slug=resolved.plugin_slug,
            plugin_id=resolved.plugin_id,
        )
        for item in items
    ]


def _overall_status(results: list[AnalysisResult]) -> AnalysisResultStatus:
    if not results:
        return 'pass'
    worst = max(_STATUS_RANK.get(r.status, 0) for r in results)
    for status, rank in _STATUS_RANK.items():
        if rank == worst:
            return typing.cast('AnalysisResultStatus', status)
    return 'pass'


_DELETE_REPORT_QUERY: typing.LiteralString = """
MATCH (p:Project {{id: {project_id}}})
      -[:HAS_ANALYSIS_REPORT]->(r:AnalysisReport)
OPTIONAL MATCH (r)-[:HAS_RESULT]->(res:AnalysisResult)
DETACH DELETE res, r
"""

_CREATE_REPORT_QUERY: typing.LiteralString = """
MATCH (p:Project {{id: {project_id}}})
CREATE (p)-[:HAS_ANALYSIS_REPORT]->(r:AnalysisReport {{
  id: {id},
  project_id: {project_id},
  created_at: {created_at},
  overall_status: {overall_status},
  triggered_by_user_id: {triggered_by_user_id}
}})
RETURN r
"""

_CREATE_RESULT_QUERY: typing.LiteralString = """
MATCH (r:AnalysisReport {{id: {report_id}}})
CREATE (r)-[:HAS_RESULT]->(res:AnalysisResult {{
  report_id: {report_id},
  slug: {slug},
  title: {title},
  description: {description},
  status: {status},
  plugin_slug: {plugin_slug},
  plugin_id: {plugin_id}
}})
"""


async def _persist_report(
    db: graph.Graph,
    *,
    project_id: str,
    overall_status: AnalysisResultStatus,
    triggered_by_user_id: str | None,
    results: list[AnalysisResult],
) -> AnalysisReport:
    """Replace the project's existing report and persist a new one."""
    await db.execute(_DELETE_REPORT_QUERY, {'project_id': project_id})
    report_id = nanoid.generate()
    created_at = datetime.datetime.now(datetime.UTC)
    await db.execute(
        _CREATE_REPORT_QUERY,
        {
            'project_id': project_id,
            'id': report_id,
            'created_at': created_at.isoformat(),
            'overall_status': overall_status,
            'triggered_by_user_id': triggered_by_user_id or '',
        },
    )
    for result in results:
        await db.execute(
            _CREATE_RESULT_QUERY,
            {
                'report_id': report_id,
                'slug': result.slug,
                'title': result.title,
                'description': result.description,
                'status': result.status,
                'plugin_slug': result.plugin_slug,
                'plugin_id': result.plugin_id,
            },
        )
    return AnalysisReport(
        id=report_id,
        project_id=project_id,
        created_at=created_at,
        overall_status=overall_status,
        triggered_by_user_id=triggered_by_user_id,
        results=results,
    )


_FETCH_REPORT_QUERY: typing.LiteralString = """
MATCH (p:Project {{id: {project_id}}})
      -[:HAS_ANALYSIS_REPORT]->(r:AnalysisReport)
OPTIONAL MATCH (r)-[:HAS_RESULT]->(res:AnalysisResult)
RETURN r, collect(res) AS results
"""


async def _fetch_report(
    db: graph.Graph,
    project_id: str,
) -> AnalysisReport | None:
    rows = await db.execute(
        _FETCH_REPORT_QUERY, {'project_id': project_id}, ['r', 'results']
    )
    if not rows:
        return None
    report_raw = graph.parse_agtype(rows[0]['r'])
    if not isinstance(report_raw, dict):
        return None
    raw_results = graph.parse_agtype(rows[0]['results']) or []
    results: list[AnalysisResult] = []
    for entry in raw_results:
        if not isinstance(entry, dict):
            continue
        try:
            results.append(AnalysisResult.model_validate(entry))
        except pydantic.ValidationError:
            LOGGER.warning(
                'Skipping malformed AnalysisResult node for project %s',
                project_id,
            )
    results.sort(key=lambda r: (-_STATUS_RANK.get(r.status, 0), r.title))
    created_at_raw = report_raw.get('created_at')
    created_at = (
        datetime.datetime.fromisoformat(created_at_raw)
        if isinstance(created_at_raw, str)
        else datetime.datetime.now(datetime.UTC)
    )
    triggered = report_raw.get('triggered_by_user_id') or None
    overall = report_raw.get('overall_status') or 'pass'
    return AnalysisReport(
        id=str(report_raw.get('id')),
        project_id=project_id,
        created_at=created_at,
        overall_status=typing.cast('AnalysisResultStatus', overall),
        triggered_by_user_id=triggered if isinstance(triggered, str) else None,
        results=results,
    )


@project_analysis_router.get('/', response_model=AnalysisReport)
async def get_project_analysis(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('project:read')),
    ],
) -> AnalysisReport:
    del org_slug
    report = await _fetch_report(db, project_id)
    if report is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail='No analysis report exists for this project',
        )
    return report


@project_analysis_router.post('/run', response_model=AnalysisReport)
async def run_project_analysis(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('project:write')),
    ],
) -> AnalysisReport:
    plugins = await resolve_analysis_plugins(db, project_id)
    if not plugins:
        report = await _persist_report(
            db,
            project_id=project_id,
            overall_status='pass',
            triggered_by_user_id=(auth.user.id if auth.user else None),
            results=[],
        )
        return report
    per_plugin = await asyncio.gather(
        *(_run_one(db, org_slug, project_id, rp) for rp in plugins)
    )
    results: list[AnalysisResult] = []
    for batch in per_plugin:
        results.extend(batch)
    results.sort(key=lambda r: (-_STATUS_RANK.get(r.status, 0), r.title))
    overall = _overall_status(results)
    triggered = auth.user.id if auth.user else None
    return await _persist_report(
        db,
        project_id=project_id,
        overall_status=overall,
        triggered_by_user_id=triggered,
        results=results,
    )
