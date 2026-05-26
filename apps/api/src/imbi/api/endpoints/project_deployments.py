"""Project deployment plugin endpoints.

Pass-through endpoints that resolve the project's ``tab='deployment'``
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
    """
    description = json.dumps(
        {
            'action': action,
            'plugin_slug': plugin_slug,
            'run_url': run_url,
            'release_url': release_url,
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
        link=run_url,
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
    return await call_with_timeout(
        handler.list_refs(ctx, credentials, kind=kind, query=q)
    )


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
    return await call_with_timeout(
        handler.list_commits(ctx, credentials, ref=ref, limit=limit)
    )


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
    return await call_with_timeout(
        handler.resolve_committish(ctx, credentials, committish)
    )


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
    return await call_with_timeout(
        handler.compare(ctx, credentials, base=base, head=head)
    )


@project_deployments_router.post('', status_code=202)
async def trigger_deployment(
    org_slug: str,
    project_id: str,
    body: DeploymentRequestBody,
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
            db, org_slug, project_id, auth, body, source=source
        )
    return await _handle_deploy(
        db, org_slug, project_id, auth, body, source=source
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
    await _record_deployment_audit(
        project_id=project_id,
        project_slug=ctx.project_slug,
        environment_slug=body.environment,
        recorded_by=auth.principal_name,
        action=body.action,
        tag=matched_tag if result is not None else candidate_tag,
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
    """Cut a tag + create a release at ``body.from_committish``.

    The repo's ``on: release: [published]`` workflow handles the
    deploy, so we don't dispatch from here.  Failures degrade to a
    warning appended to ``warnings`` rather than raising -- a flaky
    GitHub API shouldn't bury the audit trail.  Returns the
    plugin-returned ReleaseInfo on success (or ``None`` when the
    plugin has no ``create_release``).
    """
    tag_message = body.release_name or body.tag

    async def _create_tag(c: PluginContext) -> typing.Any:
        return await call_with_timeout(
            handler.create_tag(
                c,
                _resolve_credentials(c, credentials),
                sha=body.from_committish,
                tag=body.tag,
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
                'creating tags; promote is not available.'
            ),
        ) from exc
    except Exception as exc:
        if _is_already_exists_error(exc):
            LOGGER.debug(
                'create_tag: tag %s already exists for project=%s, continuing',
                body.tag,
                project_id,
            )
        else:
            LOGGER.exception(
                'create_tag failed for project=%s env=%s tag=%s',
                project_id,
                body.to_environment,
                body.tag,
            )
            warnings.append(_promote_warning('create_tag', exc))

    async def _create_release(c: PluginContext) -> typing.Any:
        return await call_with_timeout(
            handler.create_release(
                c,
                _resolve_credentials(c, credentials),
                tag=body.tag,
                name=body.release_name or body.tag,
                body_markdown=body.release_notes_markdown,
                prerelease=body.prerelease,
            )
        )

    try:
        return await call_with_identity_retry(
            db, ctx, resolved, auth, fn=_create_release, attached=True
        )
    except NotImplementedError:
        LOGGER.info(
            'Plugin %r has no create_release; tag-only promote',
            resolved.plugin_slug,
        )
        return None
    except Exception as exc:
        if _is_already_exists_error(exc):
            LOGGER.debug(
                'create_release: %s already exists for project=%s',
                body.tag,
                project_id,
            )
        else:
            LOGGER.exception(
                'create_release failed for project=%s env=%s tag=%s',
                project_id,
                body.to_environment,
                body.tag,
            )
            warnings.append(_promote_warning('create_release', exc))
        return None


async def _handle_promote(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
    auth: permissions.AuthContext,
    body: PromoteActionRequest,
    *,
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
    await _record_deployment_audit(
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
