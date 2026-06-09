"""Project deployment plugin endpoints.

Pass-through endpoints that resolve the project's ``plugin_type='deployment'``
plugin and call its handler methods.  Covers ref / commit discovery,
comparison, ``deploy`` / ``redeploy`` workflow dispatch (Phase 1), and
the ``promote`` flow with AI-drafted release notes plus tag + Release
upsert (Phase 2).

See ``docs/deployments-plan.md`` for the full design.
"""

import asyncio
import datetime
import functools
import importlib.resources
import itertools
import json
import logging
import re
import typing
import urllib.parse

import fastapi
import httpx
import nanoid
import pydantic
from imbi_common import clickhouse, graph, versioning
from imbi_common import models as common_models
from imbi_common.plugins.base import (
    Commit,
    CompareResult,
    DeploymentPlugin,
    DeploymentRun,
    PluginContext,
    Ref,
    RemoteDeployment,
)
from imbi_common.plugins.errors import PluginCredentialsMissing

from imbi_api.auth import permissions
from imbi_api.endpoints._helpers import (
    lookup_project_links,
    lookup_project_slugs,
    lookup_project_type_slugs,
    persist_link_writeback,
)
from imbi_api.endpoints.releases import (
    AppendOutcome,
    ReleaseEnvironmentEdgeResponse,
    append_deployment_event,
)
from imbi_api.identity.host_integration import (
    attach_identity,
    call_with_identity_retry,
)
from imbi_api.llm.dependencies import InjectAnthropicClient
from imbi_api.plugins import call_with_timeout
from imbi_api.plugins.credentials import get_plugin_credentials
from imbi_api.plugins.resolution import ResolvedPlugin, resolve_plugin

LOGGER = logging.getLogger(__name__)

project_deployments_router = fastapi.APIRouter(tags=['Project: Deployments'])


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------


class DeployActionRequest(pydantic.BaseModel):
    """Body for ``POST /deployments`` with ``action='deploy'|'redeploy'``."""

    action: typing.Literal['deploy', 'redeploy']
    environment: str
    committish: str
    ref_label: str | None = None
    inputs: dict[str, str] | None = None


class PromoteActionRequest(pydantic.BaseModel):
    """Body for ``POST /deployments`` with ``action='promote'``.

    Cuts a new tag at ``from_committish`` (the build being promoted),
    creates a release on the remote, then dispatches the workflow with
    the tag as the ref.
    """

    action: typing.Literal['promote']
    from_environment: str
    to_environment: str
    from_committish: str
    tag: str
    release_name: str | None = None
    release_notes_markdown: str = ''
    prerelease: bool = False


DeploymentRequestBody = typing.Annotated[
    DeployActionRequest | PromoteActionRequest,
    pydantic.Field(discriminator='action'),
]


class DeploymentTriggerResponse(pydantic.BaseModel):
    """Response shape for a successful deploy/redeploy/promote action."""

    run: DeploymentRun
    plugin_id: str
    plugin_slug: str
    recorded: bool = False
    release_url: str | None = None
    tag: str | None = None
    # Human-readable narrative for any non-fatal failure encountered
    # while running the per-environment promote steps (e.g. the GitHub
    # Deployments POST returned 422 because the repo's ``on: deployment``
    # workflow isn't wired up yet).  The promote itself still records a
    # DeploymentEvent; the UI surfaces this as an amber inline note.
    warning: str | None = None


class DraftReleaseNotesRequest(pydantic.BaseModel):
    """Body for ``POST /deployments/draft-release-notes``."""

    base_sha: str
    head_sha: str
    last_tag: str | None = None


SemverBump = typing.Literal['major', 'minor', 'patch']


class DraftReleaseNotes(pydantic.BaseModel):
    """The structured payload Claude returns for a release-notes draft."""

    bump: SemverBump
    version: str
    reasoning: str
    notes_markdown: str


class DraftReleaseNotesResponse(pydantic.BaseModel):
    """Response shape for the release-notes drafting endpoint."""

    bump: SemverBump
    version: str
    reasoning: str
    notes_markdown: str
    degraded: bool = False
    commits_considered: int = 0


class ResyncProjectError(pydantic.BaseModel):
    """One non-fatal failure encountered during a resync."""

    project_id: str | None = None
    environment: str | None = None
    detail: str


class ResyncSummary(pydantic.BaseModel):
    """Aggregate counts returned by a resync run.

    ``observed`` is the number of remote deployments the plugin returned;
    ``releases_created`` / ``releases_updated`` count distinct
    ``Release`` nodes affected; ``events_recorded`` counts the
    ``DeploymentEvent`` rows actually appended (dedupe-suppressed rows
    do not count); ``events_skipped`` counts rows the dedupe path
    short-circuited.
    """

    projects: int = 0
    observed: int = 0
    releases_created: int = 0
    releases_updated: int = 0
    events_recorded: int = 0
    events_skipped: int = 0
    errors: list[ResyncProjectError] = []


class PromotionOption(pydantic.BaseModel):
    """One promotion gap for the popover.

    Pairs a from-env (whose current SHA we'd promote) with a to-env
    (the target).  ``commits_pending`` is the size of the
    ``from..to`` compare; ``None`` means we couldn't ask the plugin
    (e.g. no current release on either side).
    """

    from_environment: str
    to_environment: str
    from_version: str | None = None
    to_version: str | None = None
    from_sha: str | None = None
    to_sha: str | None = None
    commits_pending: int | None = None


class RecentCommit(pydantic.BaseModel):
    """A commit row read from the ClickHouse ``commits`` table.

    Powers the Releases-tab commit picker / drift list.  ``ci_status``
    is the rolled-up check state captured at sync time (``'unknown'``
    when not yet hydrated).  The table carries no PR number, so none is
    surfaced here.
    """

    sha: str
    short_sha: str
    message: str
    author: str | None = None
    authored_at: datetime.datetime
    ci_status: str = 'unknown'
    url: str | None = None


class ReleaseDriftResponse(pydantic.BaseModel):
    """Commits awaiting a release: the delta between the latest tag and HEAD.

    Computed entirely from the ClickHouse ``commits`` / ``tags`` tables.
    ``commits`` is newest-first and capped; ``commits_since_tag`` is the
    exact count (uncapped).  ``suggested_tag`` / ``suggested_bump`` are a
    cheap conventional-commit heuristic the UI can override.
    """

    latest_tag: str | None = None
    latest_tag_sha: str | None = None
    latest_tag_at: datetime.datetime | None = None
    head_sha: str | None = None
    commits_since_tag: int = 0
    commits: list[RecentCommit] = []
    suggested_bump: SemverBump = 'patch'
    suggested_tag: str = 'v0.1.0'


class ReleaseHistoryEntry(pydantic.BaseModel):
    """One published release: a ClickHouse tag joined to its Release node."""

    tag: str
    sha: str
    short_sha: str
    published_at: datetime.datetime | None = None
    author: str | None = None
    ci_status: str = 'unknown'
    title: str | None = None
    notes_markdown: str | None = None
    release_url: str | None = None
    tag_url: str | None = None
    package_url: str | None = None


class ReleaseCutRequest(pydantic.BaseModel):
    """Body for ``POST /deployments/releases/cut``.

    Cuts a git tag + GitHub release at ``committish`` with no deployment
    step -- the build-and-release-only (library / image) flow.
    """

    committish: str
    tag: str
    release_name: str | None = None
    release_notes_markdown: str = ''
    prerelease: bool = False


class ReleaseCutResponse(pydantic.BaseModel):
    """Response shape for a successful ``releases/cut`` action."""

    tag: str
    release_url: str | None = None
    committish: str
    recorded: bool = False
    warning: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _latest_deployment_timestamp(
    raw: typing.Any,
) -> datetime.datetime | None:
    """Return the most recent deployment-event timestamp, or ``None``.

    The ``deployments`` edge property is stored as a JSON-encoded list
    of ``DeploymentEvent``-shaped objects.  We parse just the timestamp
    field here so the promotion-options reducer can deterministically
    rank ``(Release, Environment)`` rows by recency without paying for
    full Pydantic validation.
    """
    if not raw:
        return None
    data = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(data, list):
        return None
    latest: datetime.datetime | None = None
    for entry in data:  # type: ignore[reportUnknownVariableType]
        if not isinstance(entry, dict):
            continue
        ts = entry.get('timestamp')  # type: ignore[reportUnknownMemberType]
        if not isinstance(ts, str):
            continue
        try:
            parsed = datetime.datetime.fromisoformat(ts)
        except ValueError:
            continue
        if latest is None or parsed > latest:
            latest = parsed
    return latest


