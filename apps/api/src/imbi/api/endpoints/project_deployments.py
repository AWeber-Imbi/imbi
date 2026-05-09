"""Project deployment plugin endpoints.

Pass-through endpoints that resolve the project's ``tab='deployment'``
plugin and call its handler methods.  Covers ref / commit discovery,
comparison, ``deploy`` / ``redeploy`` workflow dispatch (Phase 1), and
the ``promote`` flow with AI-drafted release notes plus tag + Release
upsert (Phase 2).

See ``docs/deployments-plan.md`` for the full design.
"""

import datetime
import itertools
import json
import logging
import re
import typing

import fastapi
import nanoid
import pydantic
from imbi_common import graph
from imbi_common.plugins.base import (
    Commit,
    CompareResult,
    DeploymentPlugin,
    DeploymentRun,
    PluginContext,
    Ref,
)
from imbi_common.plugins.errors import PluginCredentialsMissing

from imbi_api.auth import permissions
from imbi_api.endpoints._helpers import lookup_project_slugs
from imbi_api.endpoints.releases import append_deployment_event
from imbi_api.identity.host_integration import attach_identity
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
    ctx = PluginContext(
        project_id=project_id,
        project_slug=project_slug,
        org_slug=org_slug,
        team_slug=team_slug,
        environment=environment,
        assignment_options=resolved.options,
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


def _handler(resolved: ResolvedPlugin) -> DeploymentPlugin:
    """Instantiate and type-narrow the plugin handler."""
    return typing.cast(DeploymentPlugin, resolved.entry.handler_cls())


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


async def _handle_deploy(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
    auth: permissions.AuthContext,
    body: DeployActionRequest,
    *,
    source: str | None,
) -> DeploymentTriggerResponse:
    resolved, ctx, credentials = await _resolve_and_context(
        db,
        org_slug,
        project_id,
        auth,
        source=source,
        environment=body.environment,
    )
    handler = _handler(resolved)
    run = await call_with_timeout(
        handler.trigger_deployment(
            ctx,
            credentials,
            ref_or_sha=body.committish,
            inputs=body.inputs,
        )
    )
    LOGGER.info(
        'Deployment triggered: project=%s env=%s ref=%s plugin=%s '
        'action=%s actor=%s run_id=%s',
        project_id,
        body.environment,
        body.committish,
        resolved.plugin_slug,
        body.action,
        ctx.actor_user_id,
        run.run_id,
    )
    note = _deploy_note(resolved.plugin_slug, run.run_url)
    recorded = False
    for candidate in filter(None, (body.ref_label, body.committish)):
        edge = await append_deployment_event(
            db,
            org_slug=org_slug,
            project_id=project_id,
            version=candidate,
            env_slug=body.environment,
            status='in_progress',
            note=note,
        )
        if edge is not None:
            recorded = True
            break
    return DeploymentTriggerResponse(
        run=run,
        plugin_id=resolved.plugin_id,
        plugin_slug=resolved.plugin_slug,
        recorded=recorded,
    )


def _deploy_note(plugin_slug: str, run_url: str | None) -> str:
    parts = [f'via {plugin_slug}']
    if run_url:
        parts.append(run_url)
    return ' — '.join(parts)


async def _handle_promote(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
    auth: permissions.AuthContext,
    body: PromoteActionRequest,
    *,
    source: str | None,
) -> DeploymentTriggerResponse:
    resolved, ctx, credentials = await _resolve_and_context(
        db,
        org_slug,
        project_id,
        auth,
        source=source,
        environment=body.to_environment,
    )
    handler = _handler(resolved)

    # 1. Cut the annotated tag at the chosen build commit.
    tag_message = body.release_name or body.tag
    try:
        await call_with_timeout(
            handler.create_tag(
                ctx,
                credentials,
                sha=body.from_committish,
                tag=body.tag,
                message=tag_message,
            )
        )
    except NotImplementedError as exc:
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                f'Plugin {resolved.plugin_slug!r} does not support '
                'creating tags; promote is not available.'
            ),
        ) from exc

    # 2. Create the release on the remote.
    release_info = None
    try:
        release_info = await call_with_timeout(
            handler.create_release(
                ctx,
                credentials,
                tag=body.tag,
                name=body.release_name or body.tag,
                body_markdown=body.release_notes_markdown,
                prerelease=body.prerelease,
            )
        )
    except NotImplementedError:
        LOGGER.info(
            'Plugin %r has no create_release; tag-only promote',
            resolved.plugin_slug,
        )

    release_url = (release_info.html_url if release_info else None) or (
        release_info.url if release_info else None
    )

    # 3. Dispatch the workflow against the new tag.  We do this before
    #    upserting the Release node so a trigger failure doesn't leave
    #    a Release in the graph with no associated deployment run.
    run = await call_with_timeout(
        handler.trigger_deployment(
            ctx,
            credentials,
            ref_or_sha=body.tag,
            inputs=None,
        )
    )

    # 4. Upsert the Release node so future deploys of the same tag
    #    can attach a DeploymentEvent.
    await _upsert_release_node(
        db,
        project_id=project_id,
        version=body.tag,
        title=body.release_name or body.tag,
        notes_markdown=body.release_notes_markdown,
        release_url=release_url,
        created_by=auth.principal_name,
    )

    # 5. Record the deployment event.
    note = _deploy_note(resolved.plugin_slug, run.run_url)
    edge = await append_deployment_event(
        db,
        org_slug=org_slug,
        project_id=project_id,
        version=body.tag,
        env_slug=body.to_environment,
        status='in_progress',
        note=note,
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
    return DeploymentTriggerResponse(
        run=run,
        plugin_id=resolved.plugin_id,
        plugin_slug=resolved.plugin_slug,
        recorded=edge is not None,
        release_url=release_url,
        tag=body.tag,
    )


async def _upsert_release_node(
    db: graph.Graph,
    *,
    project_id: str,
    version: str,
    title: str,
    notes_markdown: str,
    release_url: str | None,
    created_by: str,
) -> None:
    """Create the ``Release`` node if missing, otherwise update notes.

    Uses MATCH-then-CREATE-or-SET so the second-promote-of-same-tag
    case (rare; tag re-creation will already have failed at the
    plugin) is benign rather than blowing up on a duplicate node.
    """
    now = datetime.datetime.now(datetime.UTC).isoformat()
    links_json = (
        json.dumps([{'type': 'github_release', 'url': release_url}])
        if release_url
        else json.dumps([])
    )
    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
    OPTIONAL MATCH (p)-[:HAS_RELEASE]
        ->(existing:Release {{version: {version}}})
    WITH p, existing
    WHERE existing IS NULL
    CREATE (p)-[:HAS_RELEASE]->(:Release {{
        id: {id},
        version: {version},
        title: {title},
        description: {description},
        links: {links},
        created_by: {created_by},
        created_at: {now},
        updated_at: {now}
    }})
    """
    await db.execute(
        query,
        {
            'project_id': project_id,
            'version': version,
            'id': nanoid.generate(),
            'title': title,
            'description': notes_markdown,
            'links': links_json,
            'created_by': created_by,
            'now': now,
        },
        [],
    )
    # Update notes / links on a pre-existing release (idempotent re-run).
    update_query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
          -[:HAS_RELEASE]->(r:Release {{version: {version}}})
    SET r.description = {description},
        r.links = {links},
        r.updated_at = {now}
    """
    await db.execute(
        update_query,
        {
            'project_id': project_id,
            'version': version,
            'description': notes_markdown,
            'links': links_json,
            'now': now,
        },
        [],
    )


# ---------------------------------------------------------------------------
# Release-notes drafting
# ---------------------------------------------------------------------------

_PROMPT_COMMIT_CAP = 150
_SEMVER_RE = re.compile(r'^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$')

_RELEASE_NOTES_SYSTEM = (
    'You are a release-notes editor for a software project.  Given a '
    'list of commits between two SHAs and the previous release tag, '
    'output a single JSON object on the form\n'
    '  {"bump": "major"|"minor"|"patch", "version": "vX.Y.Z", '
    '"reasoning": "<one-paragraph explanation>", "notes_markdown": '
    '"<markdown body>"}.\n'
    'The version must be the previous tag bumped according to your '
    'chosen ``bump``.  The notes_markdown should group commits by '
    'conventional-commit type (Features / Fixes / Chores / etc.) when '
    'possible.  Do not output anything outside the JSON object.'
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
        system=_RELEASE_NOTES_SYSTEM,
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
async def list_promotion_options(
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

    options: list[PromotionOption] = []
    for from_item, to_item in itertools.pairwise(ordered):
        from_release = from_item['release']
        to_release = to_item['release']
        if not from_release:
            continue
        from_version = str(from_release.get('version') or '')
        to_version = (
            str(to_release.get('version') or '') if to_release else None
        )
        commits_pending: int | None = None
        if to_version and to_version != from_version:
            try:
                cmp_result = await call_with_timeout(
                    handler.compare(
                        ctx,
                        credentials,
                        base=to_version,
                        head=from_version,
                    )
                )
                commits_pending = cmp_result.ahead
            except Exception:  # noqa: BLE001
                LOGGER.debug(
                    'compare failed for %s..%s', to_version, from_version
                )
        options.append(
            PromotionOption(
                from_environment=from_item['env']['slug'],
                to_environment=to_item['env']['slug'],
                from_version=from_version or None,
                to_version=to_version or None,
                commits_pending=commits_pending,
            )
        )
    return options
