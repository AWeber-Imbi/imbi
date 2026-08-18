"""Project deployment plugin endpoints.

Pass-through endpoints that resolve the project's ``plugin_type='deployment'``
plugin and call its handler methods.  Covers ref / commit discovery,
comparison, ``deploy`` / ``redeploy`` workflow dispatch (Phase 1), and
the ``promote`` flow with AI-drafted release notes plus tag + Release
upsert (Phase 2).

See ``docs/deployments-plan.md`` for the full design.
"""

import asyncio
import collections.abc
import datetime
import functools
import importlib.resources
import itertools
import json
import logging
import re
import textwrap
import typing

import fastapi
import httpx
import nanoid
import pydantic

from imbi.api.auth import permissions, principals
from imbi.api.commit_sync import queue as commit_sync_queue
from imbi.api.commit_sync import service as commit_sync_service
from imbi.api.deployment_sync import queue as deployment_sync_queue
from imbi.api.deployment_sync import service as deployment_sync_service
from imbi.api.endpoints._helpers import (
    deployed_operation_log,
    lookup_project_links,
    lookup_project_slugs,
    lookup_project_type_slugs,
    persist_link_writeback,
)
from imbi.api.endpoints.releases import (
    AppendOutcome,
    ReleaseEnvironmentEdgeResponse,
    append_deployment_event,
)
from imbi.api.identity import attribution
from imbi.api.identity.host_integration import (
    attach_identity,
    call_with_identity_retry,
)
from imbi.api.llm.dependencies import InjectAnthropicClient
from imbi.api.plugins import call_with_timeout
from imbi.api.plugins.resolution import ResolvedCapability, resolve_capability
from imbi.api.release_promote import queue as release_promote_queue
from imbi.api.release_promote import service as release_promote_service
from imbi.api.scoring import OptionalValkeyClient
from imbi.common import clickhouse, graph, versioning
from imbi.common import models as common_models
from imbi.common.plugins import base as plugin_base
from imbi.common.plugins import decrypt_integration_credentials
from imbi.common.plugins.base import (
    Commit,
    CompareResult,
    DeploymentCapability,
    DeploymentRun,
    PluginContext,
    Ref,
    RemoteDeployment,
    RemoteRelease,
)

LOGGER = logging.getLogger(__name__)

# Tags the release-notes backfill will fetch in one pass. Bounded because
# each one is a remote API call, and only tags missing notes are counted --
# a first sync of a long-lived repo tops out here and the next sync picks up
# where it left off.
_NOTES_BACKFILL_CAP = 25

#: A commit's author as an *identity*: the source host's user (a stable
#: handle the identity connections can resolve) when the sync recorded one,
#: otherwise the raw git author email. Rows attribute to one Imbi user only
#: when they agree on a single value, so the preference order matters.
_AUTHOR_EMAIL_SQL = (
    "coalesce(nullIf(author_user, ''), nullIf(author_email, ''))"
)

#: Every synced tag for a project. Deliberately unfiltered by timestamp:
#: callers rank the full candidate set by semver, so a late-synced or
#: backported tag must still be able to reach the head of the list.
_PROJECT_TAGS_SQL = (
    'SELECT name, sha, tagged_at, recorded_at FROM tags FINAL '
    'WHERE project_id = {project_id:String}'
)

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
    then dispatches the workflow with the tag as the ref.  The GitHub
    Release is *not* created here -- it is the ratification of a
    successful rollout, published later through
    ``POST /deployments/releases/{tag}/publish`` (see
    :func:`publish_release`).
    """

    action: typing.Literal['promote']
    from_environment: str
    to_environment: str
    from_committish: str
    tag: str
    release_name: str | None = None
    release_notes_markdown: str = ''
    prerelease: bool = False
    #: Operator acknowledgement that ``from_committish`` has a failing CI
    #: run.  Without it a red commit is refused with a 409; with it the
    #: promote proceeds and the override is recorded (see
    #: :func:`_assert_ci_not_failing`).  Only ``fail`` is gated -- an
    #: ``unknown`` status means CI never ran or the token cannot read
    #: check-runs, which must not stand in for a failure.
    acknowledge_ci_failure: bool = False


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
    #: Set only on the dispatch-driven promote path (the project has a
    #: Release workflow configured).  ``'building'`` means the response
    #: went out while the release build was still running and the
    #: Deployment does not exist yet -- the UI polls
    #: ``GET /deployments/promote-status`` from here rather than treating
    #: ``run`` as a live rollout.  ``None`` marks the legacy path, where
    #: the Deployment was created inline and ``run`` is already real.
    phase: typing.Literal['building'] | None = None
    #: The dispatched workflow run, when there is one.
    artifact_run_id: str | None = None
    artifact_run_url: str | None = None
    #: ``False`` when the build was dispatched but no watcher could be
    #: enqueued (Valkey down).  The build still runs; Imbi just won't
    #: finish the promote on its own, so the UI must say so.
    watched: bool = True


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


class CommitCheckStatus(pydantic.BaseModel):
    """Live rolled-up CI status for one commit.

    Backs the promote / release forms' pre-flight warning.  Read live from
    the plugin rather than from the synced ``commits`` table because it is
    the same call the promote gate itself makes -- a banner sourced from
    the (possibly lagging) sync could tell the operator the commit is
    green and then have the promote refused.
    """

    committish: str
    ci_status: plugin_base.CheckStatus = 'unknown'


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
    #: Email of the Imbi user the commit author resolves to via identity
    #: attribution (``commits.author_user``), falling back to the git
    #: author's own email when the author maps to no active identity
    #: connection; ``None`` when neither is recorded. Lets the UI link the
    #: author to their profile, render their Gravatar, and -- since the git
    #: *name* varies per commit (a squash merge records the source host's
    #: profile name, a local commit whatever git config holds) -- show one
    #: person under one name down a commit list.
    author_email: str | None = None
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
    #: Email of the Imbi user who cut the release (the ``Release`` node's
    #: ``created_by`` principal); ``None`` for tags with no Imbi-resolved
    #: author. Lets the UI link the author to their profile + Gravatar.
    author_email: str | None = None
    ci_status: str = 'unknown'
    title: str | None = None
    notes_markdown: str | None = None
    release_url: str | None = None
    tag_url: str | None = None
    package_url: str | None = None
    #: ``True`` when the release is blocked from shipping. Deploys and
    #: promotes targeting it are refused with a 409; the UI renders the
    #: row as blocked and surfaces ``blocked_reason``.
    blocked: bool = False
    blocked_reason: str | None = None
    blocked_by: str | None = None
    blocked_at: datetime.datetime | None = None
    #: Set when the release was cut over a *failing* CI run that an
    #: operator explicitly acknowledged (ENG-102).  ``ci_status`` above is
    #: the commit's CI state as it stands *now*; this is the record of what
    #: was known, and decided, at promote time -- the two differ once a
    #: re-run turns the commit green after the fact.
    ci_override_by: str | None = None
    ci_override_at: datetime.datetime | None = None


class ReleaseBlockRequest(pydantic.BaseModel):
    """Body for ``POST /deployments/releases/{tag}/block``."""

    model_config = pydantic.ConfigDict(extra='forbid')

    reason: typing.Annotated[
        str,
        pydantic.StringConstraints(
            strip_whitespace=True, min_length=1, max_length=500
        ),
    ]


class ReleaseBlockResponse(pydantic.BaseModel):
    """Block state for a release after a block / unblock."""

    tag: str
    blocked: bool
    blocked_reason: str | None = None
    blocked_by: str | None = None
    blocked_at: datetime.datetime | None = None


class ReleasePublishRequest(pydantic.BaseModel):
    """Body for ``POST /deployments/releases/{tag}/publish``.

    Every field is optional: the release title and notes come from the
    ``Release`` node being ratified, so a caller that knows only the tag
    (the gateway, reacting to a successful deployment) posts an empty
    body.
    """

    model_config = pydantic.ConfigDict(extra='forbid')

    prerelease: bool = False


class ReleasePublishResponse(pydantic.BaseModel):
    """Result of ratifying a ``Release`` on the remote."""

    tag: str
    published: bool
    release_url: str | None = None
    warning: str | None = None


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
    #: Same gate as the promote path; see
    #: :attr:`PromoteActionRequest.acknowledge_ci_failure`.
    acknowledge_ci_failure: bool = False


class ReleaseCutResponse(pydantic.BaseModel):
    """Response shape for a successful ``releases/cut`` action."""

    tag: str
    release_url: str | None = None
    committish: str
    recorded: bool = False
    warning: str | None = None
    #: Set when the project has a Release workflow configured, in which
    #: case the tag and the remote Release do not exist yet -- the
    #: dispatched build creates them.  ``release_url`` is therefore
    #: ``None`` here, and the UI polls
    #: ``GET /deployments/promote-status`` instead of linking straight to
    #: a release.  ``None`` marks the inline path, where both already
    #: exist by the time this returns.
    phase: typing.Literal['building'] | None = None
    artifact_run_id: str | None = None
    artifact_run_url: str | None = None
    watched: bool = True


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
    best_effort_identity: bool = False,
) -> tuple[ResolvedCapability, PluginContext, dict[str, str]]:
    """Common boilerplate: resolve plugin, attach identity, build creds.

    When ``best_effort_identity`` is set (the resync/backfill path), a
    missing per-user identity connection is not fatal: the actor is still
    stamped for attribution, but credential resolution falls back to the
    Integration's own service credentials (a PAT or GitHub App) rather
    than raising ``identity_required``.  This lets the headless
    deployment-resync sweep -- which acts as a synthetic principal with
    no user -- backfill via the App installation token, mirroring how
    project analysis and pr-sync already behave.
    """
    resolved = await resolve_capability(db, project_id, 'deployment', source)
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
        assignment_options=resolved.capability_options,
        integration_options=resolved.integration_options,
        capability_options=resolved.capability_options,
        environment_config=environment_config,
        project_links=project_links,
        project_type_slugs=project_type_slugs,
    )
    if best_effort_identity:
        ctx = await _attach_identity_best_effort(db, ctx, resolved, auth)
    else:
        ctx = await attach_identity(db, ctx, resolved, auth)

    if ctx.identity and ctx.identity.access_token:
        credentials: dict[str, str] = {
            'access_token': ctx.identity.access_token,
        }
    else:
        credentials = decrypt_integration_credentials(
            resolved.encrypted_credentials
        )
        if not _has_service_credentials(
            credentials, allow_app=best_effort_identity
        ):
            raise fastapi.HTTPException(
                status_code=503,
                detail=(
                    'No deployment credentials available: bind an '
                    'identity or configure a service-account token.'
                ),
            )
    return resolved, ctx, credentials


async def _attach_identity_best_effort(
    db: graph.Graph,
    ctx: PluginContext,
    resolved: ResolvedCapability,
    auth: permissions.AuthContext,
) -> PluginContext:
    """Attach the actor's identity when available, else proceed without.

    Resync backfills historical remote activity and must not hard-fail
    when the acting principal (or a headless sweep) has no per-user
    identity connection.  On ``identity_required`` we keep the actor
    stamped and let the caller fall back to the Integration's service
    credentials.
    """
    try:
        return await attach_identity(db, ctx, resolved, auth)
    except fastapi.HTTPException as exc:
        detail: object = exc.detail
        if not (
            isinstance(detail, dict)
            and typing.cast('dict[str, object]', detail).get('error')
            == 'identity_required'
        ):
            raise
        LOGGER.info(
            'No identity connection for the deployment integration on '
            'project %s; falling back to service credentials',
            ctx.project_id,
        )
        actor_user_id = auth.user.id if auth.user else None
        return ctx.model_copy(update={'actor_user_id': actor_user_id})


def _has_service_credentials(
    credentials: dict[str, str], *, allow_app: bool
) -> bool:
    """Whether *credentials* carry a usable non-identity secret.

    A PAT (``access_token``/``token``) always qualifies.  GitHub App
    credentials (``app_id`` + ``private_key``) qualify only when
    ``allow_app`` is set -- the backfill paths that can mint an
    installation token without an acting user.
    """
    if credentials.get('access_token') or credentials.get('token'):
        return True
    return allow_app and bool(
        credentials.get('app_id') and credentials.get('private_key')
    )


async def _resolve_tag_formats(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
) -> list[common_models.TagFormat]:
    """Resolve the effective release/deploy tag-format policy.

    The project's type(s) override the organization: when any of the
    project's ``ProjectType`` nodes configure ``tag_formats`` those apply
    (unioned across types); otherwise the organization's ``tag_formats``
    apply. When neither configures any, the result is empty -- meaning
    "no restriction" (see ``versioning.matches_tag_formats``).
    """
    query: typing.LiteralString = (
        'MATCH (o:Organization {{slug: {org_slug}}})'
        ' OPTIONAL MATCH (p:Project {{id: {project_id}}})'
        '-[:TYPE]->(pt:ProjectType)-[:BELONGS_TO]->(o)'
        ' RETURN o.tag_formats AS org_formats,'
        ' collect(pt.tag_formats) AS pt_formats'
    )
    try:
        records = await db.execute(
            query,
            {'org_slug': org_slug, 'project_id': project_id},
            columns=['org_formats', 'pt_formats'],
        )
    except Exception:  # noqa: BLE001
        LOGGER.debug('Tag-format lookup failed', exc_info=True)
        return []
    if not records:
        return []

    pt_raw = graph.parse_agtype(records[0].get('pt_formats'))
    pt_entries: list[dict[str, typing.Any]] = []
    if isinstance(pt_raw, list):
        for entry in typing.cast(list[object], pt_raw):
            if isinstance(entry, list):
                pt_entries.extend(
                    typing.cast(dict[str, typing.Any], e)
                    for e in typing.cast(list[object], entry)
                    if isinstance(e, dict)
                )

    # Fall back to the org policy unless the project type produced at
    # least one *valid* format; a project type whose stored formats are
    # all malformed must inherit the org gate, not disable enforcement.
    formats = _validate_tag_formats(pt_entries)
    if formats:
        return formats

    org_raw = graph.parse_agtype(records[0].get('org_formats'))
    org_entries: list[dict[str, typing.Any]] = []
    if isinstance(org_raw, list):
        org_entries = [
            typing.cast(dict[str, typing.Any], e)
            for e in typing.cast(list[object], org_raw)
            if isinstance(e, dict)
        ]
    return _validate_tag_formats(org_entries)


def _validate_tag_formats(
    entries: list[dict[str, typing.Any]],
) -> list[common_models.TagFormat]:
    """Validate stored format dicts, dropping (and logging) malformed ones."""
    formats: list[common_models.TagFormat] = []
    for entry in entries:
        try:
            formats.append(common_models.TagFormat.model_validate(entry))
        except pydantic.ValidationError:
            LOGGER.warning('Skipping invalid stored tag format: %r', entry)
    return formats


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
    """Return True when exc is a GitHub 422 "already exists" rejection.

    The remote states this two different ways.  ``POST /git/refs`` for a
    tag that is already there answers with a bare
    ``{"message": "Reference already exists"}``, but ``POST /releases``
    for a tag that already carries one answers with the generic
    ``{"message": "Validation Failed", "errors": [{"resource":
    "Release", "code": "already_exists", "field": "tag_name"}]}`` -- so
    the per-error codes have to be inspected as well, or a re-publish of
    an already-ratified release reads as a hard failure instead of the
    idempotent no-op it is.
    """
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    if exc.response.status_code != 422:
        return False
    try:
        payload = exc.response.json()
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(payload, dict):
        return False
    body = typing.cast(dict[str, typing.Any], payload)
    if 'already exists' in str(body.get('message') or '').lower():
        return True
    errors = body.get('errors')
    if not isinstance(errors, list):
        return False
    return any(
        str(
            typing.cast(dict[str, typing.Any], error).get('code') or ''
        ).lower()
        == 'already_exists'
        for error in typing.cast(list[object], errors)
        if isinstance(error, dict)
    )


def _promote_warning(step: str, exc: BaseException) -> str:
    """Sanitized client-facing warning for a failed promote step.

    Keeps the step name and the exception class for actionability
    (e.g., ``RuntimeError``, ``ClientResponseError``) but withholds
    the raw exception message, which can carry plugin internals.
    Full detail is preserved in logs via ``LOGGER.exception``.
    """
    return f'{step} failed ({type(exc).__name__}); see server logs.'


def _handler(resolved: ResolvedCapability) -> DeploymentCapability:
    """Instantiate and type-narrow the plugin handler."""
    return typing.cast(DeploymentCapability, resolved.capability_cls())


async def _resolve_ci_status(
    handler: DeploymentCapability,
    ctx: PluginContext,
    credentials: dict[str, str],
    committish: str,
) -> plugin_base.CheckStatus:
    """Roll up the CI check-runs status for *committish*.

    Never raises: a plugin that has no CI concept, a token that cannot read
    check-runs, and a transport error all answer ``'unknown'``.  That is
    the whole point -- the caller gates on ``'fail'`` alone, so a failure
    to *ask* must never read as a failing build.
    """
    try:
        return await call_with_timeout(
            handler.get_check_status(
                ctx,
                _resolve_credentials(ctx, credentials),
                committish=committish,
            )
        )
    except Exception:  # noqa: BLE001
        LOGGER.debug(
            'get_check_status failed for %s on project %s; treating the CI '
            'status as unknown',
            committish,
            ctx.project_id,
            exc_info=True,
        )
        return 'unknown'


async def _assert_ci_not_failing(
    handler: DeploymentCapability,
    ctx: PluginContext,
    credentials: dict[str, str],
    *,
    committish: str,
    acknowledged: bool,
    action: str,
) -> plugin_base.CheckStatus:
    """Refuse a promote / release off a red commit unless acknowledged.

    Returns the observed status so the caller can record it alongside the
    release.  This is a warning, not a block: an operator who has seen the
    failure and decided to ship anyway sets ``acknowledged`` and the
    override is recorded (:func:`_set_release_ci_override`).

    ``committish`` must be the commit on the default branch, never the tag
    being cut.  Tag-triggered workflow runs skip the test jobs, so a tag
    has no meaningful check status of its own -- gating on it would ask a
    question whose answer is always ``unknown``.

    Only ``'fail'`` gates.  ``'warn'`` (a cancelled or stale run) is not a
    failing build, and ``'unknown'`` means CI never ran or the token lacks
    the scope to look -- treating either as a failure would refuse most
    promotes.
    """
    status = await _resolve_ci_status(handler, ctx, credentials, committish)
    if status != 'fail':
        return status
    short = versioning.short_committish(committish)
    if not acknowledged:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'CI failed for commit {short}. Review the failing checks '
                f'before you {action} it; to {action} it anyway, resubmit '
                'with acknowledge_ci_failure=true.'
            ),
        )
    LOGGER.warning(
        'CI failure overridden: project=%s action=%s commit=%s actor=%s',
        ctx.project_id,
        action,
        short,
        ctx.actor_user_id,
    )
    return status


def _require_deployment_sync_support(resolved: ResolvedCapability) -> None:
    """Raise 400 unless the plugin opts into deployment resync.

    Shared by the enqueue endpoint and the worker-side
    :func:`resync_for_project` so the gate cannot silently diverge.
    """
    deployment_capability = resolved.entry.manifest.get_capability(
        'deployment'
    )
    supports_deployment_sync = bool(
        deployment_capability
        and deployment_capability.hints.get('supports_deployment_sync')
    )
    if not supports_deployment_sync:
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                f'Plugin {resolved.plugin_slug!r} does not support '
                'deployment resync.'
            ),
        )


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
    ci_status: str = 'unknown',
    ci_override: bool = False,
) -> None:
    """Write a deployment audit row to the ``operations_log``.

    Mirrors the configuration audit pattern in
    ``project_configuration._record_configuration_event`` so the
    project's history pane surfaces deploys/promotes the same way
    it surfaces config changes.  Audit failures intentionally
    propagate so a bad write never silently desyncs the log.

    ``OperationLog.version`` is populated with ``tag if tag else
    committish`` — a single human-friendly display string that the
    operations-log UI can render directly.  ``committish`` is *also*
    recorded as ``commit_sha`` in the audit JSON so the UI can correlate
    a tagged promotion with the untagged deploy of the same commit.

    ``ci_status`` / ``ci_override`` carry the promote-time CI decision
    (ENG-102).  Deploys leave them at their defaults: a deploy ships a
    commit some earlier promote or release already gated, so the CI
    question is not this row's to answer.
    """
    entry = deployed_operation_log(
        project_id=project_id,
        project_slug=project_slug,
        environment_slug=environment_slug,
        recorded_by=recorded_by,
        performed_by=recorded_by,
        action=action,
        version=tag or committish,
        commit_sha=committish,
        plugin_slug=plugin_slug,
        run_url=run_url,
        release_url=release_url,
        from_environment=from_environment,
        external_run_id=external_run_id,
        ci_status=ci_status,
        ci_override=ci_override,
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
    ``imbi.gateway.actions.create_release``: semver-shaped ``ref``
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
    """Return the ``Release.id`` matching ``(project, tag)``.

    Acts as both an existence probe and a lookup for the release-id
    the caller needs to pass to ``append_deployment_event`` and the
    deployment-audit writer. The tag is the identity when there is one
    — the commit it points at moves when the release workflow bumps the
    version — so ``committish`` only identifies an untagged release.
    AGE doesn't expose NULL equality, so nullable comparisons are
    COALESCEd through a sentinel.
    """
    # Fetch all matching ids so a duplicate ``(project, tag)`` row is
    # visible in the logs instead of being silently masked by
    # ``LIMIT 1`` — AGE has no composite unique constraint to enforce
    # the pair, so duplicates remain possible.
    query: typing.LiteralString = """
    MATCH (:Project {{id: {project_id}}})-[:HAS_RELEASE]->(r:Release)
    WHERE (COALESCE({tag}, '') <> '' AND r.tag = {tag})
       OR (COALESCE({tag}, '') = ''
           AND r.committish = {committish}
           AND COALESCE(r.tag, '') = '')
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
            'Multiple Release nodes for project=%s tag=%r committish=%s; '
            'using the first',
            project_id,
            tag,
            committish,
        )
    rid = graph.parse_agtype(rows[0].get('rid'))
    return str(rid) if rid else None