async def _resolve_and_context(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
    auth: permissions.AuthContext,
    *,
    source: str | None = None,
    environment: str | None = None,
) -> tuple[ResolvedPlugin, PluginContext, dict[str, str]]:
    """Common boilerplate: resolve plugin, attach identity, build creds."""
    resolved = await resolve_plugin(db, project_id, 'deployment', source)
    project_slug, team_slug = await lookup_project_slugs(db, project_id)
    project_links = await lookup_project_links(db, project_id)
    project_type_slugs = await lookup_project_type_slugs(db, project_id)
    # Per-env payload pulled off the USES_PLUGIN edge (plan: release-train
    # env flags).  The env_payloads dict is keyed by env slug and the
    # value is shallow-merged into GitHub Deployment ``payload`` (workflow
    # inputs) at trigger time.  Empty dict when there is no env in scope
    # or no per-env payload is configured -- plugin authors should treat
    # absent keys as "no extra inputs".
    environment_config: dict[str, typing.Any] = {}
    if environment and resolved.env_payloads:
        environment_config = dict(resolved.env_payloads.get(environment, {}))
    ctx = PluginContext(
        project_id=project_id,
        project_slug=project_slug,
        org_slug=org_slug,
        team_slug=team_slug,
        environment=environment,
        assignment_options=resolved.options,
        environment_config=environment_config,
        project_links=project_links,
        project_type_slugs=project_type_slugs,
    )
    ctx = await attach_identity(db, ctx, resolved, auth)

    if ctx.identity and ctx.identity.access_token:
        credentials: dict[str, str] = {
            'access_token': ctx.identity.access_token,
        }
    else:
        try:
            credentials = await get_plugin_credentials(
                db, resolved.plugin_id, resolved.entry
            )
        except PluginCredentialsMissing as exc:
            raise fastapi.HTTPException(
                status_code=503,
                detail=str(exc),
            ) from exc
        if not credentials.get('access_token') and not credentials.get(
            'token'
        ):
            raise fastapi.HTTPException(
                status_code=503,
                detail=(
                    'No deployment credentials available: bind an '
                    'identity or configure a service-account token.'
                ),
            )
    return resolved, ctx, credentials


class _EnvFlags(typing.NamedTuple):
    """Release-train flags resolved from an ``Environment`` node.

    ``found`` is ``False`` when the environment slug doesn't match any
    node in the graph; callers raise 404 in that case rather than
    accidentally treating the env as deploy-and-promote-disabled.
    """

    found: bool
    can_deploy: bool
    can_promote: bool


async def _load_env_flags(
    db: graph.Graph,
    *,
    org_slug: str,
    env_slug: str,
) -> _EnvFlags:
    """Fetch ``can_deploy`` / ``can_promote`` for one env slug.

    Scoped to the organization so multi-org data with overlapping
    environment slugs (e.g. ``prod`` in two orgs) never reads flags
    from the wrong org.

    Defaults conservative-but-permissive when the stored node predates
    the env-flag migration: ``can_deploy=True`` (no surprise lockouts)
    and ``can_promote=False`` (opt-in, matching the model default).
    """
    query: typing.LiteralString = """
    MATCH (e:Environment {{slug: {env_slug}}})
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    RETURN e.can_deploy AS can_deploy, e.can_promote AS can_promote
    """
    rows = await db.execute(
        query,
        {'env_slug': env_slug, 'org_slug': org_slug},
        ['can_deploy', 'can_promote'],
    )
    if not rows:
        return _EnvFlags(found=False, can_deploy=True, can_promote=False)
    can_deploy = graph.parse_agtype(rows[0].get('can_deploy'))
    can_promote = graph.parse_agtype(rows[0].get('can_promote'))
    return _EnvFlags(
        found=True,
        can_deploy=True if can_deploy is None else bool(can_deploy),
        can_promote=False if can_promote is None else bool(can_promote),
    )


def _is_already_exists_error(exc: BaseException) -> bool:
    """Return True when exc is a GitHub 422 'Reference already exists'."""
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    if exc.response.status_code != 422:
        return False
    try:
        msg = (exc.response.json().get('message') or '').lower()
        return 'already exists' in msg
    except Exception:  # noqa: BLE001
        return False


def _promote_warning(step: str, exc: BaseException) -> str:
    """Sanitized client-facing warning for a failed promote step.

    Keeps the step name and the exception class for actionability
    (e.g., ``RuntimeError``, ``ClientResponseError``) but withholds
    the raw exception message, which can carry plugin internals.
    Full detail is preserved in logs via ``LOGGER.exception``.
    """
    return f'{step} failed ({type(exc).__name__}); see server logs.'


def _handler(resolved: ResolvedPlugin) -> DeploymentPlugin:
    """Instantiate and type-narrow the plugin handler."""
    return typing.cast(DeploymentPlugin, resolved.entry.handler_cls())


def _resolve_credentials(
    ctx: PluginContext, fallback: dict[str, str]
) -> dict[str, str]:
    """Pick the deployment-call credentials for ``ctx``.

    Prefers the per-user identity's bearer token (so the API call is
    attributed to the human and refreshes apply) and falls back to the
    service-account PAT bound to the plugin instance.  Recomputed
    inside :func:`call_with_identity_retry`'s closure so a refreshed
    identity surfaces the new access token on retry.
    """
    if ctx.identity is not None and ctx.identity.access_token:
        return {'access_token': ctx.identity.access_token}
    return fallback


_SAFE_AUDIT_URL_SCHEMES: frozenset[str] = frozenset({'http', 'https'})


def _safe_audit_url(value: str | None) -> str | None:
    """Drop plugin-supplied URLs that aren't plain http(s).

    Both ``run_url`` and ``release_url`` are surfaced by deployment
    plugins and rendered as ``<a href>`` in the operations-log UI.
    A malicious or buggy plugin could return a ``javascript:`` or
    ``data:`` URL that, if echoed verbatim into the DOM, would land
    as XSS. The UI already escapes attribute values, but defense in
    depth: drop anything that isn't ``http(s)://`` server-side so
    every consumer of the audit row sees a known-safe scheme.
    """
    if value is None:
        return None
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme.lower() not in _SAFE_AUDIT_URL_SCHEMES:
        LOGGER.warning(
            'Dropping audit URL with unsupported scheme %r', parsed.scheme
        )
        return None
    return value


async def _record_deployment_audit(
    *,
    project_id: str,
    project_slug: str,
    environment_slug: str,
    recorded_by: str,
    action: str,
    tag: str | None,
    committish: str,
    plugin_slug: str,
    run_url: str | None,
    external_run_id: str | None = None,
    release_url: str | None = None,
    from_environment: str | None = None,
) -> None:
    """Write a deployment audit row to the ``operations_log``.

    Mirrors the configuration audit pattern in
    ``project_configuration._record_configuration_event`` so the
    project's history pane surfaces deploys/promotes the same way
    it surfaces config changes.  Audit failures intentionally
    propagate so a bad write never silently desyncs the log.

    ``OperationLog.version`` is populated with ``tag if tag else
    committish`` — a single human-friendly display string that the
    operations-log UI can render directly.

    Plugin-supplied URLs (``run_url`` / ``release_url``) are filtered
    through ``_safe_audit_url`` so non-http(s) schemes never reach the
    audit JSON — see L22.
    """
    safe_run_url = _safe_audit_url(run_url)
    safe_release_url = _safe_audit_url(release_url)
    description = json.dumps(
        {
            'action': action,
            'plugin_slug': plugin_slug,
            'run_url': safe_run_url,
            'release_url': safe_release_url,
            'from_environment': from_environment,
        },
        sort_keys=True,
    )
    entry = common_models.OperationLog(
        id=nanoid.generate(),
        recorded_at=datetime.datetime.now(datetime.UTC),
        recorded_by=recorded_by,
        performed_by=recorded_by,
        project_id=project_id,
        project_slug=project_slug,
        environment_slug=environment_slug,
        entry_type='Deployed',
        description=description,
        link=safe_run_url,
        version=tag or committish,
        plugin_slug=plugin_slug,
        external_run_id=external_run_id,
    )
    row = entry.model_dump(by_alias=True, mode='python')
    row['is_deleted'] = 1 if entry.is_deleted else 0
    await clickhouse.client.Clickhouse.get_instance().insert(
        'operations_log',
        [list(row.values())],
        list(row.keys()),
    )


# ---------------------------------------------------------------------------
# Resync helpers
# ---------------------------------------------------------------------------


_SEMVER_REF_RE = re.compile(r'^v?\d+\.\d+\.\d+(?:[-+].*)?$')


def _resync_release_identity(
    observed: RemoteDeployment,
) -> tuple[str | None, str]:
    """Pick ``(tag, committish)`` to record for an observed deployment.

    Mirrors the CEL expression the gateway uses on
    ``imbi_gateway.actions.create_release``: semver-shaped ``ref``
    becomes the tag; the committish is always the first 7 chars of
    the commit SHA. Keeping the rules aligned means a project whose
    webhooks recover later produces the same ``(tag, committish)``
    pair the gateway would have created, so deduplication stays
    consistent.
    """
    tag: str | None = None
    if observed.ref and _SEMVER_REF_RE.match(observed.ref):
        tag = observed.ref
    return tag, observed.sha[:7].lower()


