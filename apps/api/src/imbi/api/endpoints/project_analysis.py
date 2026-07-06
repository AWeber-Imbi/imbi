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
import json
import logging
import typing

import fastapi
import nanoid
import pydantic
from imbi_common import graph
from imbi_common.graph import cypher as graph_cypher
from imbi_common.plugins.base import (
    AnalysisPlugin,
    AnalysisResultItem,
    LinkWriteback,
    PluginContext,
    RemediationOffer,
    RemediationResult,
    ServiceWriteback,
)
from imbi_common.plugins.errors import (
    PluginCredentialsMissing,
    PluginRemediationNotSupported,
)

from imbi_api.auth import permissions
from imbi_api.blueprint_compliance import (
    BLUEPRINT_PLUGIN_ID,
    BLUEPRINT_PLUGIN_SLUG,
    check_blueprint_compliance,
    remediate_blueprint,
)
from imbi_api.endpoints._helpers import (
    lookup_project_exists_in,
    lookup_project_links,
    lookup_project_slugs,
    lookup_project_type_slugs,
    persist_link_writeback,
    persist_service_writeback,
)
from imbi_api.identity import errors as identity_errors
from imbi_api.identity import resolution as identity_resolution
from imbi_api.identity.host_integration import call_with_identity_retry
from imbi_api.plugins import call_with_timeout
from imbi_api.plugins.credentials import get_plugin_credentials
from imbi_api.plugins.resolution import (
    ResolvedPlugin,
    resolve_analysis_plugins,
    resolve_service_plugins,
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
    #: Present when the finding is fixable; drives the Doctor panel's
    #: per-finding "Fix" button.
    remediation: RemediationOffer | None = None


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
    service_connections = await lookup_project_exists_in(db, project_id)
    service_plugins = await resolve_service_plugins(db, project_id)
    return PluginContext(
        project_id=project_id,
        project_slug=project_slug,
        org_slug=org_slug,
        team_slug=team_slug,
        assignment_options=resolved.options,
        project_links=project_links,
        project_type_slugs=project_type_slugs,
        third_party_service_slug=resolved.third_party_service_slug,
        service_connections=service_connections,
        service_plugins=service_plugins,
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


async def _hydrate_identity_optional(
    db: graph.Graph,
    resolved: ResolvedPlugin,
    ctx: PluginContext,
    auth: permissions.AuthContext,
) -> PluginContext:
    """Stamp the actor and best-effort hydrate the user's identity.

    Analysis plugins discovered via a third-party service carry the
    service's sibling identity plugin id, letting the doctor act as the
    connecting user. When the user has not connected that identity we
    silently fall back to the plugin's static credentials rather than
    forcing a hard ``identity_required`` — diagnosis must not depend on
    every user having linked their account.
    """
    actor_user_id = auth.user.id if auth.user else None
    ctx = ctx.model_copy(update={'actor_user_id': actor_user_id})
    if resolved.identity_plugin_id and auth.user:
        try:
            ctx = await identity_resolution.hydrate_identity(
                db, ctx, resolved.identity_plugin_id
            )
        except identity_errors.IdentityRequiredError:
            LOGGER.info(
                'No identity connection for plugin %s / user %s; '
                'falling back to static credentials',
                resolved.identity_plugin_id,
                auth.user.id,
            )
    return ctx


async def _resolve_credentials(
    db: graph.Graph, resolved: ResolvedPlugin, ctx: PluginContext
) -> dict[str, str]:
    """Prefer the acting user's identity token; fall back to static."""
    if ctx.identity and ctx.identity.access_token:
        return {'access_token': ctx.identity.access_token}
    return await _credentials_for(db, resolved)


async def _run_one(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
    resolved: ResolvedPlugin,
    auth: permissions.AuthContext,
) -> list[AnalysisResult]:
    """Invoke a single plugin's ``analyze`` and shape the response.

    Plugin exceptions are captured as a synthetic ``fail`` result so
    one misbehaving plugin can't sink the whole report.
    """
    try:
        ctx = await _build_context(db, org_slug, project_id, resolved)
        ctx = await _hydrate_identity_optional(db, resolved, ctx, auth)
        credentials = await _resolve_credentials(db, resolved, ctx)
        handler = _handler(resolved)
        items: list[AnalysisResultItem] = await call_with_timeout(
            handler.analyze(ctx, credentials)
        )
    except Exception:
        # The traceback (and any URLs / query fragments / credentials
        # the plugin might have embedded in the exception message) is
        # kept in the server log via ``LOGGER.exception``. The body
        # surfaced through the API stays a fixed, sanitised string so
        # a misbehaving plugin can't leak operator-visible secrets
        # into the Doctor panel.
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
                    'The plugin failed while running analysis. '
                    'See server logs for details.'
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
            remediation=item.remediation,
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
  plugin_id: {plugin_id},
  remediation: {remediation}
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
    """Replace the project's existing report and persist a new one.

    Runs the delete + creates as a single database transaction so a
    mid-flight failure can't leave the project with a partial
    report, and two concurrent ``/run`` requests serialise on the
    project rather than interleaving and producing duplicate
    ``HAS_ANALYSIS_REPORT`` edges. Reuses :meth:`graph.Graph._execute_batch`
    — the host-side transactional primitive imbi-common exposes for
    exactly this case.
    """
    report_id = nanoid.generate()
    created_at = datetime.datetime.now(datetime.UTC)
    statements: list[graph_cypher.Statement] = [
        graph_cypher.Statement(
            cypher=_DELETE_REPORT_QUERY,
            params={'project_id': project_id},
        ),
        graph_cypher.Statement(
            cypher=_CREATE_REPORT_QUERY,
            params={
                'project_id': project_id,
                'id': report_id,
                'created_at': created_at.isoformat(),
                'overall_status': overall_status,
                'triggered_by_user_id': triggered_by_user_id or '',
            },
        ),
        *(
            graph_cypher.Statement(
                cypher=_CREATE_RESULT_QUERY,
                params={
                    'report_id': report_id,
                    'slug': result.slug,
                    'title': result.title,
                    'description': result.description,
                    'status': result.status,
                    'plugin_slug': result.plugin_slug,
                    'plugin_id': result.plugin_id,
                    'remediation': (
                        json.dumps(result.remediation.model_dump())
                        if result.remediation
                        else ''
                    ),
                },
            )
            for result in results
        ),
    ]
    # imbi-common exposes ``_execute_batch`` as the host-side
    # transactional primitive (used internally by ``Graph.create`` /
    # ``Graph.merge``). It's single-underscore by convention, not
    # truly private — basedpyright's ``reportPrivateUsage`` rule is
    # noise here.
    await db._execute_batch(statements)  # pyright: ignore[reportPrivateUsage]
    return AnalysisReport(
        id=report_id,
        project_id=project_id,
        created_at=created_at,
        overall_status=overall_status,
        triggered_by_user_id=triggered_by_user_id,
        results=results,
    )


# ``collect(properties(res))`` returns each result as a plain property
# map, not a ``::vertex``-annotated agtype vertex. A ``collect(res)`` of
# raw vertices serialises to an array that ``parse_agtype`` cannot decode
# into a list (it falls back to a string), which silently dropped every
# finding on read — leaving persisted reports looking empty and making
# "Fix all" a no-op even when fixable findings existed.
_FETCH_REPORT_QUERY: typing.LiteralString = """
MATCH (p:Project {{id: {project_id}}})
      -[:HAS_ANALYSIS_REPORT]->(r:AnalysisReport)
OPTIONAL MATCH (r)-[:HAS_RESULT]->(res:AnalysisResult)
RETURN r, collect(properties(res)) AS results
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
    report_parsed = graph.parse_agtype(rows[0]['r'])
    if not isinstance(report_parsed, dict):
        return None
    # ``parse_agtype`` returns ``Any``; pin to a typed dict so the
    # rest of this function reads cleanly under basedpyright strict.
    report_raw: dict[str, typing.Any] = typing.cast(
        'dict[str, typing.Any]', report_parsed
    )
    results_parsed = graph.parse_agtype(rows[0]['results'])
    # mypy sees ``parse_agtype`` as ``Any`` (so ``list`` narrowing is
    # already ``list[Any]``); basedpyright sees ``list[Unknown]`` and
    # demands the explicit ``list[Any]`` cast. The cast keeps strict
    # checks clean; the ``# type: ignore`` keeps mypy quiet.
    raw_results: list[typing.Any] = (
        typing.cast('list[typing.Any]', results_parsed)  # type: ignore[redundant-cast]
        if isinstance(results_parsed, list)
        else []
    )
    results: list[AnalysisResult] = []
    for entry in raw_results:
        if not isinstance(entry, dict):
            continue
        entry_dict: dict[str, typing.Any] = typing.cast(
            'dict[str, typing.Any]', entry
        )
        # ``remediation`` is persisted as a JSON string (or '' when the
        # finding is not fixable); decode it back to a dict the model can
        # validate into a RemediationOffer.
        rem_raw = entry_dict.get('remediation')
        if isinstance(rem_raw, str) and rem_raw:
            try:
                entry_dict['remediation'] = json.loads(rem_raw)
            except json.JSONDecodeError:
                entry_dict['remediation'] = None
        else:
            entry_dict['remediation'] = None
        try:
            results.append(AnalysisResult.model_validate(entry_dict))
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
    triggered_raw = report_raw.get('triggered_by_user_id')
    triggered = (
        triggered_raw
        if isinstance(triggered_raw, str) and triggered_raw
        else None
    )
    overall_raw = report_raw.get('overall_status')
    overall: AnalysisResultStatus = (
        overall_raw if overall_raw in ('pass', 'warn', 'fail') else 'pass'
    )
    return AnalysisReport(
        id=str(report_raw.get('id')),
        project_id=project_id,
        created_at=created_at,
        overall_status=overall,
        triggered_by_user_id=triggered,
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


async def _collect_results(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
    auth: permissions.AuthContext,
) -> list[AnalysisResult]:
    """Run blueprint compliance + every analysis plugin, sorted."""
    type_slugs = await lookup_project_type_slugs(db, project_id)
    compliance_items = await check_blueprint_compliance(
        db, project_id, type_slugs
    )
    results: list[AnalysisResult] = [
        AnalysisResult(
            slug=item.slug,
            title=item.title,
            description=item.description,
            status=item.status,
            plugin_slug=BLUEPRINT_PLUGIN_SLUG,
            plugin_id=BLUEPRINT_PLUGIN_ID,
            remediation=item.remediation,
        )
        for item in compliance_items
    ]
    plugins = await resolve_analysis_plugins(db, project_id)
    per_plugin = await asyncio.gather(
        *(_run_one(db, org_slug, project_id, rp, auth) for rp in plugins)
    )
    for batch in per_plugin:
        results.extend(batch)
    results.sort(key=lambda r: (-_STATUS_RANK.get(r.status, 0), r.title))
    return results


async def _run_and_persist(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
    auth: permissions.AuthContext,
) -> AnalysisReport:
    results = await _collect_results(db, org_slug, project_id, auth)
    triggered = auth.user.id if auth.user else None
    return await _persist_report(
        db,
        project_id=project_id,
        overall_status=_overall_status(results),
        triggered_by_user_id=triggered,
        results=results,
    )


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
    return await _run_and_persist(db, org_slug, project_id, auth)


class RemediateRequest(pydantic.BaseModel):
    """Identify the finding to fix.

    ``remediation_id`` is the offer id the plugin emitted; ``plugin_id``
    routes to the emitting plugin (or ``'built-in'`` for the blueprint
    compliance check). ``finding_slug`` is carried for audit/logging.
    """

    plugin_id: str
    finding_slug: str
    remediation_id: str


class RemediateResponse(pydantic.BaseModel):
    result: RemediationResult
    report: AnalysisReport


class RemediateOutcome(pydantic.BaseModel):
    slug: str
    plugin_id: str
    result: RemediationResult


class RemediateAllResponse(pydantic.BaseModel):
    outcomes: list[RemediateOutcome]
    report: AnalysisReport


async def _remediate_one(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
    plugin_id: str,
    remediation_id: str,
    auth: permissions.AuthContext,
    *,
    plugins: list[ResolvedPlugin] | None = None,
    type_slugs: list[str] | None = None,
) -> RemediationResult:
    """Apply a single finding's remediation, persisting any write-back.

    Routes the built-in blueprint check to its host-side handler;
    everything else calls back into the emitting analysis plugin and
    persists whatever ``ServiceWriteback`` / ``LinkWriteback`` it
    reported, mirroring the lifecycle dispatch write-back capture.

    ``plugins`` / ``type_slugs`` let a batch caller (remediate-all) resolve
    these once and reuse them across findings rather than re-running the
    same graph queries per finding; both are resolved on demand when not
    supplied.
    """
    if plugin_id == BLUEPRINT_PLUGIN_ID:
        if type_slugs is None:
            type_slugs = await lookup_project_type_slugs(db, project_id)
        return await remediate_blueprint(
            db, project_id, type_slugs, remediation_id
        )

    if plugins is None:
        plugins = await resolve_analysis_plugins(db, project_id)
    resolved = next((p for p in plugins if p.plugin_id == plugin_id), None)
    if resolved is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Analysis plugin {plugin_id!r} is not assigned',
        )

    ctx = await _build_context(db, org_slug, project_id, resolved)
    ctx = await _hydrate_identity_optional(db, resolved, ctx, auth)
    handler = _handler(resolved)
    captured_service: list[ServiceWriteback] = []
    captured_link: list[LinkWriteback] = []

    async def _do(c: PluginContext) -> RemediationResult:
        creds = await _resolve_credentials(db, resolved, c)
        res = await call_with_timeout(
            handler.remediate(c, creds, remediation_id)
        )
        if c.service_writeback is not None:
            captured_service.append(c.service_writeback)
        if c.link_writeback is not None:
            captured_link.append(c.link_writeback)
        return res

    try:
        if resolved.identity_plugin_id and ctx.identity:
            result = await call_with_identity_retry(
                db, ctx, resolved, auth, fn=_do, attached=True
            )
        else:
            result = await _do(ctx)
    except PluginRemediationNotSupported as exc:
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                f'Plugin {resolved.plugin_slug!r} does not support '
                f'remediation {remediation_id!r}'
            ),
        ) from exc

    if captured_service:
        await persist_service_writeback(
            db,
            ctx.model_copy(update={'service_writeback': captured_service[-1]}),
        )
    if captured_link:
        await persist_link_writeback(
            db, ctx.model_copy(update={'link_writeback': captured_link[-1]})
        )
    return result


@project_analysis_router.post('/remediate', response_model=RemediateResponse)
async def remediate_project_finding(
    org_slug: str,
    project_id: str,
    body: RemediateRequest,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('project:write')),
    ],
) -> RemediateResponse:
    """Apply one finding's fix, then return the refreshed report."""
    result = await _remediate_one(
        db, org_slug, project_id, body.plugin_id, body.remediation_id, auth
    )
    report = await _run_and_persist(db, org_slug, project_id, auth)
    return RemediateResponse(result=result, report=report)


@project_analysis_router.post(
    '/remediate-all', response_model=RemediateAllResponse
)
async def remediate_all_project_findings(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('project:write')),
    ],
) -> RemediateAllResponse:
    """Apply every fixable finding in the current report (best-effort).

    Each finding is remediated independently; a failure on one is
    captured in its outcome rather than aborting the rest. Analysis is
    re-run once at the end so the returned report reflects every fix.
    """
    report = await _fetch_report(db, project_id)
    if report is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail='No analysis report exists for this project',
        )
    # Resolve plugins and project-type slugs once and reuse them across
    # every finding, rather than re-running these graph queries per
    # finding inside _remediate_one.
    plugins = await resolve_analysis_plugins(db, project_id)
    type_slugs = await lookup_project_type_slugs(db, project_id)
    outcomes: list[RemediateOutcome] = []
    for finding in report.results:
        if finding.remediation is None:
            continue
        try:
            result = await _remediate_one(
                db,
                org_slug,
                project_id,
                finding.plugin_id,
                finding.remediation.id,
                auth,
                plugins=plugins,
                type_slugs=type_slugs,
            )
        except fastapi.HTTPException as exc:
            result = RemediationResult(
                status='failed', message=str(exc.detail)
            )
        except Exception:
            LOGGER.exception(
                'Remediation failed for finding %r (plugin=%s)',
                finding.slug,
                finding.plugin_id,
            )
            result = RemediationResult(
                status='failed',
                message='Remediation failed; see server logs for details.',
            )
        outcomes.append(
            RemediateOutcome(
                slug=finding.slug,
                plugin_id=finding.plugin_id,
                result=result,
            )
        )
    fresh = await _run_and_persist(db, org_slug, project_id, auth)
    return RemediateAllResponse(outcomes=outcomes, report=fresh)