async def _existing_tag_for_committish(
    db: graph.Graph,
    *,
    project_id: str,
    committish: str,
) -> str | None:
    """Return a tag already recorded for ``committish`` on this project.

    The resync path uses this to reconcile a deployment whose ``ref`` was
    a raw SHA (so ``_resync_release_identity`` derives no tag) onto the
    existing tagged ``Release`` node -- the one the release-history UI
    reads, keyed by tag -- rather than spawning a duplicate untagged node
    the UI never surfaces.  Returns ``None`` when no tagged release exists
    for the commit, and raises ``ValueError`` when the commit carries more
    than one distinct tag -- a retagged commit is ambiguous, so we fail the
    observation rather than silently attaching notes to the wrong release.
    """
    query: typing.LiteralString = """
    MATCH (:Project {{id: {project_id}}})
        -[:HAS_RELEASE]->(r:Release {{committish: {committish}}})
    WHERE r.tag IS NOT NULL
    RETURN r.tag AS tag
    """
    rows = await db.execute(
        query,
        {'project_id': project_id, 'committish': committish},
        ['tag'],
    )
    tags: set[str] = set()
    for row in rows:
        tag = graph.parse_agtype(row.get('tag'))
        if tag:
            tags.add(str(tag))
    if len(tags) == 1:
        return tags.pop()
    if len(tags) > 1:
        raise ValueError(
            'Multiple tagged Releases match this deployment committish'
        )
    return None


async def _best_effort[T](
    call: collections.abc.Awaitable[T], label: str
) -> T | None:
    """Await an *optional* plugin call, degrading any failure to ``None``.

    The shared contract for capability methods a plugin need not implement:
    ``NotImplementedError``, a remote error, or a timeout all yield ``None``
    so the caller falls back rather than failing the write it is enriching.
    """
    try:
        return await call_with_timeout(call)
    except NotImplementedError:
        return None
    except Exception:  # noqa: BLE001
        LOGGER.warning('%s failed', label, exc_info=True)
        return None


async def _get_release_notes(
    handler: DeploymentCapability,
    ctx: PluginContext,
    credentials: dict[str, str],
    tag: str,
) -> str | None:
    """Best-effort fetch of the remote release body for ``tag``.

    Wraps the deployment capability's optional ``get_release_notes`` so
    callers can enrich a ``Release`` node's notes when they know the tag
    but not the body (a webhook-created release, a SHA-ref resync).  Any
    failure -- the capability doesn't implement it, the remote 404s/403s,
    a timeout -- degrades to ``None`` so a notes lookup never blocks the
    surrounding write.
    """
    return await _best_effort(
        handler.get_release_notes(ctx, credentials, tag),
        f'get_release_notes tag={tag}',
    )


async def _get_release(
    handler: DeploymentCapability,
    ctx: PluginContext,
    credentials: dict[str, str],
    tag: str,
) -> RemoteRelease | None:
    """Best-effort fetch of the remote release for ``tag``.

    The metadata-carrying counterpart to :func:`_get_release_notes`, with
    the same degradation contract: a capability that doesn't implement it,
    a remote 404/403, or a timeout all yield ``None`` so a caller can fall
    back to the notes-only path rather than failing its write.
    """
    return await _best_effort(
        handler.get_release(ctx, credentials, tag), f'get_release tag={tag}'
    )