async def _load_resync_environments(
    db: graph.Graph,
    *,
    project_id: str,
) -> list[str]:
    """Return the environment slugs the project is wired up to deploy to.

    Source of truth is the project's ``DEPLOYED_IN`` edges (the same
    ones the promotion-options endpoint walks).  Order by ``sort_order``
    so the plugin sees the project's preferred order when it fans out.
    """
    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})-[:DEPLOYED_IN]->(e:Environment)
    RETURN e.slug AS slug, e.sort_order AS sort_order
    """
    rows = await db.execute(
        query,
        {'project_id': project_id},
        ['slug', 'sort_order'],
    )

    def _order(row: dict[str, typing.Any]) -> tuple[int, str]:
        order = graph.parse_agtype(row.get('sort_order'))
        slug = str(graph.parse_agtype(row.get('slug')) or '')
        # ``sort_order`` is nullable on Environment; rows missing it
        # sort after the ones that do, then break ties on slug so the
        # ordering is deterministic even with NULLs.
        order_int = int(order) if isinstance(order, int | float) else 1_000_000
        return order_int, slug

    return [
        str(graph.parse_agtype(row.get('slug')))
        for row in sorted(rows, key=_order)
        if graph.parse_agtype(row.get('slug'))
    ]


async def _release_id_for(
    db: graph.Graph,
    *,
    project_id: str,
    committish: str,
    tag: str | None,
) -> str | None:
    """Return the ``Release.id`` matching ``(project, committish, tag)``.

    Acts as both an existence probe and a lookup for the release-id
    the caller needs to pass to ``append_deployment_event`` and the
    deployment-audit writer. AGE doesn't expose NULL equality, so
    tag-matching is COALESCEd through a sentinel.
    """
    # Fetch all matching ids so a duplicate ``(committish, tag)`` row
    # is visible in the logs instead of being silently masked by
    # ``LIMIT 1`` — the schema doesn't enforce uniqueness on this pair
    # and a stuck retry path is exactly how we'd accumulate dupes.
    query: typing.LiteralString = """
    MATCH (:Project {{id: {project_id}}})
        -[:HAS_RELEASE]->(r:Release {{committish: {committish}}})
    WHERE COALESCE(r.tag, '') = COALESCE({tag}, '')
    RETURN r.id AS rid
    """
    rows = await db.execute(
        query,
        {
            'project_id': project_id,
            'committish': committish,
            'tag': tag,
        },
        ['rid'],
    )
    if not rows:
        return None
    if len(rows) > 1:
        LOGGER.warning(
            'Multiple Release nodes for project=%s committish=%s tag=%r; '
            'using the first',
            project_id,
            committish,
            tag,
        )
    rid = graph.parse_agtype(rows[0].get('rid'))
    return str(rid) if rid else None


async def resync_for_project(
    db: graph.Graph,
    *,
    org_slug: str,
    project_id: str,
    auth: permissions.AuthContext,
    source: str | None = None,
) -> ResyncSummary:
    """Resync remote deployments for a single project.

    Resolves the project's deployment plugin, asks it for the most
    recent deployment per environment, upserts ``Release`` nodes for
    any observed versions that are missing, appends ``DeploymentEvent``
    rows on the ``DEPLOYED_TO`` edge (dedup'd by ``external_run_id``),
    and writes a single audit row per environment.  Returns counts +
    a per-environment error list so the host can surface partial
    results rather than failing the whole call on one bad env.
    """
    summary = ResyncSummary(projects=1)
    resolved, ctx, credentials = await _resolve_and_context(
        db, org_slug, project_id, auth, source=source
    )
    if not getattr(resolved.entry.manifest, 'supports_deployment_sync', False):
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                f'Plugin {resolved.plugin_slug!r} does not support '
                'deployment resync.'
            ),
        )
    environments = await _load_resync_environments(db, project_id=project_id)
    if not environments:
        return summary
    handler = _handler(resolved)

    async def _fetch(c: PluginContext) -> list[RemoteDeployment]:
        return await call_with_timeout(
            handler.list_recent_deployments(
                c,
                _resolve_credentials(c, credentials),
                environments=environments,
                limit=1,
            )
        )

    try:
        observations = await call_with_identity_retry(
            db, ctx, resolved, auth, fn=_fetch, attached=True
        )
    except NotImplementedError as exc:
        # Manifest advertised sync but the implementation didn't.
        # Surface as a 400 so the operator notices rather than logging
        # silently and reporting an empty resync.
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                f'Plugin {resolved.plugin_slug!r} advertises '
                'supports_deployment_sync but did not implement '
                'list_recent_deployments.'
            ),
        ) from exc
    await persist_link_writeback(db, ctx)
    summary.observed = len(observations)
    # Track identities we've already touched so ``releases_created`` /
    # ``releases_updated`` are counted once per distinct
    # ``(committish, tag)`` pair -- the same tag promoted across
    # multiple environments is one Release node, not N.
    seen_identities: set[tuple[str, str | None]] = set()
    for observed in observations:
        try:
            await _apply_remote_deployment(
                db,
                org_slug=org_slug,
                project_id=project_id,
                plugin_slug=resolved.plugin_slug,
                recorded_by=auth.principal_name,
                observed=observed,
                summary=summary,
                seen_identities=seen_identities,
            )
        except Exception as exc:
            LOGGER.exception(
                'Resync apply failed for project=%s env=%s',
                project_id,
                observed.environment,
            )
            # Keep the full traceback in logs (above) but only return
            # the exception class to clients so plugin internals and
            # database error text aren't leaked through the API.
            summary.errors.append(
                ResyncProjectError(
                    project_id=project_id,
                    environment=observed.environment,
                    detail=(
                        f'Resync apply failed ({type(exc).__name__}); '
                        'see server logs.'
                    ),
                )
            )
    return summary


async def _apply_remote_deployment(
    db: graph.Graph,
    *,
    org_slug: str,
    project_id: str,
    plugin_slug: str,
    recorded_by: str,
    observed: RemoteDeployment,
    summary: ResyncSummary,
    seen_identities: set[tuple[str, str | None]],
) -> None:
    """Persist one observed remote deployment.

    Writes the ``Release`` node + ``DeploymentEvent`` on the
    ``DEPLOYED_TO`` edge.  No ``operations_log`` audit row is written
    here -- resync backfills historical activity, and attributing it to
    the resync operator poisons ``argMax(performed_by, occurred_at)``
    queries.  The edge's ``DeploymentEvent.performed_by`` carries the
    original deployer when the plugin can resolve one.

    ``seen_identities`` is mutated to track which
    ``(committish, tag)`` pairs have already been counted against
    ``releases_created`` / ``releases_updated`` during this resync,
    so a tag promoted across multiple environments is counted as one
    Release node, not N.
    """
    tag, committish = _resync_release_identity(observed)
    title = observed.description or observed.ref or tag or committish
    identity = (committish, tag)
    first_time_this_resync = identity not in seen_identities
    existed = (
        await _release_id_for(
            db,
            project_id=project_id,
            committish=committish,
            tag=tag,
        )
        is not None
    )
    release_id = await _upsert_release_node(
        db,
        project_id=project_id,
        tag=tag,
        committish=committish,
        title=title,
        notes_markdown=observed.description or '',
        release_url=observed.deployment_url,
        created_by=recorded_by,
    )
    if first_time_this_resync:
        seen_identities.add(identity)
        if existed:
            summary.releases_updated += 1
        else:
            summary.releases_created += 1
    result = await append_deployment_event(
        db,
        org_slug=org_slug,
        project_id=project_id,
        release_id=release_id,
        env_slug=observed.environment,
        status=observed.status,
        note=f'resync via {plugin_slug}',
        external_run_id=observed.external_run_id,
        external_run_url=observed.run_url,
        timestamp=observed.created_at,
        performed_by=observed.creator,
    )
    if result is None:
        # Either the Release upsert didn't take or the env slug isn't
        # wired up in this org -- record as an error so the operator
        # has a thread to pull rather than a silently swallowed row.
        summary.errors.append(
            ResyncProjectError(
                project_id=project_id,
                environment=observed.environment,
                detail=(
                    f'Could not attach DeploymentEvent for release '
                    f'{release_id!r} (committish={committish!r} '
                    f'tag={tag!r}) -- release or environment not '
                    f'found.'
                ),
            )
        )
        return
    _edge, outcome = result
    # Outcome comes straight from ``append_deployment_event``: a real
    # write (``appended`` / ``updated``) bumps ``events_recorded``; a
    # ``noop`` (dedupe matched an identical row) bumps
    # ``events_skipped`` so a replay against an idle remote doesn't
    # masquerade as fresh activity.
    if outcome == 'noop':
        summary.events_skipped += 1
    else:
        summary.events_recorded += 1
    # Intentionally no operations_log audit row here: resync backfills
    # historical remote deployments, so attributing them to the resync
    # operator poisons ``argMax(performed_by, occurred_at)`` lookups
    # (e.g. the "Current Deployments" column on /projects). The
    # ``DEPLOYED_TO`` edge already carries the original creator via
    # ``DeploymentEvent.performed_by``; in-product deploy/promote
    # actions still get their own audit row written by their handlers.


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@project_deployments_router.get('/refs')
async def list_refs(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:deployment:read'),
        ),
    ],
    kind: typing.Literal['default', 'branch', 'tag', 'all'] = 'all',
    q: str | None = None,
    source: str | None = None,
) -> list[Ref]:
    """List branches, tags, or the default ref for the project's repo."""
    resolved, ctx, credentials = await _resolve_and_context(
        db, org_slug, project_id, auth, source=source
    )
    handler = _handler(resolved)
    refs = await call_with_timeout(
        handler.list_refs(ctx, credentials, kind=kind, query=q)
    )
    await persist_link_writeback(db, ctx)
    return refs


@project_deployments_router.get('/refs/{ref:path}/commits')
async def list_commits(
    org_slug: str,
    project_id: str,
    ref: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:deployment:read'),
        ),
    ],
    limit: int = 25,
    source: str | None = None,
) -> list[Commit]:
    """List recent commits on a branch / tag / SHA."""
    resolved, ctx, credentials = await _resolve_and_context(
        db, org_slug, project_id, auth, source=source
    )
    handler = _handler(resolved)
    commits = await call_with_timeout(
        handler.list_commits(ctx, credentials, ref=ref, limit=limit)
    )
    await persist_link_writeback(db, ctx)
    return commits


@project_deployments_router.get('/commits/{committish}')
async def resolve_commit(
    org_slug: str,
    project_id: str,
    committish: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:deployment:read'),
        ),
    ],
    source: str | None = None,
) -> Commit:
    """Resolve a SHA / branch / tag / ``refs/pull/N/head``."""
    resolved, ctx, credentials = await _resolve_and_context(
        db, org_slug, project_id, auth, source=source
    )
    handler = _handler(resolved)
    commit = await call_with_timeout(
        handler.resolve_committish(ctx, credentials, committish)
    )
    await persist_link_writeback(db, ctx)
    return commit


@project_deployments_router.get('/compare')
async def compare_refs(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:deployment:read'),
        ),
    ],
    base: str = fastapi.Query(...),
    head: str = fastapi.Query(...),
    source: str | None = None,
) -> CompareResult:
    """Compare two refs (``base..head``)."""
    resolved, ctx, credentials = await _resolve_and_context(
        db, org_slug, project_id, auth, source=source
    )
    handler = _handler(resolved)
    result = await call_with_timeout(
        handler.compare(ctx, credentials, base=base, head=head)
    )
    await persist_link_writeback(db, ctx)
    return result


@project_deployments_router.post('', status_code=202)
async def trigger_deployment(
    org_slug: str,
    project_id: str,
    body: DeploymentRequestBody,
    background: fastapi.BackgroundTasks,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:deployment:write'),
        ),
    ],
    source: str | None = None,
) -> DeploymentTriggerResponse:
    """Trigger a deploy / redeploy / promote.

    For ``deploy`` / ``redeploy``, dispatches the workflow with the
    chosen committish; if the committish (or its ``ref_label``) matches
    an existing ``Release`` version on the project, also appends a
    ``DeploymentEvent`` to the ``DEPLOYED_TO`` edge.

    For ``promote``: cuts a tag at ``from_committish``, creates a
    release with the supplied notes on the remote, dispatches the
    workflow against the tag for ``to_environment``, upserts the
    matching ``Release`` node, and records the deployment event.
    """
    if body.action == 'promote':
        return await _handle_promote(
            db,
            org_slug,
            project_id,
            auth,
            body,
            background=background,
            source=source,
        )
    return await _handle_deploy(
        db,
        org_slug,
        project_id,
        auth,
        body,
        background=background,
        source=source,
    )


@project_deployments_router.post('/resync')
async def resync_project_deployments(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:deployment:write'),
        ),
    ],
    source: str | None = None,
) -> ResyncSummary:
    """Backfill Release nodes + DEPLOYED_TO edges from the remote.

    Asks the project's deployment plugin for the most recent
    deployment per environment, upserts any missing ``Release`` nodes,
    and dedup-appends ``DeploymentEvent`` rows so the badges advance
    even when the gateway webhook flow has lapsed.  Records one
    audit row per environment with ``action='resync'``.

    Surfaces 400 when the project's deployment plugin does not
    advertise ``supports_deployment_sync`` -- callers should hide the
    button using the plugin manifest flag.
    """
    return await resync_for_project(
        db,
        org_slug=org_slug,
        project_id=project_id,
        auth=auth,
        source=source,
    )


@project_deployments_router.get('/runs/{run_id}')
async def get_deployment_run(
    org_slug: str,
    project_id: str,
    run_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:deployment:read'),
        ),
    ],
    source: str | None = None,
) -> DeploymentRun:
    """Fetch live status for an in-flight deployment workflow run.

    Pass-through to plugin ``get_deployment_status``.  Used by the UI's
    TanStack Query ``refetchInterval`` hook to flip
    ``in_progress → success / failed`` without a page reload.
    """
    resolved, ctx, credentials = await _resolve_and_context(
        db, org_slug, project_id, auth, source=source
    )
    handler = _handler(resolved)
    try:
        return await call_with_timeout(
            handler.get_deployment_status(ctx, credentials, run_id=run_id)
        )
    except NotImplementedError as exc:
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                f'Plugin {resolved.plugin_slug!r} does not report '
                'deployment status.'
            ),
        ) from exc


async def _handle_deploy(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
    auth: permissions.AuthContext,
    body: DeployActionRequest,
    *,
    background: fastapi.BackgroundTasks,
    source: str | None,
) -> DeploymentTriggerResponse:
    env_flags = await _load_env_flags(
        db,
        org_slug=org_slug,
        env_slug=body.environment,
    )
    if not env_flags.found:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Environment {body.environment!r} not found',
        )
    if not env_flags.can_deploy:
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                f'Environment {body.environment!r} has can_deploy=false; '
                'direct deploys are disabled.  Use promote, or enable '
                "this env's can_deploy flag."
            ),
        )
    resolved, ctx, credentials = await _resolve_and_context(
        db,
        org_slug,
        project_id,
        auth,
        source=source,
        environment=body.environment,
    )
    handler = _handler(resolved)

    # Merge env_payloads (from USES_PLUGIN edge) under the caller's
    # explicit ``body.inputs`` so a manual input override always wins.
    # Coerce to strings: the plugin interface (``trigger_deployment``)
    # types ``inputs`` as ``dict[str, str]`` because GitHub's workflow
    # ``inputs`` map only accepts strings.  env_payloads carry richer
    # JSON-shaped values per the plan; we stringify scalars here and
    # JSON-encode anything else so they still round-trip into the
    # workflow.
    merged_inputs: dict[str, str] | None
    if ctx.environment_config or body.inputs:
        merged_inputs = {
            key: value if isinstance(value, str) else json.dumps(value)
            for key, value in ctx.environment_config.items()
        }
        if body.inputs:
            merged_inputs.update(body.inputs)
    else:
        merged_inputs = None

    ref = body.ref_label or body.committish

    async def _trigger(c: PluginContext) -> DeploymentRun:
        return await call_with_timeout(
            handler.trigger_deployment(
                c,
                _resolve_credentials(c, credentials),
                ref_or_sha=ref,
                inputs=merged_inputs,
            )
        )

    run = await call_with_identity_retry(
        db, ctx, resolved, auth, fn=_trigger, attached=True
    )
    await persist_link_writeback(db, ctx)
    LOGGER.info(
        'Deployment triggered: project=%s env=%s ref=%s plugin=%s '
        'action=%s actor=%s run_id=%s',
        project_id,
        body.environment,
        ref,
        resolved.plugin_slug,
        body.action,
        ctx.actor_user_id,
        run.run_id,
    )
    note = f'via {resolved.plugin_slug}'
    committish_short = body.committish[:7].lower()
    candidate_tag = (
        body.ref_label
        if body.ref_label and _SEMVER_REF_RE.match(body.ref_label)
        else None
    )
    # Look up the release that was deployed. Try (committish, tag) first
    # so a SHA that ships under a tag matches the tagged Release node;
    # fall back to (committish, None) so a raw-SHA deploy still finds
    # an untagged Release if one exists.
    result: tuple[ReleaseEnvironmentEdgeResponse, AppendOutcome] | None = None
    matched_tag: str | None = None
    for try_tag in [candidate_tag, None] if candidate_tag else [None]:
        release_id = await _release_id_for(
            db,
            project_id=project_id,
            committish=committish_short,
            tag=try_tag,
        )
        if release_id is None:
            continue
        result = await append_deployment_event(
            db,
            org_slug=org_slug,
            project_id=project_id,
            release_id=release_id,
            env_slug=body.environment,
            status='in_progress',
            note=note,
            external_run_id=str(run.run_id) if run.run_id else None,
            external_run_url=run.run_url,
        )
        if result is not None:
            matched_tag = try_tag
            break
    if result is None:
        LOGGER.warning(
            'Deploy triggered for project=%s committish=%s tag=%s but no'
            ' matching Release node was found; audit row suppressed',
            project_id,
            committish_short,
            candidate_tag,
        )
    else:
        # H13: defer the operations_log ClickHouse insert until after
        # the response goes out. The graph write that establishes the
        # DeploymentEvent already succeeded; the audit row only feeds
        # the activity history and can lag by milliseconds.
        background.add_task(
            _record_deployment_audit,
            project_id=project_id,
            project_slug=ctx.project_slug,
            environment_slug=body.environment,
            recorded_by=auth.principal_name,
            action=body.action,
            tag=matched_tag,
            committish=committish_short,
            plugin_slug=resolved.plugin_slug,
            run_url=run.run_url,
            external_run_id=str(run.run_id) if run.run_id else None,
        )
    return DeploymentTriggerResponse(
        run=run,
        plugin_id=resolved.plugin_id,
        plugin_slug=resolved.plugin_slug,
        recorded=result is not None,
    )