async def _remote_principal(
    login: str | None,
    subject: str | None,
    resolve_user: collections.abc.Callable[
        [str], collections.abc.Awaitable[str | None]
    ]
    | None,
) -> str | None:
    """Who to credit a remote actor to, as a stored principal.

    Prefers the Imbi user the actor's remote subject resolves to (an email,
    matching what the in-product flows record) and falls back to the remote
    login.  ``None`` when the remote credits nobody, leaving the caller's own
    default in place.  Resolution is best-effort: a failing identity lookup
    degrades to the login rather than failing the write being attributed.
    """
    if subject and resolve_user is not None:
        try:
            email = await resolve_user(subject)
        except Exception:  # noqa: BLE001 - attribution is best-effort
            LOGGER.warning(
                'failed to resolve remote subject=%s', subject, exc_info=True
            )
            email = None
        if email:
            return email
    return login or None


async def fetch_release_notes_for_tag(
    db: graph.Graph,
    *,
    org_slug: str,
    project_id: str,
    tag: str,
    auth: permissions.AuthContext,
) -> str | None:
    """Resolve the project's deployment capability and fetch ``tag``'s notes.

    Used by the release-create path to enrich a ``Release`` created from a
    deployment webhook, whose payload carries no release body.  Best-effort:
    a project without a deployment capability, missing service credentials,
    or a remote error all yield ``None`` so release creation is never
    blocked on the notes lookup.
    """
    try:
        resolved, ctx, credentials = await _resolve_and_context(
            db, org_slug, project_id, auth, best_effort_identity=True
        )
    except fastapi.HTTPException:
        return None
    handler = _handler(resolved)
    return await _get_release_notes(
        handler, ctx, _resolve_credentials(ctx, credentials), tag
    )


async def backfill_release_notes(
    db: graph.Graph,
    *,
    org_slug: str,
    project_id: str,
    auth: permissions.AuthContext,
    limit: int = _NOTES_BACKFILL_CAP,
) -> int:
    """Give synced tags that have no notes a ``Release`` node with them.

    A tag cut outside imbi -- a release script, CI, the source host's own
    UI -- reaches the ``tags`` table through commit sync but never gets a
    ``Release`` node, so the Deployments tab lists it with no title and
    "No release notes".  For the newest ``limit`` such tags this asks the
    deployment capability for the remote release and upserts the node from
    it: body, title, URL, and the release's *remote* author, resolved
    through the project's identity connections to an Imbi user where one
    matches.  Returns the number of tags enriched.

    Best-effort throughout: a project with no deployment capability, a
    plugin that implements neither ``get_release`` nor
    ``get_release_notes``, or a tag with no remote release each yield
    nothing rather than raising.  The upsert never clobbers notes that are
    already there.
    """
    tag_rows = await clickhouse.query(
        _PROJECT_TAGS_SQL, {'project_id': project_id}
    )
    if not tag_rows:
        return 0
    nodes = await _release_nodes_by_tag(db, org_slug, project_id)
    missing = [
        row
        for row in tag_rows
        if row.get('sha')
        and not (nodes.get(str(row['name'])) or {}).get('description')
    ]
    if not missing:
        return 0
    missing.sort(
        key=lambda r: _release_tag_order_key(
            str(r['name']), r.get('tagged_at') or r.get('recorded_at')
        ),
        reverse=True,
    )
    try:
        resolved, ctx, credentials = await _resolve_and_context(
            db, org_slug, project_id, auth, best_effort_identity=True
        )
    except fastapi.HTTPException:
        return 0
    handler = _handler(resolved)
    creds = _resolve_credentials(ctx, credentials)
    # Resolve the remote's release author to an Imbi user the same way the
    # deployment resync resolves a deployer, so a release reads as the person
    # who cut it rather than as the login that happens to appear upstream.
    integration_ids = await attribution.identity_integration_ids_for_project(
        db, project_id
    )
    resolve_user = attribution.make_user_resolver(db, integration_ids)
    enriched = 0
    for row in missing[:limit]:
        tag = str(row['name'])
        release = await _get_release(handler, ctx, creds, tag)
        notes = (
            release.body_markdown
            if release
            else await _get_release_notes(handler, ctx, creds, tag)
        )
        if not notes:
            continue
        author = (
            await _remote_principal(
                release.author, release.author_subject, resolve_user
            )
            if release
            else None
        )
        try:
            await _upsert_release_node(
                db,
                project_id=project_id,
                tag=tag,
                committish=str(row['sha']),
                title=(release.name if release and release.name else tag),
                notes_markdown=notes,
                release_url=release.html_url if release else None,
                created_by=author or auth.principal_name,
            )
        except Exception:  # noqa: BLE001
            LOGGER.warning(
                'release-notes backfill failed for project=%s tag=%s',
                project_id,
                tag,
                exc_info=True,
            )
            continue
        enriched += 1
    return enriched