async def _cut_tag_and_release(
    db: graph.Graph,
    *,
    ctx: PluginContext,
    resolved: ResolvedPlugin,
    handler: DeploymentPlugin,
    credentials: dict[str, str],
    auth: permissions.AuthContext,
    from_committish: str,
    tag: str,
    release_name: str | None,
    release_notes_markdown: str,
    prerelease: bool,
    warnings: list[str],
    project_id: str,
    log_context: str = '',
) -> typing.Any:
    """Cut a git tag + create a release at ``from_committish``.

    The shared core behind both ``promote`` (which then deploys) and the
    library ``releases/cut`` action (which does not).  Failures degrade
    to a warning appended to ``warnings`` rather than raising -- a flaky
    GitHub API shouldn't bury the audit trail.  Returns the
    plugin-returned ReleaseInfo on success (or ``None`` when the plugin
    has no ``create_release``).  ``log_context`` is an opaque label
    (e.g. the target env, or ``'release-cut'``) used only in log lines.
    """
    tag_message = release_name or tag

    async def _create_tag(c: PluginContext) -> typing.Any:
        return await call_with_timeout(
            handler.create_tag(
                c,
                _resolve_credentials(c, credentials),
                sha=from_committish,
                tag=tag,
                message=tag_message,
            )
        )

    try:
        await call_with_identity_retry(
            db, ctx, resolved, auth, fn=_create_tag, attached=True
        )
    except NotImplementedError as exc:
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                f'Plugin {resolved.plugin_slug!r} does not support '
                'creating tags; this action is not available.'
            ),
        ) from exc
    except Exception as exc:
        if _is_already_exists_error(exc):
            LOGGER.debug(
                'create_tag: tag %s already exists for project=%s, continuing',
                tag,
                project_id,
            )
        else:
            LOGGER.exception(
                'create_tag failed for project=%s context=%s tag=%s',
                project_id,
                log_context,
                tag,
            )
            warnings.append(_promote_warning('create_tag', exc))

    async def _create_release(c: PluginContext) -> typing.Any:
        return await call_with_timeout(
            handler.create_release(
                c,
                _resolve_credentials(c, credentials),
                tag=tag,
                name=release_name or tag,
                body_markdown=release_notes_markdown,
                prerelease=prerelease,
            )
        )

    try:
        return await call_with_identity_retry(
            db, ctx, resolved, auth, fn=_create_release, attached=True
        )
    except NotImplementedError:
        LOGGER.info(
            'Plugin %r has no create_release; tag-only',
            resolved.plugin_slug,
        )
        return None
    except Exception as exc:
        if _is_already_exists_error(exc):
            LOGGER.debug(
                'create_release: %s already exists for project=%s',
                tag,
                project_id,
            )
        else:
            LOGGER.exception(
                'create_release failed for project=%s context=%s tag=%s',
                project_id,
                log_context,
                tag,
            )
            warnings.append(_promote_warning('create_release', exc))
        return None


async def _promote_cut_release(
    db: graph.Graph,
    *,
    ctx: PluginContext,
    resolved: ResolvedPlugin,
    handler: DeploymentPlugin,
    credentials: dict[str, str],
    auth: permissions.AuthContext,
    body: PromoteActionRequest,
    warnings: list[str],
    project_id: str,
) -> typing.Any:
    """Cut a tag + create a release for a promote (then the caller deploys).

    Thin wrapper over :func:`_cut_tag_and_release` so ``_handle_promote``
    is unchanged; the repo's ``on: release: [published]`` workflow handles
    the deploy.
    """
    return await _cut_tag_and_release(
        db,
        ctx=ctx,
        resolved=resolved,
        handler=handler,
        credentials=credentials,
        auth=auth,
        from_committish=body.from_committish,
        tag=body.tag,
        release_name=body.release_name,
        release_notes_markdown=body.release_notes_markdown,
        prerelease=body.prerelease,
        warnings=warnings,
        project_id=project_id,
        log_context=body.to_environment,
    )


async def _handle_promote(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
    auth: permissions.AuthContext,
    body: PromoteActionRequest,
    *,
    background: fastapi.BackgroundTasks,
    source: str | None,
) -> DeploymentTriggerResponse:
    env_flags = await _load_env_flags(
        db,
        org_slug=org_slug,
        env_slug=body.to_environment,
    )
    if not env_flags.found:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Environment {body.to_environment!r} not found',
        )
    if not env_flags.can_promote:
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                f'Environment {body.to_environment!r} has '
                'can_promote=false; promotion into this env is disabled.  '
                "Enable the env's can_promote flag to allow promotes."
            ),
        )

    # Infer promote behaviour from the ref shape of ``body.tag``:
    #
    # * Semver-shaped (``1.2.3`` / ``v1.2.3``)  -> already a tag.  Skip
    #   ``create_tag`` + ``create_release``; call ``trigger_deployment``
    #   so the repo's ``on: deployment`` workflow fires.  This is the
    #   "promote to prod from a stage release tag" path.
    # * Git short/full SHA                       -> cut a tag at the SHA,
    #   create a GitHub Release; the repo's ``on: release`` workflow
    #   handles the deploy server-side.  This is the "first promote off
    #   a build commit" path.
    # * Anything else (e.g. ``main``)            -> 400.  We refuse to
    #   silently cut a tag named after a branch; a typo at the API
    #   boundary should fail loudly rather than mint ``refs/tags/main``.
    if not versioning.is_semver_tag(body.tag) and not versioning.is_commitish(
        body.tag
    ):
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                f'Promote target {body.tag!r} is neither a semver tag '
                '(e.g. "v1.2.3") nor a git SHA (7-40 hex chars); refusing '
                'to cut a tag at an ambiguous ref.'
            ),
        )

    resolved, ctx, credentials = await _resolve_and_context(
        db,
        org_slug,
        project_id,
        auth,
        source=source,
        environment=body.to_environment,
    )
    handler = _handler(resolved)

    warnings: list[str] = []
    run = DeploymentRun(run_id='', status='queued')
    release_info = None
    release_url: str | None = None

    release_info = await _promote_cut_release(
        db,
        ctx=ctx,
        resolved=resolved,
        handler=handler,
        credentials=credentials,
        auth=auth,
        body=body,
        warnings=warnings,
        project_id=project_id,
    )
    release_url = (release_info.html_url if release_info else None) or (
        release_info.url if release_info else None
    )

    promote_inputs: dict[str, str] | None
    if ctx.environment_config:
        promote_inputs = {
            key: value if isinstance(value, str) else json.dumps(value)
            for key, value in ctx.environment_config.items()
        }
    else:
        promote_inputs = None

    async def _trigger(c: PluginContext) -> DeploymentRun:
        return await call_with_timeout(
            handler.trigger_deployment(
                c,
                _resolve_credentials(c, credentials),
                ref_or_sha=body.tag,
                inputs=promote_inputs,
            )
        )

    try:
        run = await call_with_identity_retry(
            db, ctx, resolved, auth, fn=_trigger, attached=True
        )
    except Exception as exc:
        LOGGER.exception(
            'trigger_deployment failed for project=%s env=%s tag=%s',
            project_id,
            body.to_environment,
            body.tag,
        )
        if isinstance(exc, httpx.HTTPStatusError):
            LOGGER.error(
                'trigger_deployment HTTP %s response body: %s',
                exc.response.status_code,
                exc.response.text,
            )
        warnings.append(_promote_warning('trigger_deployment', exc))
        return DeploymentTriggerResponse(
            run=run,
            plugin_id=resolved.plugin_id,
            plugin_slug=resolved.plugin_slug,
            recorded=False,
            release_url=release_url,
            tag=body.tag,
            warning='; '.join(warnings) if warnings else None,
        )

    await persist_link_writeback(db, ctx)

    # 4. Upsert the Release node so future deploys of the same tag
    #    can attach a DeploymentEvent.
    promoted_committish = body.from_committish[:7].lower()
    release_id = await _upsert_release_node(
        db,
        project_id=project_id,
        tag=body.tag,
        committish=promoted_committish,
        title=body.release_name or body.tag,
        notes_markdown=body.release_notes_markdown,
        release_url=release_url,
        created_by=auth.principal_name,
    )

    # 5. Record the deployment event.
    note = f'via {resolved.plugin_slug}'
    promote_result = await append_deployment_event(
        db,
        org_slug=org_slug,
        project_id=project_id,
        release_id=release_id,
        env_slug=body.to_environment,
        status='in_progress',
        note=note,
        external_run_id=str(run.run_id) if run.run_id else None,
        external_run_url=run.run_url,
    )

    LOGGER.info(
        'Promotion triggered: project=%s %s→%s tag=%s plugin=%s '
        'actor=%s run_id=%s',
        project_id,
        body.from_environment,
        body.to_environment,
        body.tag,
        resolved.plugin_slug,
        ctx.actor_user_id,
        run.run_id,
    )
    # H13: defer the operations_log ClickHouse insert until after the
    # response goes out (same rationale as the deploy path above).
    background.add_task(
        _record_deployment_audit,
        project_id=project_id,
        project_slug=ctx.project_slug,
        environment_slug=body.to_environment,
        recorded_by=auth.principal_name,
        action='promote',
        tag=body.tag,
        committish=promoted_committish,
        plugin_slug=resolved.plugin_slug,
        run_url=run.run_url,
        external_run_id=str(run.run_id) if run.run_id else None,
        release_url=release_url,
        from_environment=body.from_environment,
    )
    return DeploymentTriggerResponse(
        run=run,
        plugin_id=resolved.plugin_id,
        plugin_slug=resolved.plugin_slug,
        recorded=promote_result is not None,
        release_url=release_url,
        tag=body.tag,
        warning='; '.join(warnings) if warnings else None,
    )