async def resync_for_project(
    db: graph.Graph,
    *,
    org_slug: str,
    project_id: str,
    auth: permissions.AuthContext,
    source: str | None = None,
    limit: int = 1,
) -> ResyncSummary:
    """Resync remote deployments for a single project.

    Resolves the project's deployment plugin, asks it for the most
    recent ``limit`` deployments per environment, upserts ``Release``
    nodes for any observed versions that are missing, appends
    ``DeploymentEvent`` rows on the ``DEPLOYED_TO`` edge (dedup'd by
    ``external_run_id``).  Returns counts + a per-environment error list
    so the host can surface partial results rather than failing the
    whole call on one bad env.

    No ``operations_log`` audit row is written: resync backfills
    historical remote activity, so attributing it to the resync operator
    would poison ``performed_by`` attribution.

    ``limit`` controls how many recent deployments per environment the
    plugin returns.  The default (1) keeps webhook-lapse catch-up cheap;
    a larger value drives a deeper backfill that both fills in missing
    historical ``DeploymentEvent`` rows and re-resolves ``performed_by``
    on already-stored events (dedup'd by ``external_run_id``), which is
    how stale actor attribution gets corrected.
    """
    summary = ResyncSummary(projects=1)
    resolved, ctx, credentials = await _resolve_and_context(
        db,
        org_slug,
        project_id,
        auth,
        source=source,
        best_effort_identity=True,
    )
    _require_deployment_sync_support(resolved)
    environments = await _load_resync_environments(db, project_id=project_id)
    if not environments:
        return summary
    handler = _handler(resolved)

    async def _fetch(c: PluginContext) -> list[RemoteDeployment]:
        # No per-call plugin timeout: a deep backfill (limit=100 across
        # several environments) legitimately takes minutes of remote API
        # calls, and every caller is a background worker (the
        # deployment-sync queue or the maintenance sweep).
        return await handler.list_recent_deployments(
            c,
            _resolve_credentials(c, credentials),
            environments=environments,
            limit=limit,
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
    # Resolve the remote deployer to an Imbi user (via the identity
    # plugins on the same service) so ``performed_by`` matches in-product
    # deploys and the user_activity queries that key on the email. Built
    # once and reused across every observed deployment.
    integration_ids = await attribution.identity_integration_ids_for_project(
        db, project_id
    )
    resolve_user = attribution.make_user_resolver(db, integration_ids)

    async def _fetch_notes(tag: str) -> str | None:
        # Enrichment for deployments whose ref was a raw SHA (so the
        # plugin couldn't populate ``release_notes`` from the ref): once
        # the tag is known, ask the remote for the release body by tag.
        return await _get_release_notes(
            handler, ctx, _resolve_credentials(ctx, credentials), tag
        )

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
                resolve_user=resolve_user,
                fetch_notes=_fetch_notes,
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
    resolve_user: collections.abc.Callable[
        [str], collections.abc.Awaitable[str | None]
    ]
    | None = None,
    fetch_notes: collections.abc.Callable[
        [str], collections.abc.Awaitable[str | None]
    ]
    | None = None,
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

    ``fetch_notes`` (optional) resolves a release body by tag; it is used
    to enrich notes when the deployment ``ref`` was a raw SHA, so the
    plugin couldn't populate ``release_notes`` from the ref itself.
    """
    tag, committish = _resync_release_identity(observed)
    # A deployment whose ref was a raw SHA carries no semver tag.  Reconcile
    # onto the existing tagged Release for this commit (the node the UI
    # reads, keyed by tag) instead of spawning a duplicate untagged node.
    if tag is None:
        tag = await _existing_tag_for_committish(
            db, project_id=project_id, committish=committish
        )
    # Prefer notes the plugin already fetched from the deployment ref; when
    # absent but the tag is now known, ask the remote for the body by tag.
    notes = observed.release_notes
    if not notes and tag is not None and fetch_notes is not None:
        notes = await fetch_notes(tag)
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
    # Attribute the deploy to an Imbi user when the remote subject
    # resolves; otherwise keep the raw remote login for display.
    performed_by = await _remote_principal(
        observed.creator, observed.creator_subject, resolve_user
    )
    release_id = await _upsert_release_node(
        db,
        project_id=project_id,
        tag=tag,
        committish=committish,
        title=title,
        notes_markdown=notes or observed.description or '',
        release_url=observed.deployment_url,
        # Credit whoever the remote says deployed it, not the resync
        # worker's own principal: this is a release Imbi observed rather
        # than one it performed, and ``created_by`` is what the release
        # history shows as the author.
        created_by=performed_by or recorded_by,
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
        performed_by=performed_by,
    )
    if isinstance(result, str):
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


@project_deployments_router.get('/check-status')
async def get_commit_check_status(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:deployment:read'),
        ),
    ],
    committish: str = fastapi.Query(...),
    source: str | None = None,
) -> CommitCheckStatus:
    """Roll up the CI check-runs status for one commit.

    The pre-flight read behind the promote / release forms' CI warning.  It
    is deliberately the *same* call the promote gate makes
    (:func:`_assert_ci_not_failing`) rather than a read of the synced
    ``commits`` table, so what the operator is shown and what the gate
    enforces cannot disagree.

    Never errors on the plugin's behalf: an unreachable or unauthorized
    check-runs API answers ``'unknown'``, which is also the status that
    does not gate a promote.
    """
    resolved, ctx, credentials = await _resolve_and_context(
        db, org_slug, project_id, auth, source=source
    )
    status = await _resolve_ci_status(
        _handler(resolved), ctx, credentials, committish
    )
    await persist_link_writeback(db, ctx)
    return CommitCheckStatus(committish=committish, ci_status=status)


@project_deployments_router.post('', status_code=202)
async def trigger_deployment(
    org_slug: str,
    project_id: str,
    body: DeploymentRequestBody,
    background: fastapi.BackgroundTasks,
    db: graph.Pool,
    valkey_client: OptionalValkeyClient,
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
            valkey_client=valkey_client,
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


class DeploymentResyncEnqueueResponse(pydantic.BaseModel):
    """Result of enqueueing a deployment resync."""

    enqueued: bool


@project_deployments_router.post('/resync', status_code=202)
async def resync_project_deployments(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    valkey_client: OptionalValkeyClient,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:deployment:write'),
        ),
    ],
    source: str | None = None,
    limit: int = fastapi.Query(default=1, ge=1, le=100),
) -> DeploymentResyncEnqueueResponse:
    """Enqueue a backfill of Release nodes + DEPLOYED_TO edges.

    The worker asks the project's deployment plugin for the most recent
    ``limit`` deployments per environment, upserts any missing
    ``Release`` nodes, and dedup-appends ``DeploymentEvent`` rows so the
    badges advance even when the gateway webhook flow has lapsed.  A
    deep backfill makes hundreds of remote API calls, so the work runs
    as a Valkey-stream job; poll ``GET /deployments/sync-status`` for
    the outcome.  No ``operations_log`` audit row is written -- the
    ``DEPLOYED_TO`` edge already carries the original creator via
    ``DeploymentEvent.performed_by``.

    ``limit`` defaults to 1 (cheap webhook-lapse catch-up).  Raise it
    (up to 100, the GitHub per-page ceiling) for a deeper backfill that
    re-resolves ``performed_by`` on historical events -- e.g. to fix
    stale deploy attribution after a user links their identity.

    Surfaces 400 when the project's deployment plugin does not
    advertise ``supports_deployment_sync`` -- callers should hide the
    button using the plugin manifest flag.  Returns ``enqueued=False``
    when the job was debounced or Valkey is unavailable.
    """
    resolved = await resolve_capability(db, project_id, 'deployment', source)
    _require_deployment_sync_support(resolved)
    requested_by = auth.principal_name
    # Captured before the XADD: every worker write for this job lands
    # after the enqueue, so guarding the optimistic ``queued`` on this
    # timestamp keeps it from clobbering a worker that already advanced
    # (or even finished) the run before this write executes.
    enqueued_at = deployment_sync_service.now_iso()
    enqueued = await deployment_sync_queue.enqueue_deployment_sync(
        valkey_client, org_slug, project_id, requested_by, limit=limit
    )
    if enqueued:
        # Optimistic, best-effort: if the worker has already flipped the
        # project to ``running``, that newer write must win -- so this
        # one does not retry the concurrent-update conflict and skips
        # the write entirely once ``deployment_sync_at`` has advanced
        # past the enqueue time.
        await deployment_sync_service.set_status(
            db,
            project_id,
            status='queued',
            requested_by=requested_by,
            retry=False,
            only_if_before=enqueued_at,
        )
    return DeploymentResyncEnqueueResponse(enqueued=enqueued)


@project_deployments_router.get('/sync-status')
async def get_deployment_sync_status(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:deployment:read'),
        ),
    ],
) -> deployment_sync_service.DeploymentSyncStatus:
    """Return the project's last deployment-resync state."""
    del org_slug
    return await deployment_sync_service.read_status(db, project_id)


@project_deployments_router.get('/promote-status')
async def get_promote_status(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:deployment:read'),
        ),
    ],
) -> release_promote_service.PromoteStatus:
    """Return the project's in-flight (or last) promote state.

    The dispatch-driven promote returns as soon as the Release workflow is
    dispatched, so this is how the UI follows the rest: ``building`` while
    the artifact builds, ``deploying`` while the Deployment Imbi created
    rolls out, then ``success`` once that rollout reports success.

    Three ways it can end short of that, differing in what the operator
    has to do next: ``build_failed`` blocks the release (fix the build and
    promote a bumped version, or unblock to retry); ``deploy_failed``
    leaves the tag shippable (redeploy it once the cause is fixed);
    ``failed`` means Imbi lost track of the build or the rollout, so the
    outcome is unknown and the tag is likewise left shippable.
    """
    del org_slug
    return await release_promote_service.read_status(db, project_id)


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
    # Refuse before touching the plugin: a blocked release must not reach
    # the remote at all, and the check is a single graph read.
    await _assert_not_blocked(
        db,
        project_id,
        tag=body.ref_label,
        committish=body.committish[:7].lower(),
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
        appended = await append_deployment_event(
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
        if not isinstance(appended, str):
            result = appended
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
        plugin_id=resolved.integration_id,
        plugin_slug=resolved.plugin_slug,
        recorded=result is not None,
    )


async def _cut_tag(
    db: graph.Graph,
    *,
    ctx: PluginContext,
    resolved: ResolvedCapability,
    handler: DeploymentCapability,
    credentials: dict[str, str],
    auth: permissions.AuthContext,
    from_committish: str,
    tag: str,
    tag_message: str,
    warnings: list[str],
    project_id: str,
    log_context: str = '',
) -> None:
    """Cut a git tag at ``from_committish`` on the remote.

    The first half of cutting a release.  A plugin with no ``create_tag``
    is a 400 -- the action is simply unavailable -- but a remote failure
    degrades to a warning appended to ``warnings`` rather than raising,
    so a flaky GitHub API doesn't bury the audit trail.  A 422
    "already exists" is the idempotent re-run and is not a warning.
    ``log_context`` is an opaque label (e.g. the target env, or
    ``'release-cut'``) used only in log lines.
    """

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


async def _create_remote_release(
    db: graph.Graph,
    *,
    ctx: PluginContext,
    resolved: ResolvedCapability,
    handler: DeploymentCapability,
    credentials: dict[str, str],
    auth: permissions.AuthContext,
    tag: str,
    release_name: str | None,
    release_notes_markdown: str,
    prerelease: bool,
    warnings: list[str],
    project_id: str,
    log_context: str = '',
) -> typing.Any:
    """Create the release on the remote for an already-cut ``tag``.

    The second half of cutting a release, split out so a promote can
    defer it until the rollout succeeds (see :func:`publish_release`).
    Returns the plugin-returned ``ReleaseInfo`` on success, or ``None``
    when the plugin has no ``create_release``, the release already
    exists, or the call failed (in which case a warning is appended).
    """

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


async def _cut_tag_and_release(
    db: graph.Graph,
    *,
    ctx: PluginContext,
    resolved: ResolvedCapability,
    handler: DeploymentCapability,
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
    """Cut a git tag *and* create its release at ``from_committish``.

    Backs the library ``releases/cut`` action, where there is no
    deployment to gate the release on so both halves run in one step.
    ``promote`` deliberately does *not* use this: it cuts the tag now
    (:func:`_cut_tag`) and defers the release to :func:`publish_release`.
    """
    await _cut_tag(
        db,
        ctx=ctx,
        resolved=resolved,
        handler=handler,
        credentials=credentials,
        auth=auth,
        from_committish=from_committish,
        tag=tag,
        tag_message=release_name or tag,
        warnings=warnings,
        project_id=project_id,
        log_context=log_context,
    )
    return await _create_remote_release(
        db,
        ctx=ctx,
        resolved=resolved,
        handler=handler,
        credentials=credentials,
        auth=auth,
        tag=tag,
        release_name=release_name,
        release_notes_markdown=release_notes_markdown,
        prerelease=prerelease,
        warnings=warnings,
        project_id=project_id,
        log_context=log_context,
    )


async def _promote_cut_tag(
    db: graph.Graph,
    *,
    ctx: PluginContext,
    resolved: ResolvedCapability,
    handler: DeploymentCapability,
    credentials: dict[str, str],
    auth: permissions.AuthContext,
    body: PromoteActionRequest,
    warnings: list[str],
    project_id: str,
) -> None:
    """Cut the promote's tag; the release is published after the rollout.

    Promote creates the git tag and stops there.  The GitHub Release is
    the *ratification* of a release that actually shipped, so it is
    published from the ``deployment_status`` webhook once the deploy
    reports success -- and a failed rollout leaves a blocked release
    rather than a ratified one.
    """
    await _cut_tag(
        db,
        ctx=ctx,
        resolved=resolved,
        handler=handler,
        credentials=credentials,
        auth=auth,
        from_committish=body.from_committish,
        tag=body.tag,
        tag_message=body.release_name or body.tag,
        warnings=warnings,
        project_id=project_id,
        log_context=body.to_environment,
    )


#: Inputs ``release.yml`` declares.  The shared ``release-tag.yaml``
#: treats an empty ``commit`` as "release the tip of the default branch",
#: so omitting it would silently tag something other than the build being
#: promoted -- a green release of the wrong tree.  ``create_deployment``
#: is the D6 seam from ENG-101: the workflow stops creating the
#: Deployment once Imbi does.
#:
#: Only the first three are universal.  ``environment`` and
#: ``create_deployment`` are declared by the workflow a *deployable*
#: project dispatches; the releasable (library / image) variant drops
#: both, so :func:`_dispatch_release_build` gates them on the project
#: type's ``deployable`` flag.
_RELEASE_WORKFLOW_DESCRIPTION_INPUT = 'description'
_RELEASE_WORKFLOW_NOTES_INPUT = 'release_notes'
_RELEASE_WORKFLOW_COMMIT_INPUT = 'commit'
_RELEASE_WORKFLOW_ENVIRONMENT_INPUT = 'environment'
_RELEASE_WORKFLOW_CREATE_DEPLOYMENT_INPUT = 'create_deployment'


async def _default_branch(
    handler: DeploymentCapability,
    ctx: PluginContext,
    credentials: dict[str, str],
) -> str | None:
    """The repo's default branch, for use as a dispatch ref.

    ``workflow_dispatch`` resolves the workflow file on the ref it is
    given, and a freshly-promoted tag does not exist yet -- the workflow
    is what creates it.  So the dispatch runs from the default branch and
    the workflow checks out the version itself.
    """
    refs = await _best_effort(
        handler.list_refs(ctx, credentials, kind='default'),
        f'list_refs kind=default for project {ctx.project_id}',
    )
    for ref in refs or []:
        if ref.name:
            return ref.name
    return None


class _DispatchedBuild(typing.NamedTuple):
    """What :func:`_dispatch_release_build` leaves behind."""

    release_id: str
    artifact: plugin_base.ArtifactRun
    #: ``True`` when a watcher was queued.  ``False`` means the build runs
    #: but nothing will finish the promote.
    watched: bool
    warning: str | None


async def _dispatch_release_build(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
    auth: permissions.AuthContext,
    *,
    resolved: ResolvedCapability,
    ctx: PluginContext,
    credentials: dict[str, str],
    handler: DeploymentCapability,
    valkey_client: typing.Any,
    tag: str,
    committish: str,
    title: str,
    notes_markdown: str,
    to_environment: str = '',
    from_environment: str = '',
    deploy: bool,
    ci_status: plugin_base.CheckStatus = 'unknown',
) -> _DispatchedBuild:
    """Record the release, dispatch its build, and queue the watcher.

    Shared by the promote and the release-cut paths -- they differ only in
    whether a deployment follows, which the watcher reads off
    ``deploy``.

    The ``Release`` node is written *before* the dispatch on purpose: a
    build that fails needs something to block, and the node keyed on
    ``(tag, committish)`` is that something.  So a node can exist for a
    tag the remote never carries; the block and its reason are what
    distinguish that from a shipped release.

    That reasoning only covers failures *after* the dispatch, though, so
    everything that can fail before it runs first.  A 502 here used to
    leave a node behind that no dispatch, no block, and no promote status
    explained -- and one that still matched the ``(tag, committish)``
    gates in :func:`_blocked_release`.
    """
    ref = await _default_branch(handler, ctx, credentials)
    if ref is None:
        raise fastapi.HTTPException(
            status_code=502,
            detail=(
                "Could not resolve the repository's default branch, which "
                'is the ref the Release workflow must be dispatched from.'
            ),
        )
    release_id = await _upsert_release_node(
        db,
        project_id=project_id,
        tag=tag,
        committish=committish,
        title=title,
        notes_markdown=notes_markdown,
        release_url=None,
        created_by=auth.principal_name,
    )
    # Stamped before the dispatch, for the same reason the node itself is:
    # the decision to ship a red commit has to outlive a build that fails.
    await _set_release_ci_override(
        db,
        project_id=project_id,
        release_id=release_id,
        ci_status=ci_status,
        overridden_by=auth.principal_name,
    )
    inputs = {
        _RELEASE_WORKFLOW_DESCRIPTION_INPUT: title,
        _RELEASE_WORKFLOW_NOTES_INPUT: notes_markdown,
        # Never omitted: release-tag.yaml reads an empty ``commit`` as
        # "release the tip of the default branch".
        _RELEASE_WORKFLOW_COMMIT_INPUT: committish,
    }
    # The deployment inputs exist only in the workflow a deployable
    # project dispatches.  A releasable project's workflow declares
    # neither -- publishing *is* its release, so it has no deployment
    # seam to close -- and workflow_dispatch rejects the whole call with
    # a 422 when it is handed an input the workflow does not declare.
    if await _project_is_deployable(db, project_id):
        inputs[_RELEASE_WORKFLOW_CREATE_DEPLOYMENT_INPUT] = 'false'
        if to_environment:
            inputs[_RELEASE_WORKFLOW_ENVIRONMENT_INPUT] = to_environment

    async def _dispatch(c: PluginContext) -> plugin_base.ArtifactRun:
        return await call_with_timeout(
            handler.create_deployment_artifact(
                c,
                _resolve_credentials(c, credentials),
                ref=ref,
                version=tag,
                inputs=inputs,
            )
        )

    try:
        artifact = await call_with_identity_retry(
            db, ctx, resolved, auth, fn=_dispatch, attached=True
        )
    except NotImplementedError as exc:
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                f'Plugin {resolved.plugin_slug!r} cannot dispatch a release '
                'workflow; clear the Release workflow option to fall back '
                'to cutting the tag directly.'
            ),
        ) from exc
    await persist_link_writeback(db, ctx)

    job = release_promote_service.WatchJob(
        org_slug=org_slug,
        project_id=project_id,
        release_id=release_id,
        tag=tag,
        committish=committish,
        to_environment=to_environment,
        from_environment=from_environment,
        run_id=artifact.run_id or '',
        run_url=artifact.run_url or '',
        requested_by=auth.principal_name,
        deploy=deploy,
    )
    watched = bool(artifact.run_id) and (
        await release_promote_queue.enqueue_release_promote(valkey_client, job)
    )
    warning: str | None = None
    if not artifact.run_id:
        warning = (
            'The release workflow was dispatched but the remote did not '
            'report a run id, so Imbi cannot watch the build. Finish the '
            'release from the workflow run once it is green.'
        )
    elif not watched:
        warning = (
            'The release build is running, but Imbi could not queue a '
            'watcher for it and will not finish the release automatically.'
        )
    await release_promote_service.set_status(
        db,
        project_id,
        status='building' if watched else 'failed',
        tag=tag,
        committish=committish,
        environment=to_environment,
        from_environment=from_environment,
        artifact_run_id=artifact.run_id or '',
        artifact_run_url=artifact.run_url or '',
        requested_by=auth.principal_name,
        error=warning or '',
    )
    LOGGER.info(
        'Release workflow dispatched: project=%s %s->%s tag=%s commit=%s '
        'plugin=%s actor=%s run_id=%s deploy=%s watched=%s',
        project_id,
        from_environment or '-',
        to_environment or '-',
        tag,
        committish,
        resolved.plugin_slug,
        ctx.actor_user_id,
        artifact.run_id,
        deploy,
        watched,
    )
    return _DispatchedBuild(release_id, artifact, watched, warning)


async def _promote_via_dispatch(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
    auth: permissions.AuthContext,
    body: PromoteActionRequest,
    *,
    resolved: ResolvedCapability,
    ctx: PluginContext,
    credentials: dict[str, str],
    handler: DeploymentCapability,
    valkey_client: typing.Any,
    ci_status: plugin_base.CheckStatus = 'unknown',
) -> DeploymentTriggerResponse:
    """Dispatch the project's Release workflow instead of cutting the tag.

    The workflow creates the annotated tag and the remote Release, so Imbi
    does neither here; the deployment follows once the build is green.
    """
    built = await _dispatch_release_build(
        db,
        org_slug,
        project_id,
        auth,
        resolved=resolved,
        ctx=ctx,
        credentials=credentials,
        handler=handler,
        valkey_client=valkey_client,
        tag=body.tag,
        committish=versioning.short_committish(body.from_committish),
        title=body.release_name or body.tag,
        notes_markdown=body.release_notes_markdown,
        to_environment=body.to_environment,
        from_environment=body.from_environment,
        deploy=await _project_is_deployable(db, project_id),
        ci_status=ci_status,
    )
    return DeploymentTriggerResponse(
        run=DeploymentRun(run_id='', status='queued'),
        plugin_id=resolved.integration_id,
        plugin_slug=resolved.plugin_slug,
        recorded=True,
        tag=body.tag,
        phase='building',
        artifact_run_id=built.artifact.run_id,
        artifact_run_url=built.artifact.run_url,
        watched=built.watched,
        warning=built.warning,
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
    valkey_client: typing.Any = None,
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

    # ``body.tag`` may name an existing release (promote-from-tag) or a SHA
    # a new tag gets cut at; ``from_committish`` is the build being
    # promoted.  Either identity resolving to a blocked release stops the
    # promote, so blocking a rolled-back tag also stops it being re-cut
    # from the same commit.
    await _assert_not_blocked(
        db,
        project_id,
        tag=body.tag,
        committish=body.from_committish[:7].lower(),
    )

    # Infer promote behaviour from the ref shape of ``body.tag``:
    #
    # * Matches a configured tag format (or, with none configured, any
    #   non-SHA ref) -> already a tag.  Skip ``create_tag`` +
    #   ``create_release``; call ``trigger_deployment`` so the repo's
    #   ``on: deployment`` workflow fires.  This is the "promote to prod
    #   from a stage release tag" path.
    # * Git short/full SHA                       -> cut a tag at the SHA
    #   and dispatch against it.  This is the "first promote off a build
    #   commit" path.  No GitHub Release is created here; publishing it
    #   is deferred until the rollout succeeds.
    # * A ref that fails a configured tag format  -> 400.  We refuse to
    #   silently cut a tag that violates the org/project-type policy; a
    #   typo at the API boundary should fail loudly.
    tag_formats = await _resolve_tag_formats(db, org_slug, project_id)
    patterns = [fmt.pattern for fmt in tag_formats]
    if not versioning.matches_tag_formats(
        body.tag, patterns
    ) and not versioning.is_commitish(body.tag):
        allowed = ', '.join(fmt.label for fmt in tag_formats)
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                f'Promote target {body.tag!r} does not match any configured '
                f'tag format ({allowed}) and is not a git SHA (7-40 hex '
                'chars); refusing to cut a tag at an ambiguous ref.'
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

    # Last gate before anything irreversible: no tag has been cut and no
    # build dispatched yet, so a 409 here leaves nothing to clean up and
    # the client can simply resubmit with the acknowledgement set.
    ci_status = await _assert_ci_not_failing(
        handler,
        ctx,
        credentials,
        committish=body.from_committish,
        acknowledged=body.acknowledge_ci_failure,
        action='promote',
    )

    # A project with a Release workflow configured takes the
    # dispatch-and-watch path: the workflow builds the artifact, cuts the
    # annotated tag and creates the remote Release, and only then does
    # Imbi deploy.  Nothing below this point runs for those projects.
    #
    # With the option blank, keep cutting the tag inline and ratifying the
    # Release from the deployment_status webhook (ENG-101).  That is the
    # right behaviour for a project whose artifacts are built outside
    # Imbi -- there is no build to wait on.
    if str(resolved.capability_options.get('artifact_workflow') or '').strip():
        return await _promote_via_dispatch(
            db,
            org_slug,
            project_id,
            auth,
            body,
            resolved=resolved,
            ctx=ctx,
            credentials=credentials,
            handler=handler,
            valkey_client=valkey_client,
            ci_status=ci_status,
        )

    warnings: list[str] = []
    run = DeploymentRun(run_id='', status='queued')
    # The GitHub Release is published by ``publish_release`` once the
    # rollout reports success, so a promote never returns a release URL.
    release_url: str | None = None

    await _promote_cut_tag(
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
            plugin_id=resolved.integration_id,
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
    await _set_release_ci_override(
        db,
        project_id=project_id,
        release_id=release_id,
        ci_status=ci_status,
        overridden_by=auth.principal_name,
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
        ci_status=ci_status,
        ci_override=ci_status == 'fail',
    )
    return DeploymentTriggerResponse(
        run=run,
        plugin_id=resolved.integration_id,
        plugin_slug=resolved.plugin_slug,
        recorded=not isinstance(promote_result, str),
        release_url=release_url,
        tag=body.tag,
        warning='; '.join(warnings) if warnings else None,
    )


# The upsert below is one statement so concurrent writers (promote,
# webhook, resync) cannot interleave a check with an act -- that race is
# how duplicate Release nodes accumulated.  It narrows that window
# rather than closing it: AGE has no unique constraint to fall back on,
# so two transactions that cannot yet see each other's row can still
# both MERGE-create the same ``(project, tag)``.  Surfacing that
# residual duplicate is what the multi-node warning in
# ``_release_id_for`` is for.
#
# AGE also has no ``ON CREATE SET``
# / ``ON MATCH SET``, so create-only properties go through ``coalesce``.
#
# Never overwrite existing data with nothing: an empty ``description``
# (no notes could be resolved) or an empty ``links`` (no release URL)
# preserves whatever the node already holds.  Without this guard a
# resync that can't fetch notes would wipe the "What's Changed" body a
# promote (or an earlier enriched create) had already written.
#
# ``created_by`` is refreshed only in one direction: a node still
# credited to a background worker takes the real author when one is
# known, but a person already recorded is never overwritten (including
# by a later worker-driven pass).
_RELEASE_UPSERT_SET: typing.Final[typing.LiteralString] = """
    SET r.id = COALESCE(r.id, {id}),
        r.committish = COALESCE(r.committish, {committish}),
        r.title = COALESCE(r.title, {title}),
        r.created_at = COALESCE(r.created_at, {now}),
        r.description = CASE WHEN {description} = ''
            THEN r.description ELSE {description} END,
        r.links = CASE WHEN {links} = '[]' THEN r.links ELSE {links} END,
        r.created_by = CASE WHEN {author} <> ''
                AND COALESCE(r.created_by, '') IN {synthetic}
            THEN {author} ELSE COALESCE(r.created_by, {created_by}) END,
        r.updated_at = {now}
    RETURN r.id AS rid
"""

# Identity is the tag: it names one shippable artifact, while the commit
# it points at moves (the release workflow bumps the version, then tags
# the bump commit).  Keying on the committish is what let the post-bump
# SHA miss the node Imbi had already created.
_RELEASE_UPSERT_BY_TAG: typing.Final[typing.LiteralString] = """
    MATCH (p:Project {{id: {project_id}}})
    MERGE (p)-[:HAS_RELEASE]->(r:Release {{tag: {tag}}})
"""

# An untagged release has only its commit to be identified by.  The
# guard lives in the caller, not here: MERGE matches on a subset of a
# node's properties, so this pattern *would* match a tagged Release
# carrying the same committish (verified against a live AGE instance --
# it returns that node and leaves its tag intact rather than creating an
# untagged sibling).  The one caller that can reach this branch (resync)
# resolves an existing tag for the committish first, so it runs only
# when no tagged Release on the project claims that commit.  AGE cannot
# express "and no tag" in a MERGE pattern -- an untagged node has no
# ``tag`` property at all -- so the predicate cannot move in here.
_RELEASE_UPSERT_BY_COMMITTISH: typing.Final[typing.LiteralString] = """
    MATCH (p:Project {{id: {project_id}}})
    MERGE (p)-[:HAS_RELEASE]->(r:Release {{committish: {committish}}})
"""


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

    Identity is ``(project, tag)`` whenever a tag exists, with the
    committish a mutable attribute: re-promoting or re-observing the
    same tag refreshes the one node instead of spawning a sibling.  An
    untagged release falls back to ``(project, committish)``.  Returns
    the resulting ``Release.id``.

    The committish is normalized to the short, lowercase form here rather
    than trusted from the caller: it is what the untagged lookup matches
    on and what the release history displays, so one writer passing a
    full SHA yields a node nothing can match.
    """
    committish = versioning.short_committish(committish)
    now = datetime.datetime.now(datetime.UTC).isoformat()
    links_json = (
        json.dumps([{'type': 'github_release', 'url': release_url}])
        if release_url
        else json.dumps([])
    )
    new_id: str = nanoid.generate()
    query: typing.LiteralString = (
        _RELEASE_UPSERT_BY_TAG if tag else _RELEASE_UPSERT_BY_COMMITTISH
    ) + _RELEASE_UPSERT_SET
    rows = await db.execute(
        query,
        {
            'project_id': project_id,
            'committish': committish,
            'tag': tag,
            'id': new_id,
            'title': title,
            'description': notes_markdown,
            'links': links_json,
            'created_by': created_by,
            'author': (
                ''
                if principals.is_process_principal(created_by)
                else created_by
            ),
            'synthetic': [*sorted(principals.PROCESS_PRINCIPALS), ''],
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
# Dispatch-driven promote: completion path
#
# ``_handle_promote`` dispatches the project's Release workflow and returns.
# The functions below are what ``imbi.api.release_promote.service`` calls once
# that build reaches a terminal state -- they live here so every graph write
# and plugin call for the promote flow stays in one module, the same way
# ``deployment_sync.service`` defers to ``resync_for_project``.
#
# All of them run under the watcher's process principal, which has no per-user
# identity connection, so they resolve context with
# ``best_effort_identity=True`` and act with the Integration's own service
# credential.  The promoting user is carried separately, as ``requested_by``,
# and reaches the ``DeploymentEvent`` and the ``operations_log`` row -- a
# promote is something a person did, and losing that would leave the activity
# history crediting a worker.
# ---------------------------------------------------------------------------


def _watcher_auth() -> permissions.AuthContext:
    """The synthetic principal the promote watcher acts under."""
    return principals.system_auth(
        principals.RELEASE_PROMOTE, 'Imbi Release Promote'
    )


async def _project_is_deployable(db: graph.Graph, project_id: str) -> bool:
    """True when any of the project's types is ``deployable``.

    A project can carry more than one ``ProjectType``, so this aggregates
    rather than reading one: ``deployable`` XOR ``releasable`` holds per
    type, not per project.  A project with no type at all answers
    ``False`` -- there is nothing to deploy into.
    """
    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
    OPTIONAL MATCH (p)-[:TYPE]->(pt:ProjectType)
    RETURN collect(COALESCE(pt.deployable, false)) AS flags
    """
    rows = await db.execute(query, {'project_id': project_id}, ['flags'])
    if not rows:
        return False
    flags = typing.cast(
        'list[object]', graph.parse_agtype(rows[0].get('flags')) or []
    )
    return any(bool(flag) for flag in flags)


async def poll_artifact_run(
    db: graph.Graph,
    *,
    org_slug: str,
    project_id: str,
    run_id: str,
) -> plugin_base.ArtifactRun:
    """Report the current state of a dispatched release build.

    Wraps ``get_artifact_run_status``, which resolves a *workflow run*
    id.  Deliberately not :func:`get_deployment_run` -- that one resolves
    a GitHub *Deployment* id through a different endpoint, and handing it
    a workflow run id would 404.
    """
    resolved, ctx, credentials = await _resolve_and_context(
        db,
        org_slug,
        project_id,
        _watcher_auth(),
        source=None,
        best_effort_identity=True,
    )
    handler = _handler(resolved)
    return await call_with_timeout(
        handler.get_artifact_run_status(
            ctx, _resolve_credentials(ctx, credentials), run_id=run_id
        )
    )


async def poll_promote_rollout(
    db: graph.Graph,
    *,
    org_slug: str,
    project_id: str,
    run_id: str,
) -> DeploymentRun:
    """Report the current state of a promote's rollout.

    The counterpart to :func:`poll_artifact_run` for the second half of a
    dispatch-driven promote: once the build is green and
    :func:`complete_promote_build` has created the Deployment, this is
    what tells the watcher whether the rollout actually shipped.

    Resolves a *Deployment* id, so it goes through
    ``get_deployment_status`` -- the same split
    :func:`poll_artifact_run` documents, in the other direction.
    Distinct from :func:`get_deployment_run` because that one runs under
    the caller's identity and raises ``HTTPException``; the watcher has
    no per-user identity, so it resolves the Integration's own service
    credential instead.
    """
    resolved, ctx, credentials = await _resolve_and_context(
        db,
        org_slug,
        project_id,
        _watcher_auth(),
        source=None,
        best_effort_identity=True,
    )
    handler = _handler(resolved)
    return await call_with_timeout(
        handler.get_deployment_status(
            ctx, _resolve_credentials(ctx, credentials), run_id=run_id
        )
    )


async def fail_promote_build(
    db: graph.Graph,
    *,
    org_slug: str,
    project_id: str,
    tag: str,
    reason: str,
    requested_by: str = '',
) -> None:
    """Block ``tag`` after its release build failed.

    Scoped to the tag (see :func:`_set_release_block`): the build failed
    for this version, and the ordinary fix is to promote a bumped version
    off the same commit, which a commit-wide block would refuse.
    """
    blocked = await _set_release_block(
        db,
        org_slug=org_slug,
        project_id=project_id,
        tag=tag,
        blocked_at=datetime.datetime.now(datetime.UTC).isoformat(),
        blocked_by=requested_by or principals.RELEASE_PROMOTE,
        reason=reason[:500],
        scope='tag',
    )
    if not blocked:
        # The promote creates the node before dispatching, so this means
        # someone deleted it mid-build.  Nothing to block; the warning is
        # the whole remedy.
        LOGGER.warning(
            'release-promote could not block tag %s on project %s: no '
            'Release node found',
            tag,
            project_id,
        )
        return
    LOGGER.info(
        'release-promote blocked tag %s on project %s: %s',
        tag,
        project_id,
        reason,
    )


async def _set_release_committish(
    db: graph.Graph,
    *,
    release_id: str,
    committish: str,
) -> None:
    """Point a ``Release`` at the commit its tag actually resolves to.

    The committish is an attribute, not the identity -- the tag is --
    so healing it here is what makes the deployment webhook's later
    lookup (which carries the post-bump SHA) find this node instead of
    creating a duplicate.
    """
    query: typing.LiteralString = """
    MATCH (r:Release {{id: {release_id}}})
    SET r.committish = {committish},
        r.updated_at = {now}
    """
    await db.execute(
        query,
        {
            'release_id': release_id,
            'committish': committish,
            'now': datetime.datetime.now(datetime.UTC).isoformat(),
        },
        [],
    )


async def _set_release_artifact_run(
    db: graph.Graph,
    *,
    project_id: str,
    release_id: str,
    run_id: str,
    run_url: str | None,
) -> None:
    """Record which workflow run built a release.

    Kept off :func:`_upsert_release_node` on purpose: that function is
    also the resync's writer, and resync observes deployments rather than
    builds, so it has no run id to contribute and should not have to pass
    a placeholder.
    """
    query: typing.LiteralString = """
    MATCH (:Project {{id: {project_id}}})
          -[:HAS_RELEASE]->(r:Release {{id: {release_id}}})
    SET r.workflow_run_id = {run_id},
        r.workflow_run_url = {run_url},
        r.updated_at = {now}
    RETURN r.id AS rid
    """
    await db.execute(
        query,
        {
            'project_id': project_id,
            'release_id': release_id,
            'run_id': run_id,
            'run_url': run_url,
            'now': datetime.datetime.now(datetime.UTC).isoformat(),
        },
        ['rid'],
    )


async def _set_release_ci_override(
    db: graph.Graph,
    *,
    project_id: str,
    release_id: str,
    ci_status: plugin_base.CheckStatus,
    overridden_by: str,
) -> None:
    """Record the CI status a release was cut against.

    ``ci_status == 'fail'`` is exactly the case an operator had to
    acknowledge to get here -- :func:`_assert_ci_not_failing` refuses it
    otherwise -- so the actor and timestamp are stamped on that and only
    that.  The status itself is recorded either way, because "shipped
    green" and "shipped without CI ever having run" are different facts
    and a blank property could not tell them apart.

    Written here, at promote time, rather than only folded into the
    ``operations_log`` row: on the dispatch path that row is written by the
    watcher *after* a green build, so an override whose release build then
    failed would otherwise leave no trace of the decision anywhere.

    Kept off :func:`_upsert_release_node` for the same reason
    :func:`_set_release_artifact_run` is -- that function is also the
    resync's writer, and resync observes deployments, not CI.
    """
    overridden = ci_status == 'fail'
    now = datetime.datetime.now(datetime.UTC).isoformat()
    query: typing.LiteralString = """
    MATCH (:Project {{id: {project_id}}})
          -[:HAS_RELEASE]->(r:Release {{id: {release_id}}})
    SET r.ci_status_at_promote = {ci_status},
        r.updated_at = {now}
    RETURN r.id AS rid
    """
    await db.execute(
        query,
        {
            'project_id': project_id,
            'release_id': release_id,
            'ci_status': ci_status,
            'now': now,
        },
        ['rid'],
    )
    if not overridden:
        return
    # Only ever written, never blanked.  ``_upsert_release_node`` keys on
    # ``(project, committish, tag)``, so re-promoting one tag lands on the
    # same node and runs this a second time -- and a CI re-run that turns
    # the commit green makes that the expected sequence.  Clearing the
    # actor on that pass would erase the acknowledgement someone actually
    # made, dropping the override badge from release history and making
    # :func:`_release_ci_override` report a clean promote for a release
    # that shipped over a failing build.
    override_query: typing.LiteralString = """
    MATCH (:Project {{id: {project_id}}})
          -[:HAS_RELEASE]->(r:Release {{id: {release_id}}})
    SET r.ci_override_by = {overridden_by},
        r.ci_override_at = {overridden_at}
    RETURN r.id AS rid
    """
    await db.execute(
        override_query,
        {
            'project_id': project_id,
            'release_id': release_id,
            'overridden_by': overridden_by,
            'overridden_at': now,
        },
        ['rid'],
    )


async def _release_ci_override(
    db: graph.Graph,
    *,
    project_id: str,
    release_id: str,
) -> tuple[str, bool]:
    """Read back ``(ci_status_at_promote, was_overridden)`` for a release.

    Lets the dispatch path's audit row carry the promote-time CI decision
    without threading it through the serialized ``WatchJob`` -- the
    ``Release`` node stamped by :func:`_set_release_ci_override` stays the
    single source of truth, and a node written by an older build (no such
    properties) reads as ``('unknown', False)``.
    """
    query: typing.LiteralString = """
    MATCH (:Project {{id: {project_id}}})
          -[:HAS_RELEASE]->(r:Release {{id: {release_id}}})
    RETURN r.ci_status_at_promote AS ci_status,
           r.ci_override_by AS overridden_by
    """
    try:
        rows = await db.execute(
            query,
            {'project_id': project_id, 'release_id': release_id},
            ['ci_status', 'overridden_by'],
        )
    except Exception:  # noqa: BLE001
        LOGGER.debug(
            'CI override read failed for release %s', release_id, exc_info=True
        )
        return 'unknown', False
    if not rows:
        return 'unknown', False
    status = graph.parse_agtype(rows[0].get('ci_status'))
    overridden_by = graph.parse_agtype(rows[0].get('overridden_by'))
    return str(status) if status else 'unknown', bool(overridden_by)


async def _sync_promoted_tag(
    db: graph.Graph,
    *,
    org_slug: str,
    project_id: str,
    tag: str,
    valkey_client: typing.Any,
) -> None:
    """Feed the tag the release build created to ClickHouse.

    ENG-100 F6: an API-created tag fires no ``push`` event, so
    ``github#sync_tags`` never runs and the tag is missing from the
    ``tags`` table -- and therefore from release history and the Releases
    tab -- until something asks for it.

    Records that one tag directly, because the caller knows which tag
    appeared: three remote calls, where the queued backfill re-peels every
    tag the repo already carries.  Falls back to that backfill when the
    bounded path can't run (no commit-sync capability, or one that syncs
    only full history) -- and, either way, degrades quietly: a tag that
    lands late delays the Releases tab, it does not fail the promote.
    """
    written = await _best_effort(
        commit_sync_service.run_tag_sync(db, org_slug, project_id, tag),
        f'sync tag {tag} for project {project_id}',
    )
    if written is not None:
        LOGGER.info(
            'release-promote recorded %d tag row(s) for project %s tag %s',
            written,
            project_id,
            tag,
        )
        return
    if not await commit_sync_queue.enqueue_commit_sync(
        valkey_client, org_slug, project_id, principals.RELEASE_PROMOTE
    ):
        LOGGER.info(
            'release-promote could not enqueue a tag resync for project %s; '
            'tag %s stays absent from ClickHouse until the next sync',
            project_id,
            tag,
        )


async def complete_promote_build(
    db: graph.Graph,
    *,
    org_slug: str,
    project_id: str,
    release_id: str,
    tag: str,
    committish: str,
    to_environment: str,
    from_environment: str = '',
    requested_by: str = '',
    run_id: str = '',
    run_url: str | None = None,
    deploy: bool = True,
    valkey_client: typing.Any = None,
) -> DeploymentRun | None:
    """Finish a promote whose release build succeeded.

    The build created the annotated tag and the remote Release, so this
    reconciles Imbi with what now exists and then ships it:

    1. Resolve what the tag actually points at, and warn on disagreement.
    2. Refresh the ``Release`` node with the remote release link and the
       run that built it.
    3. Record the new tag in ClickHouse -- an API-created tag fires no
       ``push`` event, so ``github#sync_tags`` never runs and the tag is
       missing from the ``tags`` table (and therefore from release-history
       and the Releases tab) until something asks for it.
    4. For a deployable project, create the Deployment and record the
       event.  A releasable-only project stops after step 3: there is
       nothing to deploy into.

    Returns the Deployment it created so the caller can watch the
    rollout, or ``None`` for a releasable-only project.  Creating the
    Deployment is *not* the end of the promote -- the rollout it starts
    is what the user is waiting on -- so this deliberately hands the run
    back rather than reporting success on its own behalf.
    """
    resolved, ctx, credentials = await _resolve_and_context(
        db,
        org_slug,
        project_id,
        _watcher_auth(),
        source=None,
        environment=to_environment or None,
        best_effort_identity=True,
    )
    handler = _handler(resolved)
    creds = _resolve_credentials(ctx, credentials)

    tagged = await _best_effort(
        handler.resolve_committish(ctx, creds, committish=tag),
        f'resolve tag {tag} for project {project_id}',
    )
    if tagged is not None:
        actual = versioning.short_committish(tagged.sha)
        if actual != versioning.short_committish(committish):
            # Imbi created the Release node keyed on the commit it asked
            # to tag, but the release workflow bumps the version and tags
            # the bump commit, so the tag routinely points somewhere
            # else.  Adopt what the tag actually resolves to: the tag is
            # the node's identity, edges hang off the node rather than
            # off ``committish``, and every later correlation (the
            # gateway's deployment_status lookup above all) arrives
            # carrying the post-bump SHA.
            LOGGER.info(
                'release-promote: tag %s on project %s points at %s, not '
                'the promoted commit %s; updating the Release committish',
                tag,
                project_id,
                actual,
                committish,
            )
            await _set_release_committish(
                db, release_id=release_id, committish=actual
            )
            committish = actual

    remote = await _get_release(handler, ctx, creds, tag)
    release_url = remote.html_url if remote else None
    if release_url:
        await _upsert_release_node(
            db,
            project_id=project_id,
            tag=tag,
            committish=committish,
            title=tag,
            # Empty preserves the notes the promote already wrote; this
            # call exists to attach the remote release link.
            notes_markdown='',
            release_url=release_url,
            created_by=principals.RELEASE_PROMOTE,
        )
    if run_id:
        await _set_release_artifact_run(
            db,
            project_id=project_id,
            release_id=release_id,
            run_id=run_id,
            run_url=run_url,
        )
    await persist_link_writeback(db, ctx)

    await _sync_promoted_tag(
        db,
        org_slug=org_slug,
        project_id=project_id,
        tag=tag,
        valkey_client=valkey_client,
    )

    if not deploy:
        LOGGER.info(
            'release-promote finished build-only release %s for project %s',
            tag,
            project_id,
        )
        return None

    inputs: dict[str, str] | None = None
    if ctx.environment_config:
        inputs = {
            key: value if isinstance(value, str) else json.dumps(value)
            for key, value in ctx.environment_config.items()
        }
    run = await call_with_timeout(
        handler.trigger_deployment(ctx, creds, ref_or_sha=tag, inputs=inputs)
    )
    LOGGER.info(
        'release-promote deployment triggered: project=%s env=%s tag=%s '
        'plugin=%s run_id=%s',
        project_id,
        to_environment,
        tag,
        resolved.plugin_slug,
        run.run_id,
    )
    appended = await append_deployment_event(
        db,
        org_slug=org_slug,
        project_id=project_id,
        release_id=release_id,
        env_slug=to_environment,
        status='in_progress',
        note=f'via {resolved.plugin_slug}',
        external_run_id=str(run.run_id) if run.run_id else None,
        external_run_url=run.run_url,
        # The person who pressed promote, not the worker that got here.
        performed_by=requested_by or None,
    )
    if isinstance(appended, str):
        LOGGER.warning(
            'release-promote could not record the deployment event for '
            'project %s release %s: %s',
            project_id,
            release_id,
            appended,
        )
    # The CI decision was made (and stamped on the Release node) back when
    # the operator pressed promote, minutes ago; read it back rather than
    # re-asking the plugin, whose answer may have changed since.
    ci_status, ci_override = await _release_ci_override(
        db, project_id=project_id, release_id=release_id
    )
    await _record_deployment_audit(
        project_id=project_id,
        project_slug=ctx.project_slug,
        environment_slug=to_environment,
        recorded_by=requested_by or principals.RELEASE_PROMOTE,
        action='promote',
        tag=tag,
        committish=committish,
        plugin_slug=resolved.plugin_slug,
        run_url=run.run_url,
        external_run_id=str(run.run_id) if run.run_id else None,
        release_url=release_url,
        from_environment=from_environment or None,
        ci_status=ci_status,
        ci_override=ci_override,
    )
    return run


# ---------------------------------------------------------------------------
# Release-notes drafting
# ---------------------------------------------------------------------------

_PROMPT_COMMIT_CAP = 150
_PROMPT_BODY_CAP = 2000
_SEMVER_RE = re.compile(r'^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$')


@functools.cache
def _release_notes_system() -> str:
    return (
        importlib.resources.files('imbi.api.prompts')
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


def _tag_timestamp(
    row: dict[str, typing.Any],
) -> datetime.datetime | None:
    """When a ``tags`` row was published, as an aware UTC timestamp.

    Falls back to ``recorded_at`` for rows synced without a tag date.
    ClickHouse returns these columns naive, so ``as_utc`` tags the offset
    on before Pydantic serializes them.
    """
    return clickhouse.as_utc_or_none(
        row.get('tagged_at') or row.get('recorded_at')
    )


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
    buckets: dict[str, list[str]] = {}
    for commit in commits:
        # Subject only: a body pasted into a bullet breaks the markdown.
        subject = commit.message.split('\n', 1)[0].strip()
        prefix = subject.split(':', 1)[0].lower().strip()
        if not prefix or len(prefix) > 16:
            prefix = 'other'
        buckets.setdefault(prefix, []).append(
            f'- {subject} ({commit.short_sha})'
        )
    lines: list[str] = []
    for prefix in sorted(buckets):
        lines.append(f'### {prefix}')
        lines.extend(buckets[prefix])
        lines.append('')
    return '\n'.join(lines).rstrip()


_BODY_TRUNCATION_MARKER = '\n… (truncated)'


def _truncate_commit_body(body: str) -> str:
    """Cap one commit body so a long one can't crowd out the rest.

    The marker counts against the cap, so the result never exceeds
    ``_PROMPT_BODY_CAP``.
    """
    if len(body) <= _PROMPT_BODY_CAP:
        return body
    keep = _PROMPT_BODY_CAP - len(_BODY_TRUNCATION_MARKER)
    return body[:keep].rstrip() + _BODY_TRUNCATION_MARKER


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
        'Commits (oldest → newest). Indented text under a commit is that '
        "commit's message body:",
    ]
    for commit in capped:
        author = commit.author or 'unknown'
        body_lines.append(f'- {commit.short_sha} {commit.message} — {author}')
        # A squashed PR carries what actually changed in its body, so the
        # subject alone reads as a chore far more often than it is one.
        if commit.body:
            body_lines.append(
                textwrap.indent(
                    _truncate_commit_body(commit.body), '    '
                ).rstrip()
            )
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
    # A body is what ships on the release, so an empty one is never useful:
    # fall back to the deterministic commit-prefix grouping. Reached when
    # every commit in the range reads as excludable to the model.
    if not notes.notes_markdown.strip() and commits:
        notes = notes.model_copy(
            update={'notes_markdown': _fallback_notes(commits)}
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
    author_email = row.get('author_email')
    url = row.get('url')
    return RecentCommit(
        sha=sha,
        short_sha=str(row.get('short_sha') or sha[:7]),
        message=str(row.get('message') or ''),
        author=str(author) if author else None,
        author_email=str(author_email) if author_email else None,
        authored_at=clickhouse.as_utc(row['authored_at']),
        ci_status=str(row.get('ci_status') or 'unknown'),
        url=str(url) if url else None,
    )


class _CommitFacts(typing.NamedTuple):
    """The synced-commit facts a release-history entry is built from."""

    ci_status: str
    author: str | None
    author_email: str | None


async def _commit_facts_by_sha(
    project_id: str, shas: list[str]
) -> dict[str, _CommitFacts]:
    """Map ``sha -> _CommitFacts`` for a bounded sha set, ``{}`` when empty.

    One query for both the CI state and the commit's author: the release
    history needs each per tagged commit, and ``FINAL`` is the expensive
    part.  Uses enumerated string params (the sha list is small and bounded
    by the caller) rather than an Array binding, keeping to the parameter
    features already exercised elsewhere in the codebase.
    """
    if not shas:
        return {}
    sha_params = {f'sha{i}': sha for i, sha in enumerate(shas)}
    placeholders = ', '.join(f'{{sha{i}:String}}' for i in range(len(shas)))
    # placeholders are generated indices; all values are bound params.
    sql = (
        f'SELECT sha, ci_status, author_name, {_AUTHOR_EMAIL_SQL} AS email '  # noqa: S608
        'FROM commits FINAL '
        'WHERE project_id = {project_id:String} '
        f'AND sha IN ({placeholders})'
    )
    rows = await clickhouse.query(
        sql, {'project_id': project_id, **sha_params}
    )
    return {
        str(r['sha']): _CommitFacts(
            ci_status=str(r.get('ci_status') or 'unknown'),
            author=str(r['author_name']) if r.get('author_name') else None,
            author_email=str(r['email']) if r.get('email') else None,
        )
        for r in rows
    }


def _release_author(
    tagger: typing.Any,
    created_by: typing.Any,
    commit: _CommitFacts,
) -> tuple[str | None, str | None]:
    """Resolve ``(author, author_email)`` for a release-history entry.

    Preference order: the tag's own tagger, then whoever recorded the
    ``Release`` node, then the author of the tagged commit. A background
    worker's principal is skipped rather than shown -- ``created_by`` holds
    whatever wrote the node, so a release the deployment resync or a
    maintenance pass observed would otherwise read as "released by
    deployment-sync" instead of the person who cut it.
    """
    recorded = str(created_by) if created_by else ''
    if principals.is_process_principal(recorded):
        recorded = ''
    author = (str(tagger) if tagger else None) or recorded or commit.author
    return author or None, (
        (recorded if '@' in recorded else None) or commit.author_email
    )


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
        # The interpolated fragment is a module constant; values are params.
        'SELECT sha, short_sha, message, author_name AS author, '  # noqa: S608
        f'{_AUTHOR_EMAIL_SQL} AS author_email, '
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
        _PROJECT_TAGS_SQL, {'project_id': project_id}
    )
    latest = _latest_release_tag(tag_rows)
    latest_tag = str(latest['name']) if latest else None
    latest_tag_sha = str(latest['sha']) if latest else None
    latest_tag_at = _tag_timestamp(latest) if latest else None

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
        f'{_AUTHOR_EMAIL_SQL} AS author_email, '
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
    shas = [str(r['sha']) for r in tag_rows if r.get('sha')]
    facts_by_sha = await _commit_facts_by_sha(project_id, shas)
    unknown = _CommitFacts(ci_status='unknown', author=None, author_email=None)
    entries: list[ReleaseHistoryEntry] = []
    for row in tag_rows:
        name = str(row['name'])
        sha = str(row['sha'])
        node = nodes.get(name) or {}
        tagger = row.get('tagger_name')
        blocked_at = node.get('blocked_at')
        facts = facts_by_sha.get(sha, unknown)
        author, author_email = _release_author(
            tagger, node.get('created_by'), facts
        )
        entries.append(
            ReleaseHistoryEntry(
                tag=name,
                sha=sha,
                short_sha=sha[:7],
                published_at=_tag_timestamp(row),
                author=author,
                author_email=author_email,
                ci_status=facts.ci_status,
                title=node.get('title'),
                notes_markdown=node.get('description'),
                release_url=_release_url_from_links(node.get('links')),
                tag_url=str(row['url']) if row.get('url') else None,
                package_url=None,
                blocked=bool(blocked_at),
                blocked_reason=node.get('blocked_reason'),
                blocked_by=node.get('blocked_by'),
                blocked_at=blocked_at,
                ci_override_by=node.get('ci_override_by') or None,
                ci_override_at=node.get('ci_override_at') or None,
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
    valkey_client: OptionalValkeyClient,
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
    tag against the configured formats and the committish, cut the tag +
    release via the deployment plugin (reusing the promote machinery
    minus the deploy step), upsert the matching ``Release`` node, and
    record an audit row.
    """
    tag_formats = await _resolve_tag_formats(db, org_slug, project_id)
    patterns = [fmt.pattern for fmt in tag_formats]
    if not versioning.matches_tag_formats(body.tag, patterns):
        allowed = ', '.join(fmt.label for fmt in tag_formats)
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                f'Release tag {body.tag!r} does not match any configured '
                f'tag format ({allowed}).'
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

    # Same gate as the promote path, and for the same reason: a library
    # release off a red commit is still a red artifact, and nothing
    # irreversible has happened yet.
    ci_status = await _assert_ci_not_failing(
        handler,
        ctx,
        credentials,
        committish=body.committish,
        acknowledged=body.acknowledge_ci_failure,
        action='release',
    )

    # With a Release workflow configured, the build owns the tag and the
    # remote Release, exactly as on the promote path -- the only
    # difference is that nothing is deployed afterwards.  See
    # ``_handle_promote`` for why the option gates this.
    if str(resolved.capability_options.get('artifact_workflow') or '').strip():
        built = await _dispatch_release_build(
            db,
            org_slug,
            project_id,
            auth,
            resolved=resolved,
            ctx=ctx,
            credentials=credentials,
            handler=handler,
            valkey_client=valkey_client,
            tag=body.tag,
            committish=versioning.short_committish(body.committish),
            title=body.release_name or body.tag,
            notes_markdown=body.release_notes_markdown,
            deploy=False,
            ci_status=ci_status,
        )
        return ReleaseCutResponse(
            tag=body.tag,
            release_url=None,
            committish=versioning.short_committish(body.committish),
            recorded=True,
            phase='building',
            artifact_run_id=built.artifact.run_id,
            artifact_run_url=built.artifact.run_url,
            watched=built.watched,
            warning=built.warning,
        )

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
    release_id = await _upsert_release_node(
        db,
        project_id=project_id,
        tag=body.tag,
        committish=committish,
        title=body.release_name or body.tag,
        notes_markdown=body.release_notes_markdown,
        release_url=release_url,
        created_by=auth.principal_name,
    )
    await _set_release_ci_override(
        db,
        project_id=project_id,
        release_id=release_id,
        ci_status=ci_status,
        overridden_by=auth.principal_name,
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
        ci_status=ci_status,
        ci_override=ci_status == 'fail',
    )
    return ReleaseCutResponse(
        tag=body.tag,
        release_url=release_url,
        committish=committish,
        recorded=True,
        warning='; '.join(warnings) if warnings else None,
    )


async def _release_for_tag(
    db: graph.Graph,
    *,
    org_slug: str,
    project_id: str,
    tag: str,
) -> dict[str, typing.Any] | None:
    """Return the ``Release`` node for ``tag``, or ``None``.

    Scoped through the project's owning organization so a tag from
    another org can never be ratified against this one.  A tag carried
    by more than one ``Release`` (a retag) is ambiguous about *which*
    notes to publish, so the newest by ``created_at`` wins and the
    collision is logged.
    """
    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    MATCH (p)-[:HAS_RELEASE]->(r:Release {{tag: {tag}}})
    RETURN r{{.id, .tag, .committish, .title, .description,
              .created_at}} AS release
    """
    rows = await db.execute(
        query,
        {'project_id': project_id, 'org_slug': org_slug, 'tag': tag},
        ['release'],
    )
    if not rows:
        return None
    nodes = [
        typing.cast(
            'dict[str, typing.Any]', graph.parse_agtype(row['release'])
        )
        for row in rows
    ]
    if len(nodes) > 1:
        LOGGER.warning(
            'Multiple Release nodes for project=%s tag=%s; publishing the '
            'most recently created one',
            project_id,
            tag,
        )
        nodes.sort(key=lambda node: str(node.get('created_at') or ''))
    return nodes[-1]


@project_deployments_router.post('/releases/{tag}/publish')
async def publish_release(
    org_slug: str,
    project_id: str,
    tag: str,
    background: fastapi.BackgroundTasks,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:deployment:write'),
        ),
    ],
    body: ReleasePublishRequest | None = None,
    source: str | None = None,
) -> ReleasePublishResponse:
    """Ratify an existing ``Release`` by creating it on the remote.

    ``promote`` cuts the tag and records the ``Release`` node -- the
    *intent* to ship.  This publishes the GitHub Release for it, which
    is the *ratification*: the gateway calls it from the
    ``deployment_status`` webhook once the rollout reports success, so a
    failed rollout leaves a blocked release rather than a ratified one.

    Title and notes come from the ``Release`` node, so the ratification
    can't drift from what Imbi recorded at promote time.  Idempotent: a
    release the remote already has is not an error, and the node's
    ``github_release`` link is refreshed either way.  Blocked releases
    are refused with a 409.
    """
    release = await _release_for_tag(
        db, org_slug=org_slug, project_id=project_id, tag=tag
    )
    if release is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'No release found for tag {tag!r}',
        )
    # A block and a success webhook can race; the block wins.  Match on
    # the tag alone -- the committish gate belongs to the deploy paths,
    # and a sibling release cut from the same commit must not veto this
    # one's ratification.
    await _assert_not_blocked(db, project_id, tag=tag)

    resolved, ctx, credentials = await _resolve_and_context(
        db,
        org_slug,
        project_id,
        auth,
        source=source,
        # The caller is normally the gateway's service principal, which
        # has no per-user identity connection; fall back to the
        # Integration's own credentials rather than 503ing.
        best_effort_identity=True,
    )
    handler = _handler(resolved)

    warnings: list[str] = []
    release_info = await _create_remote_release(
        db,
        ctx=ctx,
        resolved=resolved,
        handler=handler,
        credentials=credentials,
        auth=auth,
        tag=tag,
        release_name=str(release.get('title') or tag),
        release_notes_markdown=str(release.get('description') or ''),
        prerelease=(body or ReleasePublishRequest()).prerelease,
        warnings=warnings,
        project_id=project_id,
        log_context='publish',
    )
    release_url = (release_info.html_url if release_info else None) or (
        release_info.url if release_info else None
    )
    if release_url is None and not warnings:
        # The plugin returned nothing -- either it has no
        # ``create_release`` or the remote already had one.  Ask for the
        # existing release so the node still gets its link.
        remote = await _get_release(
            handler, ctx, _resolve_credentials(ctx, credentials), tag
        )
        release_url = remote.html_url if remote else None

    await persist_link_writeback(db, ctx)

    committish = str(release.get('committish') or '')
    # Guard on the committish: it is the node's identity, and upserting
    # against an empty one would spawn a second, unmatchable Release.
    if release_url and committish:
        await _upsert_release_node(
            db,
            project_id=project_id,
            tag=tag,
            committish=committish,
            title=str(release.get('title') or tag),
            # Empty preserves whatever the node already holds; this call
            # is only here to write the ``github_release`` link.
            notes_markdown='',
            release_url=release_url,
            created_by=auth.principal_name,
        )

    published = not warnings
    LOGGER.info(
        'Release publish: project=%s tag=%s published=%s plugin=%s actor=%s',
        project_id,
        tag,
        published,
        resolved.plugin_slug,
        ctx.actor_user_id,
    )
    background.add_task(
        _record_deployment_audit,
        project_id=project_id,
        project_slug=ctx.project_slug,
        environment_slug='',
        recorded_by=auth.principal_name,
        action='publish',
        tag=tag,
        committish=committish,
        plugin_slug=resolved.plugin_slug,
        run_url=None,
        release_url=release_url,
    )
    return ReleasePublishResponse(
        tag=tag,
        published=published,
        release_url=release_url,
        warning='; '.join(warnings) if warnings else None,
    )


# ---------------------------------------------------------------------------
# Release blocks
#
# Blocking a release keeps it from shipping again -- the rollback follow-up:
# a regression is found, the release is rolled back, and the tag is blocked
# so nobody re-deploys or re-promotes it while the fix is in flight.  The
# block is global (every environment) and carries a required reason.  State
# lives on the ``Release`` node as ``blocked_at`` / ``blocked_by`` /
# ``blocked_reason``; ``blocked_at`` is the flag.
# ---------------------------------------------------------------------------


async def _tag_sha(project_id: str, tag: str) -> str | None:
    """Return the synced commit SHA for ``tag``, or ``None``."""
    rows = await clickhouse.query(
        'SELECT sha FROM tags FINAL '
        'WHERE project_id = {project_id:String} AND name = {tag:String} '
        'LIMIT 1',
        {'project_id': project_id, 'tag': tag},
    )
    return str(rows[0]['sha']) if rows and rows[0].get('sha') else None


async def _set_release_block(
    db: graph.Graph,
    *,
    org_slug: str,
    project_id: str,
    tag: str,
    blocked_at: str | None,
    blocked_by: str | None,
    reason: str | None,
    scope: typing.Literal['tag'] | None = None,
) -> bool:
    """Write the ``blocked_*`` properties on a tagged ``Release``.

    Passing ``None`` for ``blocked_at`` / ``blocked_by`` / ``reason``
    clears the block (AGE stores a ``null`` assignment as property
    removal).  Returns ``False`` when no ``Release`` node for ``tag``
    exists under the org, letting the caller decide between creating one
    and returning a 404.

    ``scope='tag'`` narrows the block to this exact version, so
    :func:`_blocked_release` stops matching it on the shared committish.
    A failed *release build* is a property of the version, not of the
    commit -- the usual fix is to promote a new version off the same tree,
    which a commit-wide block would refuse.  A manual block leaves
    ``scope`` ``None`` and keeps the broad, commit-wide semantics: an
    operator blocking a rolled-back release means "stop shipping this
    code", which is exactly the commit.
    """
    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    MATCH (p)-[:HAS_RELEASE]->(r:Release {{tag: {tag}}})
    SET r.blocked_at = {blocked_at},
        r.blocked_by = {blocked_by},
        r.blocked_reason = {reason},
        r.blocked_scope = {scope},
        r.updated_at = {now}
    RETURN r.id AS rid
    """
    rows = await db.execute(
        query,
        {
            'project_id': project_id,
            'org_slug': org_slug,
            'tag': tag,
            'blocked_at': blocked_at,
            'blocked_by': blocked_by,
            'reason': reason,
            'scope': scope,
            'now': datetime.datetime.now(datetime.UTC).isoformat(),
        },
        ['rid'],
    )
    return bool(rows)


async def _blocked_release(
    db: graph.Graph,
    project_id: str,
    *,
    tag: str | None,
    committish: str | None,
) -> tuple[str, str | None] | None:
    """Return ``(tag_or_committish, reason)`` for a blocked release.

    Matches on either identity so both shipping paths are covered: a
    deploy names a tag or a raw SHA, and a promote names the tag being
    promoted plus the committish it was cut from.  ``None`` means
    nothing blocked matches.  Empty strings stand in for the absent
    identity -- neither ever matches a stored value, and AGE has no
    NULL equality.

    A release blocked with ``blocked_scope = 'tag'`` matches on its tag
    only.  Those are build failures, recorded by the promote watcher
    against one version; matching them on the committish too would wedge
    the whole commit and refuse the ordinary fix of promoting a bumped
    version off the same tree.  Manual blocks carry no scope and keep
    matching both identities.
    """
    query: typing.LiteralString = """
    MATCH (:Project {{id: {project_id}}})-[:HAS_RELEASE]->(r:Release)
    WHERE r.blocked_at IS NOT NULL
      AND (COALESCE(r.tag, '') = {tag}
           OR (COALESCE(r.committish, '') = {committish}
               AND COALESCE(r.blocked_scope, '') <> 'tag'))
    RETURN r{{.tag, .committish, .blocked_reason}} AS release
    """
    rows = await db.execute(
        query,
        {
            'project_id': project_id,
            'tag': tag or '',
            'committish': committish or '',
        },
        ['release'],
    )
    if not rows:
        return None
    node = typing.cast(
        'dict[str, typing.Any]', graph.parse_agtype(rows[0]['release'])
    )
    label = node.get('tag') or node.get('committish') or (tag or committish)
    reason = node.get('blocked_reason')
    return str(label), str(reason) if reason else None


async def _assert_not_blocked(
    db: graph.Graph,
    project_id: str,
    *,
    tag: str | None = None,
    committish: str | None = None,
) -> None:
    """Raise 409 when the release being shipped is blocked."""
    blocked = await _blocked_release(
        db, project_id, tag=tag, committish=committish
    )
    if blocked is None:
        return
    label, reason = blocked
    detail = f'Release {label!r} is blocked and cannot be deployed'
    if reason:
        detail += f': {reason}'
    raise fastapi.HTTPException(status_code=409, detail=detail)


@project_deployments_router.post('/releases/{tag}/block')
async def block_release(
    org_slug: str,
    project_id: str,
    tag: str,
    body: ReleaseBlockRequest,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:deployment:write'),
        ),
    ],
) -> ReleaseBlockResponse:
    """Block ``tag`` from being deployed or promoted, with a reason.

    Blocking is idempotent and re-blocking overwrites the reason and
    re-stamps the actor.  A tag that has been synced but never cut
    through Imbi has no ``Release`` node yet; one is created from the
    synced tag so the block still holds.  A tag Imbi has never seen is
    a 404.
    """
    blocked_at = datetime.datetime.now(datetime.UTC)
    matched = await _set_release_block(
        db,
        org_slug=org_slug,
        project_id=project_id,
        tag=tag,
        blocked_at=blocked_at.isoformat(),
        blocked_by=auth.principal_name,
        reason=body.reason,
    )
    if not matched:
        sha = await _tag_sha(project_id, tag)
        if sha is None:
            raise fastapi.HTTPException(
                status_code=404,
                detail=f'No release found for tag {tag!r}',
            )
        await _upsert_release_node(
            db,
            project_id=project_id,
            tag=tag,
            committish=sha[:7].lower(),
            title=tag,
            notes_markdown='',
            release_url=None,
            created_by=auth.principal_name,
        )
        matched = await _set_release_block(
            db,
            org_slug=org_slug,
            project_id=project_id,
            tag=tag,
            blocked_at=blocked_at.isoformat(),
            blocked_by=auth.principal_name,
            reason=body.reason,
        )
        if not matched:
            raise fastapi.HTTPException(
                status_code=404,
                detail=f'No release found for tag {tag!r}',
            )
    LOGGER.info(
        'Release blocked: project=%s tag=%s actor=%s reason=%s',
        project_id,
        tag,
        auth.principal_name,
        body.reason,
    )
    return ReleaseBlockResponse(
        tag=tag,
        blocked=True,
        blocked_reason=body.reason,
        blocked_by=auth.principal_name,
        blocked_at=blocked_at,
    )


@project_deployments_router.delete('/releases/{tag}/block')
async def unblock_release(
    org_slug: str,
    project_id: str,
    tag: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:deployment:write'),
        ),
    ],
) -> ReleaseBlockResponse:
    """Clear the block on ``tag``, letting it ship again.

    Unblocking an unblocked release is a no-op, not an error; a 404 only
    means no ``Release`` node exists for the tag.
    """
    matched = await _set_release_block(
        db,
        org_slug=org_slug,
        project_id=project_id,
        tag=tag,
        blocked_at=None,
        blocked_by=None,
        reason=None,
    )
    if not matched:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'No release found for tag {tag!r}',
        )
    LOGGER.info(
        'Release unblocked: project=%s tag=%s actor=%s',
        project_id,
        tag,
        auth.principal_name,
    )
    return ReleaseBlockResponse(tag=tag, blocked=False)