async def _upsert_release_node(
    db: graph.Graph,
    *,
    project_id: str,
    tag: str | None,
    committish: str,
    title: str,
    notes_markdown: str,
    release_url: str | None,
    created_by: str,
) -> str:
    """Create the ``Release`` node if missing, otherwise update notes.

    Identity is ``(project, committish, tag)``: re-promoting the same
    tag from the same SHA is benign and refreshes notes / links;
    re-tagging the same SHA produces a new ``Release`` node.
    Returns the resulting ``Release.id``.
    """
    now = datetime.datetime.now(datetime.UTC).isoformat()
    links_json = (
        json.dumps([{'type': 'github_release', 'url': release_url}])
        if release_url
        else json.dumps([])
    )
    new_id: str = nanoid.generate()
    # Match the exact identity (committish, tag) before deciding to
    # create.  Filtering inside ``OPTIONAL MATCH`` keeps a sibling
    # release with the same committish but a different tag from
    # spawning a duplicate ``(committish, tag)`` row.
    create_query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
    OPTIONAL MATCH (p)-[:HAS_RELEASE]
        ->(existing:Release {{committish: {committish}}})
    WHERE COALESCE(existing.tag, '') = COALESCE({tag}, '')
    WITH p, existing
    WHERE existing IS NULL
    CREATE (p)-[:HAS_RELEASE]->(:Release {{
        id: {id},
        tag: {tag},
        committish: {committish},
        title: {title},
        description: {description},
        links: {links},
        created_by: {created_by},
        created_at: {now},
        updated_at: {now}
    }})
    """
    await db.execute(
        create_query,
        {
            'project_id': project_id,
            'committish': committish,
            'tag': tag,
            'id': new_id,
            'title': title,
            'description': notes_markdown,
            'links': links_json,
            'created_by': created_by,
            'now': now,
        },
        [],
    )
    # Update notes / links on a pre-existing release (idempotent re-run).
    # Match on (committish, tag) — tag matching uses COALESCE so a NULL
    # tag compares equal to a NULL tag (AGE has no NULL equality).
    update_query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
          -[:HAS_RELEASE]->(r:Release {{committish: {committish}}})
    WHERE COALESCE(r.tag, '') = COALESCE({tag}, '')
    SET r.description = {description},
        r.links = {links},
        r.updated_at = {now}
    RETURN r.id AS rid
    """
    rows = await db.execute(
        update_query,
        {
            'project_id': project_id,
            'committish': committish,
            'tag': tag,
            'description': notes_markdown,
            'links': links_json,
            'now': now,
        },
        ['rid'],
    )
    if rows:
        rid = graph.parse_agtype(rows[0].get('rid'))
        if rid:
            return str(rid)
    return new_id


# ---------------------------------------------------------------------------
# Release-notes drafting
# ---------------------------------------------------------------------------

_PROMPT_COMMIT_CAP = 150
_SEMVER_RE = re.compile(r'^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$')


@functools.cache
def _release_notes_system() -> str:
    return (
        importlib.resources.files('imbi_api.prompts')
        .joinpath('release_notes_system.md')
        .read_text(encoding='utf-8')
    )


def _semver_sort_key(name: str) -> tuple[int, int, int] | None:
    """``(major, minor, patch)`` for version ordering; ``None`` if not semver.

    Pre-release / build metadata is ignored for ordering -- good enough to
    pick the newest *released* version and to sort the history list.
    """
    match = _SEMVER_RE.match(name)
    if not match:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return (major, minor, patch)


def _release_tag_order_key(
    name: str, when: typing.Any
) -> tuple[bool, tuple[int, int, int], str]:
    """Sort key ranking the latest *release* first.

    Semver-shaped tags outrank non-semver ones; within those, the highest
    version wins, with the newer timestamp as a tie-break. This deliberately
    ignores tag/commit *timestamps* for the primary ordering so a backported
    or late-synced lower version (e.g. ``v4.1.3`` tagged after ``v7.1.0``)
    can't masquerade as the latest release.
    """
    key = _semver_sort_key(name)
    when_key = when.isoformat() if isinstance(when, datetime.datetime) else ''
    return (key is not None, key or (0, 0, 0), when_key)


def _latest_release_tag(
    rows: list[dict[str, typing.Any]],
) -> dict[str, typing.Any] | None:
    """Pick the latest release tag (highest semver) from ``tags`` rows."""
    if not rows:
        return None
    return max(
        rows,
        key=lambda r: _release_tag_order_key(
            str(r['name']), r.get('tagged_at') or r.get('recorded_at')
        ),
    )


def _bump_semver(last_tag: str | None, bump: SemverBump) -> str:
    """Bump a semver-shaped tag.  Falls back to ``v0.1.0`` when missing."""
    raw = (last_tag or 'v0.0.0').lstrip('v')
    match = _SEMVER_RE.match(raw)
    if not match:
        return 'v0.1.0'
    major, minor, patch = (int(part) for part in match.groups())
    if bump == 'major':
        return f'v{major + 1}.0.0'
    if bump == 'minor':
        return f'v{major}.{minor + 1}.0'
    return f'v{major}.{minor}.{patch + 1}'


def _classify_bump(commits: list[Commit]) -> SemverBump:
    """Crude heuristic used as the fallback when Claude isn't available."""
    breaking = ('breaking', '!:', 'breaking change')
    features = ('feat:', 'feature:')
    for commit in commits:
        msg = commit.message.lower()
        if any(token in msg for token in breaking):
            return 'major'
    for commit in commits:
        msg = commit.message.lower()
        if any(msg.startswith(token) for token in features):
            return 'minor'
    return 'patch'


def _fallback_notes(commits: list[Commit]) -> str:
    """Group commits by conventional-commit prefix as the fallback body."""
    if not commits:
        return '_No commits between the chosen base and head._'
    buckets: dict[str, list[Commit]] = {}
    for commit in commits:
        prefix = commit.message.split(':', 1)[0].lower().strip()
        if not prefix or len(prefix) > 16:
            prefix = 'other'
        buckets.setdefault(prefix, []).append(commit)
    lines: list[str] = []
    for prefix in sorted(buckets):
        lines.append(f'### {prefix}')
        for commit in buckets[prefix]:
            lines.append(f'- {commit.message} ({commit.short_sha})')
        lines.append('')
    return '\n'.join(lines).rstrip()


def _build_release_notes_prompt(
    project_name: str,
    last_tag: str | None,
    base_sha: str,
    head_sha: str,
    commits: list[Commit],
) -> str:
    capped = commits[:_PROMPT_COMMIT_CAP]
    omitted = len(commits) - len(capped)
    body_lines = [
        f'Project: {project_name}',
        f'Previous tag: {last_tag or "(none)"}',
        f'Comparing: {base_sha}..{head_sha}',
        f'Total commits: {len(commits)}'
        + (f' (+{omitted} earlier omitted)' if omitted else ''),
        '',
        'Commits (oldest → newest):',
    ]
    for commit in capped:
        author = commit.author or 'unknown'
        body_lines.append(f'- {commit.short_sha} {commit.message} — {author}')
    body_lines.append('')
    body_lines.append('Return the JSON object described in the system prompt.')
    return '\n'.join(body_lines)


@project_deployments_router.post('/draft-release-notes')
async def draft_release_notes(
    org_slug: str,
    project_id: str,
    body: DraftReleaseNotesRequest,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:deployment:write'),
        ),
    ],
    anthropic: InjectAnthropicClient,
    source: str | None = None,
) -> DraftReleaseNotesResponse:
    """Draft release notes for a tag promotion.

    Calls the project's deployment plugin ``compare(base..head)`` to
    enumerate the commits being promoted, asks Claude for a structured
    ``{bump, version, reasoning, notes_markdown}`` payload, and returns
    it.  Falls back to a deterministic conventional-commit-prefix
    grouping with ``degraded=true`` when Claude is unavailable, the
    response can't be parsed, or schema validation fails.
    """
    resolved, ctx, credentials = await _resolve_and_context(
        db, org_slug, project_id, auth, source=source
    )
    handler = _handler(resolved)
    compare_result = await call_with_timeout(
        handler.compare(
            ctx, credentials, base=body.base_sha, head=body.head_sha
        )
    )
    commits = compare_result.commits
    fallback_bump = _classify_bump(commits)
    fallback = DraftReleaseNotes(
        bump=fallback_bump,
        version=_bump_semver(body.last_tag, fallback_bump),
        reasoning=(
            'AI unavailable — bump and notes derived from '
            'conventional-commit prefixes.'
        ),
        notes_markdown=_fallback_notes(commits),
    )
    completion = await anthropic.complete_json(
        _build_release_notes_prompt(
            ctx.project_slug,
            body.last_tag,
            body.base_sha,
            body.head_sha,
            commits,
        ),
        schema=DraftReleaseNotes,
        fallback=fallback,
        system=_release_notes_system(),
        cache_system_prompt=True,
    )
    notes = completion.data
    # Re-bump if Claude returned a non-semver-shaped version string.
    if not _SEMVER_RE.match(notes.version.lstrip('v')):
        notes = notes.model_copy(
            update={'version': _bump_semver(body.last_tag, notes.bump)}
        )
    return DraftReleaseNotesResponse(
        bump=notes.bump,
        version=notes.version,
        reasoning=notes.reasoning,
        notes_markdown=notes.notes_markdown,
        degraded=completion.degraded,
        commits_considered=len(commits),
    )


# ---------------------------------------------------------------------------
# Promotion options
# ---------------------------------------------------------------------------


_PROMOTION_OPTIONS_QUERY: typing.LiteralString = """
MATCH (p:Project {{id: {project_id}}})
      -[:OWNED_BY]->(:Team)
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
MATCH (p)-[:DEPLOYED_IN]->(e:Environment)
OPTIONAL MATCH (p)-[:HAS_RELEASE]->(r:Release)
               -[d:DEPLOYED_TO]->(e)
RETURN e{{.slug, .name, .sort_order}} AS env,
       CASE WHEN r IS NULL THEN null ELSE r{{.*}} END AS release,
       CASE WHEN d IS NULL THEN null ELSE d.deployments END
           AS deployments
"""


@project_deployments_router.get('/promotion-options')
async def list_promotion_options(  # noqa: C901
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:deployment:read'),
        ),
    ],
    source: str | None = None,
) -> list[PromotionOption]:
    """Enumerate the from→to promotion gaps the popover offers.

    For each consecutive pair of envs (sorted by ``sort_order``)
    where the from-env has a release deployed, returns the gap with
    the from-env's current version + SHA, the to-env's current
    version + SHA (when present), and the count of commits between
    them via ``plugin.compare()``.  Plugin failures are tolerated:
    the entry returns ``commits_pending=None``.
    """
    rows = await db.execute(
        _PROMOTION_OPTIONS_QUERY,
        {'project_id': project_id, 'org_slug': org_slug},
        ['env', 'release', 'deployments'],
    )
    if not rows:
        return []
    # The query returns one row per (Release, Environment) pair, so an
    # env with multiple historical releases produces multiple rows.
    # To pick a stable "current" release per env, parse the deployment
    # event history on each edge and rank by the most recent event
    # timestamp. Envs with no deployment history fall back to no
    # release.
    by_slug: dict[str, dict[str, typing.Any]] = {}
    for row in rows:
        env = graph.parse_agtype(row['env'])
        if not env:
            continue
        slug = env['slug']
        release_raw = graph.parse_agtype(row['release'])
        latest = _latest_deployment_timestamp(
            graph.parse_agtype(row['deployments'])
        )
        existing = by_slug.get(slug)
        if existing is None:
            by_slug[slug] = {
                'env': env,
                'release': release_raw,
                'latest': latest,
            }
            continue
        # Prefer the row with the most recent deployment event; fall
        # back to keeping a non-null release if neither row has events.
        existing_latest = existing.get('latest')
        if latest is not None and (
            existing_latest is None or latest > existing_latest
        ):
            by_slug[slug] = {
                'env': env,
                'release': release_raw,
                'latest': latest,
            }
        elif (
            latest is None
            and existing_latest is None
            and release_raw
            and not existing.get('release')
        ):
            by_slug[slug] = {
                'env': env,
                'release': release_raw,
                'latest': None,
            }

    ordered = sorted(
        by_slug.values(),
        key=lambda item: (
            item['env'].get('sort_order') or 0,
            item['env'].get('name') or '',
        ),
    )
    if len(ordered) < 2:
        return []

    # Resolve plugin once so we can issue compare() calls.
    resolved, ctx, credentials = await _resolve_and_context(
        db, org_slug, project_id, auth, source=source
    )
    handler = _handler(resolved)

    # Collect every adjacent-env pair first so we can fan the
    # ``compare()`` calls out with ``asyncio.gather`` instead of
    # awaiting them serially — the popover blocks on this for the
    # length of the slowest plugin RTT times N envs.
    pairs: list[tuple[dict[str, typing.Any], dict[str, typing.Any]]] = []
    for from_item, to_item in itertools.pairwise(ordered):
        if not from_item['release']:
            continue
        pairs.append((from_item, to_item))

    async def _compare_or_none(
        from_committish: str, to_committish: str
    ) -> int | None:
        if not (
            to_committish
            and from_committish
            and to_committish != from_committish
        ):
            return None
        try:
            cmp_result = await call_with_timeout(
                handler.compare(
                    ctx,
                    credentials,
                    base=to_committish,
                    head=from_committish,
                )
            )
        except Exception:  # noqa: BLE001
            LOGGER.debug(
                'compare failed for %s..%s', to_committish, from_committish
            )
            return None
        return cmp_result.ahead

    pair_committishes: list[tuple[str, str]] = []
    for from_item, to_item in pairs:
        from_committish = str(from_item['release'].get('committish') or '')
        to_committish = (
            str(to_item['release'].get('committish') or '')
            if to_item['release']
            else ''
        )
        pair_committishes.append((from_committish, to_committish))

    commits_pending_per_pair = await asyncio.gather(
        *(_compare_or_none(fc, tc) for fc, tc in pair_committishes)
    )

    options: list[PromotionOption] = []
    for (from_item, to_item), (from_committish, to_committish), pending in zip(
        pairs, pair_committishes, commits_pending_per_pair, strict=True
    ):
        from_release = from_item['release']
        to_release = to_item['release']
        from_tag = from_release.get('tag')
        from_display = str(from_tag) if from_tag else (from_committish or None)
        if to_release:
            to_tag = to_release.get('tag')
            to_display = str(to_tag) if to_tag else (to_committish or None)
        else:
            to_display = None
        options.append(
            PromotionOption(
                from_environment=from_item['env']['slug'],
                to_environment=to_item['env']['slug'],
                from_version=from_display,
                to_version=to_display,
                from_sha=from_committish or None,
                to_sha=to_committish or None,
                commits_pending=pending,
            )
        )
    return options


# ---------------------------------------------------------------------------
# Releases tab (build-and-release-only projects)
#
# These endpoints back the project-detail "Releases" tab for projects with
# no environments.  Commit / tag history is read from the ClickHouse
# ``commits`` / ``tags`` tables (synced by the VCS plugin); release notes
# come from the graph ``Release`` nodes; and ``releases/cut`` cuts a tag +
# GitHub release with no deployment step.
# ---------------------------------------------------------------------------


def _recent_commit_from_row(row: dict[str, typing.Any]) -> RecentCommit:
    """Map a ClickHouse ``commits`` row onto a :class:`RecentCommit`."""
    sha = str(row['sha'])
    author = row.get('author')
    url = row.get('url')
    return RecentCommit(
        sha=sha,
        short_sha=str(row.get('short_sha') or sha[:7]),
        message=str(row.get('message') or ''),
        author=str(author) if author else None,
        authored_at=row['authored_at'],
        ci_status=str(row.get('ci_status') or 'unknown'),
        url=str(url) if url else None,
    )


async def _ci_status_by_sha(
    project_id: str, shas: list[str]
) -> dict[str, str]:
    """Look up ``ci_status`` for a bounded set of shas, ``{}`` when empty.

    Uses enumerated string params (the sha list is small and bounded by
    the caller) rather than an Array binding, keeping to the parameter
    features already exercised elsewhere in the codebase.
    """
    if not shas:
        return {}
    sha_params = {f'sha{i}': sha for i, sha in enumerate(shas)}
    placeholders = ', '.join(f'{{sha{i}:String}}' for i in range(len(shas)))
    # placeholders are generated indices; all values are bound params.
    sql = (
        'SELECT sha, ci_status FROM commits FINAL '  # noqa: S608
        'WHERE project_id = {project_id:String} '
        f'AND sha IN ({placeholders})'
    )
    rows = await clickhouse.query(
        sql, {'project_id': project_id, **sha_params}
    )
    return {str(r['sha']): str(r.get('ci_status') or 'unknown') for r in rows}


def _release_url_from_links(raw: typing.Any) -> str | None:
    """Extract the ``github_release`` URL from a Release node's links."""
    if not raw:
        return None
    data = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(data, list):
        return None
    for item in data:  # type: ignore[reportUnknownVariableType]
        if not isinstance(item, dict):
            continue
        kind = item.get('type')  # type: ignore[reportUnknownMemberType]
        if kind != 'github_release':
            continue
        url = item.get('url')  # type: ignore[reportUnknownMemberType]
        if isinstance(url, str) and url:
            return url
    return None


async def _release_nodes_by_tag(
    db: graph.Graph, org_slug: str, project_id: str
) -> dict[str, dict[str, typing.Any]]:
    """Map ``tag -> Release node`` for the project's tagged releases."""
    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    MATCH (p)-[:HAS_RELEASE]->(r:Release)
    WHERE r.tag IS NOT NULL
    RETURN r{{.*}} AS release
    """
    rows = await db.execute(
        query,
        {'project_id': project_id, 'org_slug': org_slug},
        ['release'],
    )
    out: dict[str, dict[str, typing.Any]] = {}
    for row in rows:
        node = typing.cast(
            'dict[str, typing.Any]', graph.parse_agtype(row['release'])
        )
        tag = node.get('tag')
        if tag:
            out[str(tag)] = node
    return out


@project_deployments_router.get('/recent-commits')
async def list_recent_commits(
    org_slug: str,
    project_id: str,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:deployment:read'),
        ),
    ],
    limit: int = 25,
    ref: str | None = None,
) -> list[RecentCommit]:
    """Recent commits for the project, newest first, from ClickHouse.

    Ordered by push then author time across all synced refs; pass ``ref``
    to scope to one branch.  Capped at 200.
    """
    capped = max(1, min(limit, 200))
    sql = (
        'SELECT sha, short_sha, message, author_name AS author, '
        'authored_at, ci_status, url FROM commits FINAL '
        'WHERE project_id = {project_id:String} '
        "AND ({ref:String} = '' OR ref = {ref:String}) "
        'ORDER BY pushed_at DESC, authored_at DESC LIMIT {limit:UInt32}'
    )
    rows = await clickhouse.query(
        sql,
        {'project_id': project_id, 'ref': ref or '', 'limit': capped},
    )
    return [_recent_commit_from_row(row) for row in rows]


_DRIFT_COMMIT_CAP = 100


@project_deployments_router.get('/release-drift')
async def get_release_drift(
    org_slug: str,
    project_id: str,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:deployment:read'),
        ),
    ],
) -> ReleaseDriftResponse:
    """Commits awaiting a release: the delta from the latest tag to HEAD.

    Computed from ClickHouse: find the latest tag, the HEAD commit, and
    the commits authored after the tag's commit.  With no prior tag the
    drift is the full (capped) history and the suggestion is ``v0.1.0``.
    """
    # Fetch all tags and pick the latest *release* by semver (not by
    # timestamp): a late-synced or backported lower version must not be
    # treated as the base, or the "commits since the last tag" delta below
    # is computed from the wrong tag.
    tag_rows = await clickhouse.query(
        'SELECT name, sha, tagged_at, recorded_at FROM tags FINAL '
        'WHERE project_id = {project_id:String}',
        {'project_id': project_id},
    )
    latest = _latest_release_tag(tag_rows)
    latest_tag = str(latest['name']) if latest else None
    latest_tag_sha = str(latest['sha']) if latest else None
    latest_tag_at = (
        (latest.get('tagged_at') or latest.get('recorded_at'))
        if latest
        else None
    )

    head_rows = await clickhouse.query(
        'SELECT sha FROM commits FINAL '
        'WHERE project_id = {project_id:String} '
        'ORDER BY pushed_at DESC, authored_at DESC LIMIT 1',
        {'project_id': project_id},
    )
    head_sha = str(head_rows[0]['sha']) if head_rows else None

    since: datetime.datetime | None = None
    if latest_tag_sha:
        base_rows = await clickhouse.query(
            'SELECT authored_at FROM commits FINAL '
            'WHERE project_id = {project_id:String} AND sha = {sha:String} '
            'LIMIT 1',
            {'project_id': project_id, 'sha': latest_tag_sha},
        )
        if not base_rows:
            # Tag exists but its commit isn't synced -- we can't bound the
            # delta, so report no drift rather than dumping all history.
            return ReleaseDriftResponse(
                latest_tag=latest_tag,
                latest_tag_sha=latest_tag_sha,
                latest_tag_at=latest_tag_at,
                head_sha=head_sha,
                commits_since_tag=0,
                commits=[],
                suggested_bump='patch',
                suggested_tag=_bump_semver(latest_tag, 'patch'),
            )
        since = base_rows[0]['authored_at']

    where = 'project_id = {project_id:String}'
    params: dict[str, typing.Any] = {'project_id': project_id}
    if since is not None:
        where += ' AND authored_at > {since:DateTime64(3)}'
        params['since'] = since

    commit_rows = await clickhouse.query(
        # WHERE is a fixed string; all values are bound params.
        'SELECT sha, short_sha, message, author_name AS author, '  # noqa: S608
        'authored_at, ci_status, url FROM commits FINAL '
        f'WHERE {where} '
        'ORDER BY authored_at DESC LIMIT {cap:UInt32}',
        {**params, 'cap': _DRIFT_COMMIT_CAP},
    )
    count_rows = await clickhouse.query(
        f'SELECT count() AS c FROM commits FINAL WHERE {where}',  # noqa: S608
        params,
    )
    commits_since_tag = int(count_rows[0]['c']) if count_rows else 0
    commits = [_recent_commit_from_row(row) for row in commit_rows]

    classify_input = [
        Commit(sha=c.sha, short_sha=c.short_sha, message=c.message)
        for c in commits
    ]
    bump = _classify_bump(classify_input)
    return ReleaseDriftResponse(
        latest_tag=latest_tag,
        latest_tag_sha=latest_tag_sha,
        latest_tag_at=latest_tag_at,
        head_sha=head_sha,
        commits_since_tag=commits_since_tag,
        commits=commits,
        suggested_bump=bump,
        suggested_tag=_bump_semver(latest_tag, bump),
    )


@project_deployments_router.get('/release-history')
async def get_release_history(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:deployment:read'),
        ),
    ],
    limit: int = 20,
) -> list[ReleaseHistoryEntry]:
    """Release history: ClickHouse tags joined to their ``Release`` nodes."""
    capped = max(1, min(limit, 100))
    # Fetch all tags (not a timestamp-limited window) so the semver sort
    # below ranks the full candidate set: a high-semver tag with an old or
    # late-synced timestamp must still be able to reach the head of the list,
    # consistent with the drift base selection.
    tag_rows = await clickhouse.query(
        'SELECT name, sha, tagged_at, tagger_name, url, recorded_at '
        'FROM tags FINAL WHERE project_id = {project_id:String}',
        {'project_id': project_id},
    )
    nodes = await _release_nodes_by_tag(db, org_slug, project_id)
    ci_by_sha = await _ci_status_by_sha(
        project_id, [str(r['sha']) for r in tag_rows if r.get('sha')]
    )
    entries: list[ReleaseHistoryEntry] = []
    for row in tag_rows:
        name = str(row['name'])
        sha = str(row['sha'])
        node = nodes.get(name) or {}
        tagger = row.get('tagger_name')
        created_by = node.get('created_by')
        entries.append(
            ReleaseHistoryEntry(
                tag=name,
                sha=sha,
                short_sha=sha[:7],
                published_at=row.get('tagged_at') or row.get('recorded_at'),
                author=str(tagger) if tagger else (created_by or None),
                ci_status=ci_by_sha.get(sha, 'unknown'),
                title=node.get('title'),
                notes_markdown=node.get('description'),
                release_url=_release_url_from_links(node.get('links')),
                tag_url=str(row['url']) if row.get('url') else None,
                package_url=None,
            )
        )
    # Order by released version (highest semver first) so the head of the
    # list is the current release -- consistent with the drift base, which
    # is also chosen by semver rather than timestamp.
    entries.sort(
        key=lambda e: _release_tag_order_key(e.tag, e.published_at),
        reverse=True,
    )
    return entries[:capped]


@project_deployments_router.post('/releases/cut', status_code=201)
async def cut_release(
    org_slug: str,
    project_id: str,
    body: ReleaseCutRequest,
    background: fastapi.BackgroundTasks,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:deployment:write'),
        ),
    ],
    source: str | None = None,
) -> ReleaseCutResponse:
    """Cut a git tag + GitHub release at ``committish`` -- no deployment.

    The build-and-release-only (library / image) flow: validate the
    semver tag and committish, cut the tag + release via the deployment
    plugin (reusing the promote machinery minus the deploy step), upsert
    the matching ``Release`` node, and record an audit row.
    """
    if not versioning.is_semver_tag(body.tag):
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                f'Release tag {body.tag!r} is not a semver tag '
                '(e.g. "v1.2.3").'
            ),
        )
    if not versioning.is_commitish(body.committish):
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                f'Release committish {body.committish!r} is not a git SHA '
                '(7-40 hex chars).'
            ),
        )

    resolved, ctx, credentials = await _resolve_and_context(
        db, org_slug, project_id, auth, source=source
    )
    handler = _handler(resolved)

    warnings: list[str] = []
    release_info = await _cut_tag_and_release(
        db,
        ctx=ctx,
        resolved=resolved,
        handler=handler,
        credentials=credentials,
        auth=auth,
        from_committish=body.committish,
        tag=body.tag,
        release_name=body.release_name,
        release_notes_markdown=body.release_notes_markdown,
        prerelease=body.prerelease,
        warnings=warnings,
        project_id=project_id,
        log_context='release-cut',
    )
    release_url = (release_info.html_url if release_info else None) or (
        release_info.url if release_info else None
    )

    await persist_link_writeback(db, ctx)

    committish = body.committish[:7].lower()
    await _upsert_release_node(
        db,
        project_id=project_id,
        tag=body.tag,
        committish=committish,
        title=body.release_name or body.tag,
        notes_markdown=body.release_notes_markdown,
        release_url=release_url,
        created_by=auth.principal_name,
    )

    LOGGER.info(
        'Release cut: project=%s tag=%s committish=%s plugin=%s actor=%s',
        project_id,
        body.tag,
        committish,
        resolved.plugin_slug,
        ctx.actor_user_id,
    )
    background.add_task(
        _record_deployment_audit,
        project_id=project_id,
        project_slug=ctx.project_slug,
        environment_slug='',
        recorded_by=auth.principal_name,
        action='release',
        tag=body.tag,
        committish=committish,
        plugin_slug=resolved.plugin_slug,
        run_url=None,
        release_url=release_url,
    )
    return ReleaseCutResponse(
        tag=body.tag,
        release_url=release_url,
        committish=committish,
        recorded=True,
        warning='; '.join(warnings) if warnings else None,
    )
