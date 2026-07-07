"""Project management endpoints.

Projects are identified by a Nano-ID (``id`` field) and may
belong to multiple project types.  See ADR-0006 for rationale.
"""

import asyncio
import datetime
import json
import logging
import re
import typing

import fastapi
import nanoid
import psycopg
import pydantic
from imbi_common import blueprints, clickhouse, graph, models
from imbi_common.clickhouse import client as ch_client
from imbi_common.plugins.base import (
    LifecycleCapability,
    PluginContext,
    RelocationTarget,
)
from imbi_common.scoring import compute_score

from imbi_api import blueprint_attributes
from imbi_api import patch as json_patch
from imbi_api.auth import permissions
from imbi_api.domain import scoring as scoring_models
from imbi_api.domain.models import ExistsInResponse
from imbi_api.endpoints._helpers import conflict_on_unique_violation
from imbi_api.endpoints._json_fields import (
    JSONFields,
    deserialize_json_fields,
    serialize_json_fields,
)
from imbi_api.graph_sql import escape_prop, props_template, set_clause
from imbi_api.plugins.lifecycle_dispatch import (
    LifecycleInvocation,
    build_lifecycle_context_bundle,
    dispatch_lifecycle,
)
from imbi_api.plugins.resolution import resolve_all_capabilities
from imbi_api.relationships import RelationshipSpec, build_relationships
from imbi_api.scoring import OptionalValkeyClient
from imbi_api.scoring import queue as score_queue
from imbi_api.settings import get_server_config

LOGGER = logging.getLogger(__name__)

_RELEASE_SEMVER_RE = re.compile(r'^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$')


def _release_semver_key(
    name: str,
) -> tuple[int, int, int] | None:
    """Return ``(major, minor, patch)`` for semver tags; ``None`` if not."""
    m = _RELEASE_SEMVER_RE.match(name)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _pick_latest_tag(
    rows: list[dict[str, typing.Any]],
) -> dict[str, typing.Any] | None:
    """Pick the latest release tag (highest semver) from ``tags`` rows.

    Mirrors ``_latest_release_tag`` in ``project_deployments`` but is
    local to avoid a circular import (project_deployments → releases →
    projects).

    Only semver tags are considered; non-semver rows are ignored so an
    ad-hoc tag (e.g. ``deploy-20240101``) never wins over a real release.
    """
    semver_rows = [
        row
        for row in rows
        if _release_semver_key(str(row.get('name', ''))) is not None
    ]
    if not semver_rows:
        return None

    def _key(
        r: dict[str, typing.Any],
    ) -> tuple[tuple[int, int, int], str]:
        sv = _release_semver_key(str(r.get('name', '')))
        when = r.get('tagged_at') or r.get('recorded_at')
        when_key = (
            when.isoformat() if isinstance(when, datetime.datetime) else ''
        )
        return (sv or (0, 0, 0), when_key)

    return max(semver_rows, key=_key)


projects_router = fastapi.APIRouter(tags=['Projects'])


# -- Request / Response models ------------------------------------------


class EnvironmentRef(models.Environment):
    """Environment with dynamic edge properties from DEPLOYED_IN.

    Edge properties are defined by relationship blueprints and
    accepted via ``extra='allow'`` so they flow through to the
    response without hard-coding field names.
    """

    model_config = pydantic.ConfigDict(extra='allow')


class ProjectCreate(pydantic.BaseModel):
    """Request body for creating a project.

    Blueprint-defined fields are accepted as extra properties.
    """

    model_config = pydantic.ConfigDict(extra='allow')

    name: str
    slug: str
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None
    team_slug: str
    project_type_slugs: list[str] = pydantic.Field(min_length=1)
    environments: dict[str, dict[str, typing.Any]] = pydantic.Field(
        default_factory=dict,
        description=(
            'Map of environment slug to edge properties. '
            'Example: {"production": {"url": "https://..."}, '
            '"staging": {}}'
        ),
    )
    links: dict[str, pydantic.AnyUrl] = {}
    identifiers: dict[str, int | str] = {}

    @pydantic.field_validator('project_type_slugs')
    @classmethod
    def _deduplicate_type_slugs(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))


class ProjectUpdate(pydantic.BaseModel):
    """Request body for updating a project.

    Blueprint-defined fields are accepted as extra properties.
    """

    model_config = pydantic.ConfigDict(extra='allow')

    name: str | None = None
    slug: str | None = None
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None
    team_slug: str | None = None
    project_type_slugs: list[str] | None = pydantic.Field(
        default=None, min_length=1
    )

    @pydantic.field_validator('project_type_slugs')
    @classmethod
    def _deduplicate_type_slugs(
        cls,
        v: list[str] | None,
    ) -> list[str] | None:
        if v is not None:
            return list(dict.fromkeys(v))
        return v

    environments: dict[str, dict[str, typing.Any]] | None = pydantic.Field(
        default=None,
        description=(
            'Map of environment slug to edge properties. '
            'Replaces all environment assignments when provided.'
        ),
    )
    links: dict[str, pydantic.AnyUrl] | None = None
    identifiers: dict[str, int | str] | None = None


# ProjectRelationships now lives in imbi_common.models so the OpenAPI
# schema emitted from ``make_response_model(Project)`` matches the
# runtime shape that this endpoint actually returns. Re-export under
# the historical name for callers in this module.
ProjectRelationships = models.ProjectRelationships


class ReleaseInfo(pydantic.BaseModel):
    """Current release for a project in an environment.

    ``tag`` is the optional human-readable label (e.g. ``1.0.0``);
    ``committish`` is the 7-char short SHA. The UI displays
    ``tag ?? committish`` and uses ``committish`` equality to group
    environments showing the same release.
    """

    deployed_at: datetime.datetime
    performed_by: str | None = None
    tag: str | None = None
    committish: str | None = None


class ReleaseSummary(pydantic.BaseModel):
    """Minimal release-drift summary for the projects-list view.

    head_sha is the latest commit on main; latest_tag is the most recent
    semver release tag; commits_since_tag is the number of unreleased
    commits.
    """

    head_sha: str | None = None
    head_short_sha: str | None = None
    head_author: str | None = None
    head_author_login: str | None = None
    head_authored_at: datetime.datetime | None = None
    latest_tag: str | None = None
    latest_tag_sha: str | None = None
    latest_tag_at: datetime.datetime | None = None
    latest_tag_author: str | None = None
    commits_since_tag: int = 0


class ProjectListTeamRef(pydantic.BaseModel):
    """Minimal team identity for the projects-list view."""

    name: str
    slug: str


class ProjectListProjectTypeRef(pydantic.BaseModel):
    """Minimal project-type identity for the projects-list view."""

    name: str
    slug: str
    deployable: bool = False
    releasable: bool = False


class ProjectListEnvironmentRef(pydantic.BaseModel):
    """Minimal environment identity for the projects-list view."""

    name: str
    slug: str
    label_color: str | None = None
    sort_order: int = 0


class ProjectListItem(pydantic.BaseModel):
    """Slim project payload returned from ``GET /projects/?slim=true``.

    Stripped to the fields the projects-list page actually reads --
    no ``links``, ``identifiers``, ``relationships``, embedded
    organizations, blueprint dynamic fields, or ``DEPLOYED_IN`` edge
    properties. Cuts the response shape from kilobytes-per-project
    down to a few hundred bytes.

    The page-equivalent fetcher in imbi-ui calls this endpoint with
    ``slim=true`` to keep the cached array compact in memory.
    """

    id: str
    name: str
    slug: str
    description: str | None = None
    archived: bool = False
    score: float | None = None
    team: ProjectListTeamRef
    project_types: list[ProjectListProjectTypeRef] = []
    environments: list[ProjectListEnvironmentRef] = []
    open_pr_count: int = 0
    closed_pr_count: int = 0
    viewer_open_pr_count: int = 0
    viewer_closed_pr_count: int = 0
    current_releases: dict[str, ReleaseInfo] = pydantic.Field(
        default_factory=dict
    )
    release_summary: ReleaseSummary | None = None


class ProjectResponse(pydantic.BaseModel):
    """Response body for a project."""

    model_config = pydantic.ConfigDict(extra='allow')

    id: str | None = None
    name: str
    slug: str
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    archived: bool = False
    archived_at: datetime.datetime | None = None
    team: models.Team
    project_types: list[models.ProjectType] = []
    environments: list[EnvironmentRef] = []
    links: dict[str, pydantic.AnyUrl] = {}
    identifiers: dict[str, int | str] = {}
    # The project's EXISTS_IN connections, one entry per
    # ``(:Project)-[:EXISTS_IN]->(:Integration)`` edge.  Read-only
    # structured surface (identifier + canonical API URL + the dashboard
    # URL from ``links``); maintained through the project-services
    # endpoints, not by editing ``identifiers``.
    services: list[ExistsInResponse] = []
    score: float | None = None
    breakdown: scoring_models.ScoreBreakdown | None = None
    relationships: ProjectRelationships | None = None
    open_pr_count: int = 0
    closed_pr_count: int = 0
    viewer_open_pr_count: int = 0
    viewer_closed_pr_count: int = 0
    current_releases: dict[str, ReleaseInfo] = pydantic.Field(
        default_factory=dict
    )

    @pydantic.field_validator(
        'links',
        'identifiers',
        mode='before',
    )
    @classmethod
    def _parse_json_strings(
        cls,
        value: typing.Any,
    ) -> typing.Any:
        """Graph stores dicts as JSON strings."""
        if isinstance(value, str):
            return json.loads(value)
        return value

    @pydantic.model_validator(mode='before')
    @classmethod
    def _build_services(cls, data: typing.Any) -> typing.Any:
        """Build the ``services`` list from the EXISTS_IN edges.

        The read fragment returns a ``service_edges`` list of
        ``{slug, name, identifier, canonical_url}`` from each
        ``(:Project)-[:EXISTS_IN]->(:Integration)`` edge.  Pair each
        with the matching ``Project.links[slug]`` dashboard URL and expose
        the result as the read-only ``services`` field.  ``identifiers``
        is intentionally left as the node property -- edge identifiers are
        *not* merged into it, so the editable identifier map and the
        service relationship never collide.
        """
        if not isinstance(data, dict):
            return data
        values = typing.cast('dict[str, typing.Any]', data)
        raw_edges = values.pop('service_edges', None)
        if not raw_edges or not isinstance(raw_edges, list):
            return values
        edges = typing.cast('list[dict[str, typing.Any]]', raw_edges)
        raw_links: typing.Any = values.get('links') or {}
        if isinstance(raw_links, str):
            raw_links = json.loads(raw_links) or {}
        links = typing.cast('dict[str, typing.Any]', raw_links)
        services: list[dict[str, typing.Any]] = []
        for edge in edges:
            slug = edge.get('slug')
            if not slug or not isinstance(slug, str):
                continue
            identifier = edge.get('identifier')
            dashboard = links.get(slug)
            services.append(
                {
                    'integration_slug': slug,
                    'integration_name': edge.get('name') or slug,
                    'identifier': ''
                    if identifier is None
                    else str(identifier),
                    'canonical_url': edge.get('canonical_url'),
                    'dashboard_url': str(dashboard) if dashboard else None,
                }
            )
        values['services'] = services
        return values


class ProjectMutationResponse(ProjectResponse):
    """Response for any project mutation that triggers a lifecycle dispatch.

    Mirrors :class:`ProjectResponse` and appends one
    :class:`LifecycleInvocation` per assigned lifecycle plugin so the
    UI can surface third-party outcomes (GitHub repo created /
    renamed, archive succeeded, etc.) without a follow-up request.
    Used by create / patch / archive / unarchive.  Empty when no
    lifecycle plugins are assigned.
    """

    lifecycle_results: list[LifecycleInvocation] = []


# Back-compat alias: pre-2.8 the archive / unarchive endpoints
# returned ``ArchiveProjectResponse``.  The shape is now shared with
# create / patch so the canonical name is ``ProjectMutationResponse``;
# this alias keeps OpenAPI clients and existing tests building.
ArchiveProjectResponse = ProjectMutationResponse


class ProjectDeletedResponse(pydantic.BaseModel):
    """Response for a successful project delete.

    The project node is gone by the time the response is built, so
    the body carries only the per-plugin lifecycle results -- empty
    when ``delete_repository=false`` short-circuits the dispatch.
    """

    lifecycle_results: list[LifecycleInvocation] = []


class LifecyclePreviewEntry(pydantic.BaseModel):
    """One row of the ``/lifecycle/preview`` response.

    Lets the UI decide whether to surface a "move repository" affordance
    for the hypothetical ``project_type_slugs`` set: ``would_relocate``
    is true when the plugin would route the link somewhere different
    than where it points today.  ``current_target`` may be ``None`` if
    the project has no project types assigned today (a brand-new
    project being type-tagged for the first time).
    """

    integration_id: str
    plugin_slug: str
    current_target: RelocationTarget | None = None
    next_target: RelocationTarget | None = None
    would_relocate: bool = False


class LifecyclePreviewResponse(pydantic.BaseModel):
    """Per-plugin preview for a hypothetical project-type change.

    Empty ``previews`` when the project has no lifecycle plugins
    assigned, or when none of the assigned plugins implement
    :meth:`LifecycleCapability.resolve_relocation_target` (the default
    base implementation returns ``None``).
    """

    previews: list[LifecyclePreviewEntry] = []


def _build_project_ui_url(org_slug: str, project_id: str) -> str | None:
    """Resolve the canonical UI deep link for a project.

    Returns ``None`` when ``IMBI_UI_URL`` is unset so lifecycle plugins
    can skip writing the equivalent of a GitHub repo ``homepage``
    without falling back to a localhost URL that would point at
    nothing meaningful for a third party.
    """
    base = get_server_config().ui_url
    if not base:
        return None
    return f'{base}/organizations/{org_slug}/projects/{project_id}'


# -- Helpers ------------------------------------------------------------


def _env_entries_template(
    entries: list[dict[str, typing.Any]],
) -> tuple[str, dict[str, typing.Any]]:
    """Build an inline Cypher list of maps for env entries.

    Each entry is a dict with ``slug`` plus arbitrary edge
    properties.  Returns ``(template_fragment, params_dict)``
    where the template uses indexed placeholders and the params
    dict maps those keys to scalar values.

    """
    if not entries:
        return '[]', {}
    maps: list[str] = []
    params: dict[str, typing.Any] = {}
    for i, entry in enumerate(entries):
        pairs: list[str] = []
        for key, value in entry.items():
            param = f'env_{i}_{key}'
            pairs.append(f'{escape_prop(key)}: {{{param}}}')
            params[param] = value
        maps.append('{{' + ', '.join(pairs) + '}}')
    return '[' + ', '.join(maps) + ']', params


def _edge_props_map(
    entries: list[dict[str, typing.Any]],
) -> str:
    """Build a Cypher property map for DEPLOYED_IN edge writes.

    Used for both ``CREATE … []`` (project creation) and
    ``MERGE … SET r =`` (project update).  Returns a string like
    ``{{`url`: entry.`url`}}`` derived from the union of all entries'
    keys (excluding ``slug``).  Returns an empty string when there are
    no edge properties.

    """
    if not entries:
        return ''
    all_keys: dict[str, None] = {}
    for entry in entries:
        for k in entry:
            if k != 'slug':
                all_keys[k] = None
    prop_keys = list(all_keys)
    if not prop_keys:
        return ''
    pairs = [f'{escape_prop(k)}: entry.{escape_prop(k)}' for k in prop_keys]
    return ' {{' + ', '.join(pairs) + '}}'


async def _validate_env_slugs(
    db: graph.Pool,
    org_slug: str,
    env_slugs: list[str],
) -> None:
    """Validate that all environment slugs exist in the org.

    Raises HTTPException 422 if any are missing.
    """
    env_check: typing.LiteralString = """
    MATCH (o:Organization {{slug: {org_slug}}})
    UNWIND {env_slugs} AS env_slug
    OPTIONAL MATCH (e:Environment {{slug: env_slug}})
             -[:BELONGS_TO]->(o)
    RETURN env_slug, e IS NOT NULL AS found
    """
    records = await db.execute(
        env_check,
        {
            'org_slug': org_slug,
            'env_slugs': env_slugs,
        },
        ['env_slug', 'found'],
    )
    missing = [
        graph.parse_agtype(r['env_slug'])
        for r in records
        if not graph.parse_agtype(r['found'])
    ]
    if missing:
        raise fastapi.HTTPException(
            status_code=422,
            detail=(f'Environment slug(s) not found: {sorted(missing)!r}'),
        )


async def _fetch_pr_counts(
    project_ids: list[str],
    viewer: str | None = None,
) -> dict[str, tuple[int, int, int, int]]:
    """Return {project_id: (open, closed, viewer_open, viewer_closed)}.

    Errors are swallowed — PR counts are best-effort and should not
    fail the project list endpoint.
    """
    if not project_ids:
        return {}
    params: dict[str, typing.Any] = {'project_ids': project_ids}
    if viewer:
        sql = (
            'SELECT project_id,'
            " countIf(state = 'open') AS open_count,"
            " countIf(state = 'closed') AS closed_count,"
            " countIf(state = 'open' AND author = {viewer:String})"
            ' AS viewer_open_count,'
            " countIf(state = 'closed' AND author = {viewer:String})"
            ' AS viewer_closed_count'
            ' FROM pull_requests FINAL'
            ' WHERE project_id IN {project_ids:Array(String)}'
            ' GROUP BY project_id'
        )
        params['viewer'] = viewer
    else:
        sql = (
            'SELECT project_id,'
            " countIf(state = 'open') AS open_count,"
            " countIf(state = 'closed') AS closed_count,"
            ' 0 AS viewer_open_count,'
            ' 0 AS viewer_closed_count'
            ' FROM pull_requests FINAL'
            ' WHERE project_id IN {project_ids:Array(String)}'
            ' GROUP BY project_id'
        )
    try:
        rows = await ch_client.Clickhouse.get_instance().query(sql, params)
    except Exception:  # noqa: BLE001
        LOGGER.warning('Failed to fetch PR counts for projects', exc_info=True)
        return {}
    return {
        str(r['project_id']): (
            int(r['open_count']),
            int(r['closed_count']),
            int(r['viewer_open_count']),
            int(r['viewer_closed_count']),
        )
        for r in rows
    }


async def _resolve_display_names(
    db: graph.Graph,
    emails: list[str],
) -> dict[str, str]:
    """Return {email: display_name} for known User nodes.

    Best-effort enrichment: callers fall back to the local-part of
    the email when a name is not returned, so DB errors should never
    surface as a 500.
    """
    if not emails:
        return {}
    query: typing.LiteralString = (
        'MATCH (u:User) WHERE u.email IN {emails}'
        ' RETURN u.email AS email, u.display_name AS display_name'
    )
    try:
        records = await db.execute(
            query, {'emails': emails}, ['email', 'display_name']
        )
    except Exception:  # noqa: BLE001
        LOGGER.warning(
            'Failed to resolve performer display names', exc_info=True
        )
        return {}
    return {
        str(graph.parse_agtype(r['email'])): str(
            graph.parse_agtype(r['display_name'])
        )
        for r in records
        if r.get('email') and r.get('display_name')
    }


def _latest_deployment_event(
    raw: typing.Any,
) -> tuple[datetime.datetime, str | None] | None:
    """Return ``(timestamp, performed_by)`` of the latest event, or ``None``.

    The ``deployments`` edge property is a JSON-encoded list of
    ``DeploymentEvent``-shaped objects.  ``_fetch_current_releases``
    only needs the most recent ``(timestamp, performed_by)`` per
    ``(project, environment)`` pair, so we parse straight off the dicts
    and skip the per-entry Pydantic validation that
    ``_parse_deployment_events`` used to pay for.
    """
    if not raw:
        return None
    data = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(data, list):
        return None
    latest_ts: datetime.datetime | None = None
    latest_by: str | None = None
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
        if latest_ts is None or parsed > latest_ts:
            latest_ts = parsed
            performed_by = entry.get(  # type: ignore[reportUnknownMemberType]
                'performed_by'
            )
            latest_by = performed_by if isinstance(performed_by, str) else None
    if latest_ts is None:
        return None
    return latest_ts, latest_by


async def lookup_ops_log_performed_by(
    targets: list[tuple[str, str, str]],
) -> dict[tuple[str, str, str], str]:
    """Map ``(project_id, environment_slug, version)`` → ``performed_by``.

    Backfills the deployer for releases whose
    ``DeploymentEvent.performed_by`` on the AGE edge is null.
    The in-product deploy/promote handlers intentionally leave that
    field empty because the audit row in ``operations_log`` already
    carries the operator (see
    ``project_deployments._record_deployment_audit``).

    Errors are swallowed — performer attribution is best-effort.
    """
    if not targets:
        return {}
    project_ids = sorted({t[0] for t in targets})
    sql = (
        'SELECT project_id, environment_slug, version,'
        ' argMax(performed_by, occurred_at) AS performed_by'
        ' FROM operations_log FINAL'
        " WHERE entry_type = 'Deployed'"
        ' AND project_id IN {project_ids:Array(String)}'
        ' GROUP BY project_id, environment_slug, version'
    )
    try:
        rows = await ch_client.Clickhouse.get_instance().query(
            sql, {'project_ids': project_ids}
        )
    except Exception:  # noqa: BLE001
        LOGGER.warning(
            'Failed to enrich performed_by from operations_log',
            exc_info=True,
        )
        return {}
    target_keys = set(targets)
    result: dict[tuple[str, str, str], str] = {}
    for row in rows:
        key = (
            str(row.get('project_id') or ''),
            str(row.get('environment_slug') or ''),
            str(row.get('version') or ''),
        )
        performed_by = row.get('performed_by')
        if performed_by and key in target_keys:
            result[key] = str(performed_by)
    return result


async def _fetch_current_releases(
    db: graph.Graph,
    project_ids: list[str],
) -> dict[str, dict[str, ReleaseInfo]]:
    """Return {project_id: {env_slug: ReleaseInfo}} for current releases.

    Reads from the AGE graph — the same source the project-detail
    ``/releases/current`` endpoint uses — so both views agree.  For
    each project we walk every
    ``(p)-[:HAS_RELEASE]->(r:Release)-[d:DEPLOYED_TO]->(e:Environment)``
    edge and pick the release whose latest ``DeploymentEvent``
    has the most recent ``timestamp`` per environment.

    ``performed_by`` on each ``DeploymentEvent`` is populated for
    resync-sourced events but is intentionally null for in-product
    deploy/promote actions (which capture the operator on the
    ``operations_log`` audit row instead).  For those rows we look
    up the deployer in ``operations_log`` keyed on
    ``(project_id, environment_slug, version)`` — where ``version``
    is ``tag if tag else committish``, matching the audit writer.

    Errors are swallowed — release data is best-effort.
    """
    if not project_ids:
        return {}
    query: typing.LiteralString = """
    MATCH (p:Project)-[:HAS_RELEASE]->(r:Release)
                    -[d:DEPLOYED_TO]->(e:Environment)
    WHERE p.id IN {project_ids}
    RETURN p.id AS project_id,
           e.slug AS env_slug,
           r.tag AS tag,
           r.committish AS committish,
           d.deployments AS deployments
    """
    try:
        rows = await db.execute(
            query,
            {'project_ids': project_ids},
            ['project_id', 'env_slug', 'tag', 'committish', 'deployments'],
        )
    except Exception:  # noqa: BLE001
        LOGGER.warning(
            'Failed to fetch current releases for projects', exc_info=True
        )
        return {}

    # For each (project_id, env_slug), keep the (release, event) pair
    # with the latest event timestamp.
    latest: dict[
        tuple[str, str],
        tuple[str | None, str | None, datetime.datetime, str | None],
    ] = {}
    for row in rows:
        pid = graph.parse_agtype(row.get('project_id'))
        env_slug = graph.parse_agtype(row.get('env_slug'))
        if not isinstance(pid, str) or not isinstance(env_slug, str):
            continue
        latest_event = _latest_deployment_event(
            graph.parse_agtype(row.get('deployments'))
        )
        if latest_event is None:
            continue
        event_ts, performed_by = latest_event
        tag_val = graph.parse_agtype(row.get('tag'))
        committish_val = graph.parse_agtype(row.get('committish'))
        tag = str(tag_val) if tag_val else None
        committish = str(committish_val) if committish_val else None
        key = (pid, env_slug)
        existing = latest.get(key)
        if existing is None or event_ts > existing[2]:
            latest[key] = (tag, committish, event_ts, performed_by)

    # Backfill performed_by from operations_log for events whose
    # AGE edge left it null (in-product deploy/promote path).
    enrich_targets = [
        (pid, env_slug, str(tag or committish or ''))
        for (pid, env_slug), (
            tag,
            committish,
            _ts,
            performed_by,
        ) in latest.items()
        if performed_by is None and (tag or committish)
    ]
    performed_by_by_key = await lookup_ops_log_performed_by(enrich_targets)
    if performed_by_by_key:
        for key, (tag, committish, ts, performed_by) in list(latest.items()):
            if performed_by is not None:
                continue
            version = str(tag or committish or '')
            looked_up = performed_by_by_key.get((key[0], key[1], version))
            if looked_up:
                latest[key] = (tag, committish, ts, looked_up)

    result: dict[str, dict[str, ReleaseInfo]] = {}
    for (pid, env_slug), (tag, committish, ts, performed_by) in latest.items():
        result.setdefault(pid, {})[env_slug] = ReleaseInfo(
            tag=tag,
            committish=committish,
            performed_by=performed_by,
            deployed_at=ts,
        )
    return result


async def _fetch_release_summaries(
    project_ids: list[str],
) -> dict[str, ReleaseSummary]:
    """Return {project_id: ReleaseSummary} for releasable projects.

    Two ClickHouse queries: one for latest tags, one for latest commit
    SHA.  Uses the same semver-max logic as the per-project
    release-drift endpoint.  Errors are swallowed — release data is
    best-effort.
    """
    if not project_ids:
        return {}
    try:
        tag_rows, head_rows = await asyncio.gather(
            clickhouse.query(
                'SELECT project_id, name, sha, tagged_at, recorded_at,'
                ' tagger_name'
                ' FROM tags FINAL'
                ' WHERE project_id IN {project_ids:Array(String)}',
                {'project_ids': project_ids},
            ),
            clickhouse.query(
                'SELECT project_id, sha, short_sha,'
                ' author_name, author_user, authored_at'
                ' FROM commits FINAL'
                ' WHERE project_id IN {project_ids:Array(String)}'
                ' ORDER BY pushed_at DESC, authored_at DESC'
                ' LIMIT 1 BY project_id',
                {'project_ids': project_ids},
            ),
        )
    except Exception:  # noqa: BLE001
        LOGGER.warning(
            'Failed to fetch release summaries for projects',
            exc_info=True,
        )
        return {}

    tags_by_project: dict[str, list[dict[str, typing.Any]]] = {}
    for row in tag_rows:
        pid = str(row.get('project_id', ''))
        if pid:
            tags_by_project.setdefault(pid, []).append(row)

    head_by_project: dict[str, dict[str, typing.Any]] = {
        str(row['project_id']): row
        for row in head_rows
        if row.get('project_id') and row.get('sha')
    }

    # Resolve each project's latest semver tag and its timestamp so we
    # can query commit counts after that point.
    all_pids = set(tags_by_project.keys()) | set(head_by_project.keys())
    latest_by_pid: dict[str, dict[str, typing.Any] | None] = {
        pid: _pick_latest_tag(tags_by_project.get(pid, [])) for pid in all_pids
    }

    # Batch-fetch commit counts since each project's latest tag.
    # Build a list of (project_id, tag_authored_at) tuples so a single
    # ClickHouse query can count unreleased commits per project.
    # Projects with no prior tag get a cutoff of epoch-start (count all).
    tagged_pids = [
        pid for pid, tag in latest_by_pid.items() if tag is not None
    ]
    counts_since_tag: dict[str, int] = {}
    if tagged_pids:
        try:
            # For each project, count commits authored after the tag's
            # recorded_at/tagged_at (the closest proxy we have to when
            # the tag commit landed without a separate sha→authored_at
            # look-up).  This mirrors what the per-project drift endpoint
            # does via a base-commit authored_at lookup.
            tag_times = [
                (latest_by_pid[pid] or {}).get('tagged_at')
                or (latest_by_pid[pid] or {}).get('recorded_at')
                for pid in tagged_pids
            ]
            # Build per-project WHERE via countIf for a single scan.
            # Rows without a valid tag timestamp are excluded from the
            # list, so we can safely cast to datetime.
            pid_cutoff: list[tuple[str, datetime.datetime]] = [
                (pid, t)
                for pid, t in zip(tagged_pids, tag_times, strict=True)
                if isinstance(t, datetime.datetime)
            ]
            if pid_cutoff:
                cutoff_map = dict(pid_cutoff)
                count_rows = await clickhouse.query(
                    'SELECT project_id,'
                    ' countIf(authored_at'
                    ' > {cutoffs:Map(String,DateTime64(3))}'
                    '[project_id]) AS c'
                    ' FROM commits FINAL'
                    ' WHERE project_id'
                    ' IN {project_ids:Array(String)}'
                    ' GROUP BY project_id',
                    {
                        'project_ids': list(cutoff_map.keys()),
                        'cutoffs': cutoff_map,
                    },
                )
                counts_since_tag = {
                    str(row['project_id']): int(row['c'])
                    for row in count_rows
                    if row.get('project_id') is not None
                }
        except Exception:  # noqa: BLE001
            LOGGER.warning(
                'Failed to fetch commit counts since tag',
                exc_info=True,
            )

    release_result: dict[str, ReleaseSummary] = {}
    for pid in all_pids:
        latest = latest_by_pid.get(pid)
        head_row = head_by_project.get(pid)
        head_sha = str(head_row['sha']) if head_row else None
        short_sha = (
            str(head_row.get('short_sha') or head_sha or '')[:7] or None
            if head_row
            else None
        )
        raw_author = (
            head_row.get('author_name') or head_row.get('author_user')
            if head_row
            else None
        )
        head_author = str(raw_author) if raw_author else None
        raw_login = head_row.get('author_user') if head_row else None
        head_author_login = str(raw_login) if raw_login else None
        head_authored_at: datetime.datetime | None = (
            head_row.get('authored_at') if head_row else None
        )
        latest_tag = str(latest['name']) if latest else None
        latest_tag_sha = str(latest['sha']) if latest else None
        latest_tag_at: datetime.datetime | None = (
            latest.get('tagged_at') or latest.get('recorded_at')
            if latest
            else None
        )
        tagger = latest.get('tagger_name') if latest else None
        latest_tag_author = str(tagger) if tagger else None
        release_result[pid] = ReleaseSummary(
            head_sha=head_sha,
            head_short_sha=short_sha,
            head_author=head_author,
            head_author_login=head_author_login,
            head_authored_at=head_authored_at,
            latest_tag=latest_tag,
            latest_tag_sha=latest_tag_sha,
            latest_tag_at=latest_tag_at,
            latest_tag_author=latest_tag_author,
            commits_since_tag=counts_since_tag.get(pid, 0),
        )
    return release_result


_EVENT_SKIP_FIELDS: frozenset[str] = frozenset(
    {
        'id',
        'created_at',
        'updated_at',
        'score',
        'breakdown',
        'relationships',
    }
)


async def _emit_change_events(
    project_id: str,
    principal: str,
    before: dict[str, typing.Any],
    after: dict[str, typing.Any],
) -> None:
    """Emit one events row per changed field into ClickHouse.

    Errors are logged but do not bubble up — the graph write already
    succeeded and we do not want a ClickHouse hiccup to fail the request.
    """
    now = datetime.datetime.now(datetime.UTC)
    rows: list[list[typing.Any]] = []
    for key in set(before) | set(after):
        if key in _EVENT_SKIP_FIELDS:
            continue
        old_val = before.get(key)
        new_val = after.get(key)
        if old_val == new_val:
            continue
        rows.append(
            [
                nanoid.generate(),
                project_id,
                now,
                'project-change',
                'internal',
                principal,
                {},
                {'field': key, 'old': old_val, 'new': new_val},
            ]
        )
    if not rows:
        return
    try:
        await ch_client.Clickhouse.get_instance().insert(
            'events',
            rows,
            [
                'id',
                'project_id',
                'recorded_at',
                'type',
                'integration',
                'attributed_to',
                'metadata',
                'payload',
            ],
        )
    except Exception:
        LOGGER.exception(
            'Failed to emit change events for project %s', project_id
        )


_RESERVED_FIELDS = frozenset(
    {
        'id',
        'team',
        'project_types',
        'environments',
        'created_at',
        'updated_at',
        'archived',
        'archived_at',
    }
)

#: Project node properties that AGE stores as JSON strings.
_PROJECT_JSON_FIELDS: JSONFields = {'links': {}, 'identifiers': {}}


_PROTECTED_ENV_KEYS = frozenset(
    {
        'id',
        'name',
        'slug',
        'sort_order',
        'organization',
        'created_at',
        'updated_at',
        'label_color',
        'description',
        'icon',
    }
)


def _flatten_edge_props(
    project: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    """Merge ``_edge`` sub-dicts into each environment entry.

    The Cypher return fragment stores relationship properties
    under a nested ``_edge`` key.  This flattens them into the
    top-level environment dict so they appear as peer fields.
    Protected environment keys are excluded to prevent
    accidental overwrites.

    Also strips empty dicts that AGE can inject via null map
    projections (collect(node{...}) when OPTIONAL MATCH found nothing).
    """
    raw_pts: list[typing.Any] = project.get('project_types') or []
    project['project_types'] = [
        pt for pt in raw_pts if isinstance(pt, dict) and pt
    ]
    raw_envs: list[typing.Any] = project.get('environments') or []
    envs: list[dict[str, typing.Any]] = [
        e for e in raw_envs if isinstance(e, dict) and e
    ]
    project['environments'] = envs
    for env in envs:
        raw_edge = env.pop('_edge', None)
        if raw_edge:
            edge: dict[str, typing.Any] = (
                json.loads(raw_edge) if isinstance(raw_edge, str) else raw_edge
            )
            env.update(
                {k: v for k, v in edge.items() if k not in _PROTECTED_ENV_KEYS}
            )
    return project


# -- Return fragment used by all read queries ---------------------------

_RETURN_FRAGMENT: typing.LiteralString = """
    MATCH (p)-[:OWNED_BY]->(t:Team)-[:BELONGS_TO]->(o)
    WITH p, o, t
    OPTIONAL MATCH (p)-[:TYPE]->(pt:ProjectType)
          -[:BELONGS_TO]->(o)
    WITH p, o, t, collect(CASE WHEN pt IS NOT NULL
                          THEN pt{{.*, organization: o{{.*}}}}
                          END) AS pts
    OPTIONAL MATCH (p)-[d:DEPLOYED_IN]->(env:Environment)
          -[:BELONGS_TO]->(o)
    WITH p, o, t, pts,
         collect(CASE WHEN env IS NOT NULL
                 THEN env{{.*,
                          sort_order: coalesce(env.sort_order, 0),
                          _edge: properties(d),
                          organization: o{{.*}}}}
                 END) AS envs
    OPTIONAL MATCH (p)-[:DEPENDS_ON]->(out:Project)
    WITH p, o, t, pts, envs, count(out) AS outbound_count
    OPTIONAL MATCH (p)<-[:DEPENDS_ON]-(in_:Project)
    WITH p, o, t, pts, envs, outbound_count,
         count(in_) AS inbound_count
    OPTIONAL MATCH (p)-[ei:EXISTS_IN]->(integration:Integration)
    WITH p, o, t, pts, envs, outbound_count, inbound_count,
         collect(CASE WHEN integration IS NOT NULL
                 THEN {{slug: integration.slug,
                        name: integration.name,
                        identifier: ei.identifier,
                        canonical_url: ei.canonical_url}}
                 END) AS service_edges
    RETURN p{{.*,
        team: t{{.*, organization: o{{.*}}}},
        project_types: pts,
        environments: envs,
        service_edges: service_edges
    }} AS project,
    outbound_count,
    inbound_count
"""


# Slim variant: drops blueprint dynamic fields, embedded organizations,
# DEPLOYED_IN edge props, DEPENDS_ON counts, and every Project node
# field the projects-list page doesn't read (links, identifiers,
# icon, created_at, archived_at, ...). Cuts the per-project payload
# by an order of magnitude.
_SLIM_RETURN_FRAGMENT: typing.LiteralString = """
    MATCH (p)-[:OWNED_BY]->(t:Team)-[:BELONGS_TO]->(o)
    WITH p, t
    OPTIONAL MATCH (p)-[:TYPE]->(pt:ProjectType)
    WITH p, t,
         collect(CASE WHEN pt IS NOT NULL
                      THEN pt{{.slug, .name,
                               deployable: coalesce(pt.deployable, false),
                               releasable: coalesce(pt.releasable, false)}}
                      END) AS pts
    OPTIONAL MATCH (p)-[:DEPLOYED_IN]->(env:Environment)
    WITH p, t, pts,
         collect(CASE WHEN env IS NOT NULL
                      THEN env{{.slug, .name, .label_color,
                                sort_order: coalesce(env.sort_order, 0)}}
                      END) AS envs
    RETURN p{{.id, .name, .slug, .description, .score,
              archived: coalesce(p.archived, false),
              team: t{{.name, .slug}},
              project_types: pts,
              environments: envs}} AS project
"""


# -- Endpoints ----------------------------------------------------------


@projects_router.post('/', status_code=201)
async def create_project(
    org_slug: str,
    data: ProjectCreate,
    request: fastapi.Request,
    db: graph.Pool,
    valkey_client: OptionalValkeyClient,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:create'),
        ),
    ],
) -> ProjectMutationResponse:
    """Create a new project in an organization."""
    dynamic_model = await blueprints.get_model(
        db,
        models.Project,
        context={'project_type': data.project_type_slugs},
    )

    project_id = nanoid.generate()

    try:
        project = dynamic_model(
            id=project_id,
            team=models.Team(
                name='',
                slug=data.team_slug,
                organization=models.Organization(
                    name='',
                    slug=org_slug,
                ),
            ),
            project_types=[],
            environments=[],
            name=data.name,
            slug=data.slug,
            description=data.description,
            icon=data.icon,
            links=data.links,
            **{
                k: v
                for k, v in typing.cast(
                    dict[str, typing.Any],
                    {
                        'identifiers': data.identifiers,
                        **(data.model_extra or {}),
                    },
                ).items()
                if k not in _RESERVED_FIELDS
            },
        )
    except pydantic.ValidationError as e:
        LOGGER.warning(
            'Validation error creating project: %s',
            e,
        )
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    now = datetime.datetime.now(datetime.UTC)
    project.created_at = now
    project.updated_at = now
    props = project.model_dump(
        mode='json',
        exclude={
            'team',
            'project_types',
            'environments',
        },
    )
    props = serialize_json_fields(props, _PROJECT_JSON_FIELDS)

    # Pre-validate that all project type slugs exist before creating
    # anything, to avoid orphaned Project nodes when slugs are invalid.
    validate_query: typing.LiteralString = """
    MATCH (o:Organization {{slug: {org_slug}}})
    UNWIND {pt_slugs} AS pt_slug
    OPTIONAL MATCH (pt:ProjectType {{slug: pt_slug}})
             -[:BELONGS_TO]->(o)
    RETURN pt_slug, pt IS NOT NULL AS found
    """
    validation = await db.execute(
        validate_query,
        {
            'org_slug': org_slug,
            'pt_slugs': data.project_type_slugs,
        },
        ['pt_slug', 'found'],
    )
    missing = [
        graph.parse_agtype(r['pt_slug'])
        for r in validation
        if not graph.parse_agtype(r['found'])
    ]
    if missing:
        raise fastapi.HTTPException(
            status_code=422,
            detail=(f'Project type slug(s) not found: {sorted(missing)!r}'),
        )

    # Pre-validate that all environment slugs exist
    if data.environments:
        await _validate_env_slugs(
            db,
            org_slug,
            list(data.environments.keys()),
        )

    create_tpl = props_template(props)
    env_entries = [{'slug': s, **ep} for s, ep in data.environments.items()]
    env_tpl, env_params = _env_entries_template(env_entries)
    edge_props_tpl = _edge_props_map(env_entries)

    query: str = (
        '\nMATCH (o:Organization {{slug: {org_slug}}})'
        '\nMATCH (t:Team {{slug: {team_slug}}})'
        '\n      -[:BELONGS_TO]->(o)'
        '\nCREATE (p:Project ' + create_tpl + ')'
        '\nCREATE (p)-[:OWNED_BY]->(t)'
        '\nWITH p, t, o'
        '\nUNWIND {pt_slugs} AS pt_slug'
        '\nMATCH (pt:ProjectType {{slug: pt_slug}})'
        '\n      -[:BELONGS_TO]->(o)'
        '\nCREATE (p)-[:TYPE]->(pt)'
        '\nWITH DISTINCT p, t, o'
    )
    if data.environments:
        query += (
            '\nUNWIND ' + env_tpl + ' AS entry'
            '\nMATCH (e:Environment {{slug: entry.slug}})'
            '\n      -[:BELONGS_TO]->(o)'
            '\nCREATE (p)-[:DEPLOYED_IN' + edge_props_tpl + ']->(e)'
            '\nWITH DISTINCT p, t, o'
        )
    query += _RETURN_FRAGMENT
    with conflict_on_unique_violation(
        f'Project with id {project_id!r} already exists',
    ):
        records = await db.execute(
            query,
            {
                'org_slug': org_slug,
                'team_slug': data.team_slug,
                'pt_slugs': data.project_type_slugs,
                **props,
                **env_params,
            },
            ['project', 'outbound_count', 'inbound_count'],
        )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Organization {org_slug!r}, team'
                f' {data.team_slug!r}, or project type(s)'
                f' {data.project_type_slugs!r} not found'
            ),
        )

    project_data = graph.parse_agtype(records[0]['project'])
    _flatten_edge_props(project_data)
    _attach_project_relationships(
        project_data,
        org_slug,
        request,
        graph.parse_agtype(records[0]['outbound_count']),
        graph.parse_agtype(records[0]['inbound_count']),
    )
    await score_queue.enqueue_recompute(
        valkey_client, project_id, 'attribute_change'
    )
    # Fire the lifecycle ``created`` event so plugins (e.g. the
    # GitHub lifecycle plugin) can provision the backing repo and
    # write the resulting canonical link back via ``LinkWriteback``.
    # The project node already committed; never let a dispatch hiccup
    # turn a successful create into a 500.
    lifecycle_results: list[LifecycleInvocation] = []
    try:
        lifecycle_results = await dispatch_lifecycle(
            db,
            project_id,
            org_slug,
            'created',
            auth,
            project_name=project.name,
            project_description=project.description,
            project_ui_url=_build_project_ui_url(org_slug, project_id),
        )
    except Exception:
        LOGGER.exception(
            'Lifecycle dispatch failed after creating project %s',
            project_id,
        )
    return ProjectMutationResponse(
        **ProjectResponse.model_validate(project_data).model_dump(),
        lifecycle_results=lifecycle_results,
    )


def _attach_project_relationships(
    project: dict[str, typing.Any],
    org_slug: str,
    request: fastapi.Request,
    outbound_count: int = 0,
    inbound_count: int = 0,
) -> None:
    """Attach relationships sub-object to a project dict."""
    project_id = project.get('id') or ''
    team = project.get('team', {})
    team_slug = team.get('slug', '') if team else ''
    project_url = request.app.url_path_for(
        'get_project', org_slug=org_slug, project_id=project_id
    )
    team_url = (
        request.app.url_path_for('get_team', org_slug=org_slug, slug=team_slug)
        if team_slug
        else ''
    )
    rels: dict[str, typing.Any] = dict(
        build_relationships(
            '',
            {
                'team': RelationshipSpec(team_url, 1 if team_slug else 0),
                'environments': RelationshipSpec(
                    f'{project_url}/environments',
                    len(project.get('environments') or []),
                ),
            },
        )
    )
    rels['href'] = request.app.url_path_for(
        'get_project_relationships',
        org_slug=org_slug,
        project_id=project_id,
    )
    rels['outbound_count'] = outbound_count
    rels['inbound_count'] = inbound_count
    project['relationships'] = rels


async def _resolve_release_display_names(
    db: graph.Graph,
    releases: dict[str, dict[str, ReleaseInfo]],
) -> None:
    """Replace ``performed_by`` emails with the user's display name.

    Operates in-place on the releases map. Emails with no matching
    user fall back to the local-part; anything else is left alone.
    """
    emails = list(
        {
            info.performed_by
            for env_map in releases.values()
            for info in env_map.values()
            if info.performed_by
        }
    )
    display_names = await _resolve_display_names(db, emails)
    for env_map in releases.values():
        for slug, info in env_map.items():
            if not info.performed_by:
                continue
            if info.performed_by in display_names:
                name: str = display_names[info.performed_by]
            elif '@' in info.performed_by:
                name = info.performed_by.split('@')[0]
            else:
                continue
            env_map[slug] = info.model_copy(update={'performed_by': name})


_FILTER_FIELD_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
_FILTER_OPS = frozenset({'eq', 'ne', 'in', 'not_in', 'exists', 'not_exists'})


def _build_attribute_filter(
    filters: list[str],
    whitelist: dict[str, blueprint_attributes.FilterableAttribute],
) -> tuple[str, dict[str, typing.Any]]:
    """Translate ``field:op[:value]`` predicates into a Cypher WHERE.

    Returns ``(fragment, params)`` where ``fragment`` is empty or a
    ``WHERE`` clause (predicates joined by AND) referencing the ``p``
    project node, and ``params`` holds the bound values. ``ne`` and
    ``not_in`` use plain inequality, so projects without the attribute
    set are excluded.

    Field names are validated against ``whitelist`` (and an identifier
    pattern) before being interpolated; values are always bound as
    query parameters. Raises ``HTTPException`` (400) on malformed
    predicates, unknown operators, or non-filterable fields.
    """
    clauses: list[str] = []
    params: dict[str, typing.Any] = {}
    for index, raw in enumerate(filters):
        field, _, rest = raw.partition(':')
        op, _, value = rest.partition(':')
        if not field or not op:
            raise fastapi.HTTPException(
                status_code=400,
                detail=f'Invalid filter {raw!r}; expected field:op[:value]',
            )
        if op not in _FILTER_OPS:
            raise fastapi.HTTPException(
                status_code=400,
                detail=(
                    f'Unknown filter operator {op!r}; valid operators are '
                    f'{", ".join(sorted(_FILTER_OPS))}'
                ),
            )
        if field not in whitelist or not _FILTER_FIELD_RE.match(field):
            raise fastapi.HTTPException(
                status_code=400,
                detail=(
                    f'Attribute {field!r} is not filterable for this '
                    'project type'
                ),
            )
        if op in ('exists', 'not_exists'):
            if value:
                raise fastapi.HTTPException(
                    status_code=400,
                    detail=(
                        f'Filter {raw!r} does not accept a value for '
                        f'operator {op!r}'
                    ),
                )
            null_op = 'IS NOT NULL' if op == 'exists' else 'IS NULL'
            clauses.append(f'p.{field} {null_op}')
            continue
        if op in ('eq', 'ne') and value == '':
            raise fastapi.HTTPException(
                status_code=400,
                detail=f'Filter {raw!r} requires a value',
            )
        values = (
            [v for v in value.split(',') if v]
            if op in ('in', 'not_in')
            else [value]
        )
        if not values:
            raise fastapi.HTTPException(
                status_code=400,
                detail=f'Filter {raw!r} requires a value',
            )
        comparator = '=' if op in ('eq', 'in') else '<>'
        joiner = ' OR ' if op in ('eq', 'in') else ' AND '
        terms: list[str] = []
        for value_index, item in enumerate(values):
            key = f'f{index}_{value_index}'
            params[key] = item
            terms.append(f'p.{field} {comparator} {{{key}}}')
        clauses.append(
            terms[0] if len(terms) == 1 else '(' + joiner.join(terms) + ')'
        )
    if not clauses:
        return '', params
    return 'WHERE ' + ' AND '.join(clauses), params


@projects_router.get('/', name='list_projects')
async def list_projects(
    org_slug: str,
    request: fastapi.Request,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
    project_type: str | None = None,
    include_archived: bool = False,
    slim: bool = False,
    integration_slug: typing.Annotated[
        str | None,
        fastapi.Query(
            description=(
                'Restrict results to projects that have an EXISTS_IN '
                'relationship to the integration with this slug '
                'in the organization. Combine with ``identifier`` to '
                'match a specific external identifier on that integration.'
            ),
        ),
    ] = None,
    identifier: typing.Annotated[
        str | None,
        fastapi.Query(
            description=(
                'Restrict results to projects whose EXISTS_IN edge to '
                '``integration_slug`` carries this external '
                'identifier (exact match). Requires '
                '``integration_slug``.'
            ),
        ),
    ] = None,
    filters: typing.Annotated[
        list[str] | None,
        fastapi.Query(
            alias='filter',
            description=(
                'Filter projects by blueprint attribute, as '
                '``field:op[:value]`` (repeatable; combined with AND). '
                'Operators: eq, ne, in, not_in (comma-separated values), '
                'exists, not_exists. ne/not_in exclude projects where the '
                'attribute is unset. Valid fields and enum values per '
                'project type come from the project-type listing with '
                '``include_schema=true``. Example: '
                'framework:ne:http-service-lib'
            ),
        ),
    ] = None,
) -> list[ProjectListItem] | list[ProjectResponse]:
    """List projects in the organization.

    By default archived projects are excluded.  Pass
    ``include_archived=true`` to include them.

    ``filter`` predicates match against blueprint-defined attributes
    stored on the project (e.g. ``framework``, ``programming_language``)
    using the field/operator grammar described on the parameter.

    ``integration_slug`` restricts the listing to projects that
    have an ``EXISTS_IN`` relationship to that integration within the
    organization; adding ``identifier`` further restricts to the
    project(s) whose edge carries that external identifier. ``identifier``
    is only meaningful alongside ``integration_slug`` and is
    rejected on its own. An unknown integration slug simply matches nothing.

    ``slim=true`` returns a stripped payload tailored to the
    projects-list UI: only the fields the list view reads (id, name,
    score, team slug+name, project_type slug+name+deployable,
    environment slug+name+label_color+sort_order, PR counts,
    current releases). Strips the embedded organization,
    blueprint dynamic fields, ``links``, ``identifiers``,
    DEPLOYED_IN edge properties, and the hypermedia
    ``relationships`` block. Cuts the response from megabytes to
    kilobytes for large orgs.
    """
    if identifier is not None and integration_slug is None:
        raise fastapi.HTTPException(
            status_code=422,
            detail=(
                'identifier requires integration_slug; an '
                'external identifier is only meaningful for a specific '
                'integration'
            ),
        )
    # Restrict to projects linked to an integration (and,
    # optionally, a specific external identifier on that edge). Closed
    # with ``WITH DISTINCT p, o`` so the optional ``identifier`` WHERE
    # never lands adjacent to the attribute filter's WHERE below.
    service_filter: typing.LiteralString = ''
    if integration_slug is not None:
        identifier_clause: typing.LiteralString = (
            'WHERE ei.identifier = {identifier}\n'
            if identifier is not None
            else ''
        )
        service_filter = (
            'MATCH (p)-[ei:EXISTS_IN]->'
            '(integration:Integration {{slug: {integration_slug}}})'
            '-[:BELONGS_TO]->(o)\n'
            + identifier_clause
            + 'WITH DISTINCT p, o\n'
        )
    type_filter: typing.LiteralString = (
        'MATCH (p)-[:TYPE]->(filter_pt:ProjectType {{slug: {project_type}}})'
        if project_type
        else ''
    )
    archived_filter: typing.LiteralString = (
        '' if include_archived else 'WHERE coalesce(p.archived, false) = false'
    )
    return_fragment: typing.LiteralString = (
        _SLIM_RETURN_FRAGMENT if slim else _RETURN_FRAGMENT
    )
    attr_filter = ''
    attr_params: dict[str, typing.Any] = {}
    if filters:
        whitelist = blueprint_attributes.resolve(
            await blueprint_attributes.project_blueprints(db),
            project_type,
        )
        fragment, attr_params = _build_attribute_filter(filters, whitelist)
        attr_filter = '\n    ' + fragment + '\n' if fragment else ''
    query: str = (
        """
    MATCH (p:Project)-[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    """
        + archived_filter
        + """
    WITH DISTINCT p, o
    """
        + service_filter
        + type_filter
        + attr_filter
        + return_fragment
        + """
    ORDER BY p.name
    """
    )
    columns: list[str] = (
        ['project'] if slim else ['project', 'outbound_count', 'inbound_count']
    )
    records = await db.execute(
        query,
        {
            'org_slug': org_slug,
            'project_type': project_type,
            'integration_slug': integration_slug,
            'identifier': identifier,
            **attr_params,
        },
        columns,
    )
    project_data_list: list[dict[str, typing.Any]] = []
    for record in records:
        project_data = graph.parse_agtype(record['project'])
        if not slim:
            _flatten_edge_props(project_data)
            _attach_project_relationships(
                project_data,
                org_slug,
                request,
                graph.parse_agtype(record['outbound_count']),
                graph.parse_agtype(record['inbound_count']),
            )
        else:
            # Strip null/empty entries AGE can inject when
            # ``collect(CASE WHEN ... END)`` matches nothing.
            for key in ('project_types', 'environments'):
                raw: list[typing.Any] = project_data.get(key) or []
                project_data[key] = [
                    item for item in raw if isinstance(item, dict) and item
                ]
        project_data_list.append(project_data)

    project_ids = [
        str(p.get('id', '')) for p in project_data_list if p.get('id')
    ]
    releasable_ids = [
        str(p.get('id', ''))
        for p in project_data_list
        if p.get('id')
        and any(
            pt.get('releasable')
            for pt in typing.cast(
                list[dict[str, typing.Any]],
                p.get('project_types') or [],
            )
        )
    ]
    viewer = auth.identity_for('github-enterprise-cloud')
    pr_counts, releases, release_summaries = await asyncio.gather(
        _fetch_pr_counts(project_ids, viewer=viewer),
        _fetch_current_releases(db, project_ids),
        _fetch_release_summaries(releasable_ids),
    )

    await _resolve_release_display_names(db, releases)

    for project_data in project_data_list:
        pid = str(project_data.get('id', ''))
        open_count, closed_count, viewer_open, viewer_closed = pr_counts.get(
            pid, (0, 0, 0, 0)
        )
        project_data['open_pr_count'] = open_count
        project_data['closed_pr_count'] = closed_count
        project_data['viewer_open_pr_count'] = viewer_open
        project_data['viewer_closed_pr_count'] = viewer_closed
        project_data['current_releases'] = releases.get(pid, {})
        summary = release_summaries.get(pid)
        if summary is not None:
            project_data['release_summary'] = summary.model_dump()

    if slim:
        return [ProjectListItem.model_validate(p) for p in project_data_list]
    return [ProjectResponse.model_validate(p) for p in project_data_list]


class BlueprintSectionProperty(pydantic.BaseModel):
    """A single property from a blueprint's JSON Schema."""

    model_config = pydantic.ConfigDict(
        populate_by_name=True, serialize_by_alias=True
    )

    type: str | None = None
    format: str | None = None
    title: str | None = None
    description: str | None = None
    enum: list[str] | None = None
    default: typing.Any = None
    minimum: float | None = None
    maximum: float | None = None
    x_ui: dict[str, typing.Any] = pydantic.Field(
        default_factory=dict,
        alias='x-ui',
        serialization_alias='x-ui',
    )
    #: Optional value-display transforms (e.g. ``{'format': 'humanize'}``)
    #: applied to the rendered value, independent of ``x-ui`` color/icon
    #: resolution (which keys off the raw value).
    x_display: dict[str, typing.Any] = pydantic.Field(
        default_factory=dict,
        alias='x-display',
        serialization_alias='x-display',
    )


class BlueprintSection(pydantic.BaseModel):
    """One blueprint's contribution to the project schema."""

    name: str
    slug: str
    description: str | None = None
    #: ``project`` for node blueprints (project-level attributes);
    #: ``environment`` for relationship blueprints on the
    #: ``Project -[:DEPLOYED_IN]-> Environment`` edge (per-environment
    #: edge attributes rendered in the Environments card).
    scope: typing.Literal['project', 'environment'] = 'project'
    properties: dict[str, BlueprintSectionProperty]


class ProjectSchemaResponse(pydantic.BaseModel):
    """Fully resolved, blueprint-grouped schema for a project."""

    sections: list[BlueprintSection]


@projects_router.get('/{project_id}/schema')
async def get_project_schema(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
) -> ProjectSchemaResponse:
    """Return the merged blueprint schema for a specific project.

    Resolves the project's own types and environments, matches every
    applicable blueprint, and returns the properties grouped by
    blueprint so the UI can render labelled sections.
    """
    # Fetch the project's type slugs and environment slugs
    lookup: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (p)-[:TYPE]->(pt:ProjectType)
          -[:BELONGS_TO]->(o)
    WITH p, o, collect(pt.slug) AS type_slugs
    OPTIONAL MATCH (p)-[:DEPLOYED_IN]->(env:Environment)
          -[:BELONGS_TO]->(o)
    WITH type_slugs, collect(env.slug) AS env_slugs
    RETURN type_slugs, env_slugs
    """
    records = await db.execute(
        lookup,
        {
            'project_id': project_id,
            'org_slug': org_slug,
        },
        ['type_slugs', 'env_slugs'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )

    type_slugs: set[str] = set(
        graph.parse_agtype(records[0]['type_slugs']) or []
    )
    env_slugs: set[str] = set(
        graph.parse_agtype(records[0]['env_slugs']) or []
    )

    def _build_section(
        bp: models.Blueprint,
        scope: typing.Literal['project', 'environment'],
    ) -> BlueprintSection | None:
        """Build a schema section from a blueprint, or ``None`` to skip.

        A blueprint is skipped when its filter doesn't intersect the
        project's own types/envs, or when it declares no properties. A
        blueprint with no filter matches everything; a ``project_type``
        filter matches if any of the project's types appear in it (same
        for ``environment``).
        """
        f = bp.filter
        if f is not None:
            if f.project_type and not type_slugs.intersection(f.project_type):
                return None
            if f.environment and not env_slugs.intersection(f.environment):
                return None
        schema = bp.json_schema
        if not schema.properties:
            return None
        props: dict[str, BlueprintSectionProperty] = {}
        for prop_name, prop_schema in schema.properties.items():
            extra = prop_schema.model_extra or {}
            x_ui = dict(extra.get('x-ui') or {})
            if x_ui.get('editable') is None:
                x_ui['editable'] = True
            raw_x_display = extra.get('x-display')
            props[prop_name] = BlueprintSectionProperty(
                type=getattr(prop_schema, 'type', None),
                format=getattr(prop_schema, 'format', None),
                title=getattr(prop_schema, 'title', None),
                description=getattr(prop_schema, 'description', None),
                enum=getattr(prop_schema, 'enum', None),
                default=getattr(prop_schema, 'default', None),
                minimum=getattr(prop_schema, 'minimum', None),
                maximum=getattr(prop_schema, 'maximum', None),
                **{'x-ui': x_ui, 'x-display': dict(raw_x_display or {})},
            )
        return BlueprintSection(
            name=bp.name,
            slug=bp.slug or '',
            description=bp.description,
            scope=scope,
            properties=props,
        )

    # Node blueprints (project-level attributes) ...
    node_blueprints = await db.match(
        models.Blueprint,
        {'type': 'Project', 'enabled': True},
        order_by='priority',
    )
    # ... and relationship blueprints on the
    # ``Project -[:DEPLOYED_IN]-> Environment`` edge (per-environment edge
    # attributes), which carry the same JSON-Schema + ``x-ui`` metadata so
    # the UI renders them with the shared attribute-display logic.
    rel_blueprints = await db.match(
        models.Blueprint,
        {'kind': 'relationship', 'enabled': True},
        order_by='priority',
    )

    sections: list[BlueprintSection] = []
    for bp in node_blueprints:
        section = _build_section(bp, 'project')
        if section is not None:
            sections.append(section)
    for bp in rel_blueprints:
        if (
            bp.source != 'Project'
            or bp.target != 'Environment'
            or bp.edge != 'DEPLOYED_IN'
        ):
            continue
        section = _build_section(bp, 'environment')
        if section is not None:
            sections.append(section)

    return ProjectSchemaResponse(sections=sections)


class EnvironmentEdgeUpdate(pydantic.BaseModel):
    """Edge-property updates for a project's ``DEPLOYED_IN`` edge.

    Keys are blueprint-defined edge attributes (accepted via
    ``extra='allow'``). A non-null value sets the property; a ``null``
    value removes it.
    """

    model_config = pydantic.ConfigDict(extra='allow')


@projects_router.patch('/{project_id}/environments/{env_slug}')
async def patch_project_environment(
    org_slug: str,
    project_id: str,
    env_slug: str,
    updates: EnvironmentEdgeUpdate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('project:write')),
    ],
) -> dict[str, typing.Any]:
    """Update ``DEPLOYED_IN`` edge properties for a single environment.

    Performs targeted per-key ``SET`` / ``REMOVE`` on the one
    ``(project)-[:DEPLOYED_IN]->(environment)`` edge, so it neither
    rewrites the other environments' edges nor relies on edge deletion
    (both of which behave unreliably on some Apache AGE builds). Protected
    structural keys are rejected. Returns the updated edge properties.
    """
    extra = updates.model_extra or {}
    protected_keys = sorted(k for k in extra if k in _PROTECTED_ENV_KEYS)
    if protected_keys:
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                'Protected environment fields are not editable via this '
                f'endpoint: {protected_keys!r}'
            ),
        )
    props = dict(extra)
    if not props:
        raise fastapi.HTTPException(
            status_code=400,
            detail='No editable edge properties provided',
        )

    params: dict[str, typing.Any] = {
        'project_id': project_id,
        'org_slug': org_slug,
        'env_slug': env_slug,
    }
    set_parts: list[str] = []
    remove_parts: list[str] = []
    for i, (key, value) in enumerate(props.items()):
        if value is None:
            remove_parts.append(f'r.{escape_prop(key)}')
        else:
            param = f'edge_{i}'
            set_parts.append(f'r.{escape_prop(key)} = {{{param}}}')
            params[param] = value

    mutations = ''
    if set_parts:
        mutations += ' SET ' + ', '.join(set_parts)
    if remove_parts:
        mutations += ' REMOVE ' + ', '.join(remove_parts)

    query: str = (
        'MATCH (p:Project {{id: {project_id}}})'
        '-[:OWNED_BY]->(:Team)'
        '-[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})'
        ' MATCH (p)-[r:DEPLOYED_IN]->'
        '(e:Environment {{slug: {env_slug}}})-[:BELONGS_TO]->(o)'
        + mutations
        + ' RETURN properties(r) AS props'
    )
    records = await db.execute(query, params, ['props'])
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Project {project_id!r} is not deployed in '
                f'environment {env_slug!r}'
            ),
        )
    edge_props: dict[str, typing.Any] = (
        graph.parse_agtype(records[0]['props']) or {}
    )
    return {
        k: v for k, v in edge_props.items() if k not in _PROTECTED_ENV_KEYS
    }


@projects_router.get('/{project_id}', name='get_project')
async def get_project(
    org_slug: str,
    project_id: str,
    request: fastapi.Request,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
    breakdown: bool = False,
) -> ProjectResponse:
    """Get a project by ID."""
    query: typing.LiteralString = (
        """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    WITH DISTINCT p, o
    """
        + _RETURN_FRAGMENT
    )
    records = await db.execute(
        query,
        {
            'project_id': project_id,
            'org_slug': org_slug,
        },
        ['project', 'outbound_count', 'inbound_count'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )
    project_data = graph.parse_agtype(records[0]['project'])
    _flatten_edge_props(project_data)
    _attach_project_relationships(
        project_data,
        org_slug,
        request,
        graph.parse_agtype(records[0]['outbound_count']),
        graph.parse_agtype(records[0]['inbound_count']),
    )
    response = ProjectResponse.model_validate(project_data)
    if breakdown:
        try:
            score, bd = await compute_score(db, project_id)
            if score is not None:
                response.score = score
                response.breakdown = bd
        except ValueError:
            LOGGER.warning(
                'compute_score failed for project %s',
                project_id,
                exc_info=True,
            )
    return response


class ProjectRelationshipSummary(pydantic.BaseModel):
    """Summary of the project on the other end of an edge."""

    id: str
    name: str
    slug: str
    namespace: str | None = None
    project_type: str | None = None
    project_type_icon: str | None = None
    deprecated: bool = False

    @pydantic.field_validator('deprecated', mode='before')
    @classmethod
    def _coerce_deprecated(cls, value: object) -> bool:
        """Normalise AGE's mixed bool/string storage to a real bool."""
        if isinstance(value, str):
            return value.strip().lower() == 'true'
        return bool(value)


class ProjectRelationship(pydantic.BaseModel):
    """A single DEPENDS_ON edge touching the project."""

    direction: typing.Literal['inbound', 'outbound']
    type: typing.Literal['depends_on'] = 'depends_on'
    project: ProjectRelationshipSummary


class ProjectRelationshipsResponse(pydantic.BaseModel):
    """Wrapped list of relationships."""

    relationships: list[ProjectRelationship]


_RELATIONSHIPS_QUERY: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    WITH p
    OPTIONAL MATCH (p)-[r:DEPENDS_ON]-(other:Project)
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(otherOrg:Organization)
    OPTIONAL MATCH (other)-[:TYPE]->(pt:ProjectType)
    WITH p, r, other, otherOrg, pt
    ORDER BY pt.slug
    WITH p, r, other, otherOrg,
         collect(pt.slug)[0] AS pt_slug,
         collect(pt.icon)[0] AS pt_icon,
         CASE WHEN r IS NULL THEN null
              WHEN startNode(r) = p THEN 'outbound'
              ELSE 'inbound'
         END AS direction
    RETURN direction,
           CASE WHEN other IS NULL THEN null
                ELSE other{{.id, .name, .slug, .deprecated,
                           namespace: otherOrg.slug,
                           project_type: pt_slug,
                           project_type_icon: pt_icon}}
           END AS other
    ORDER BY CASE direction WHEN 'inbound' THEN 0
                            WHEN 'outbound' THEN 1
                            ELSE 2 END,
             other.name,
             other.id
"""


async def _fetch_relationships(
    db: graph.Pool,
    project_id: str,
    org_slug: str,
) -> list[ProjectRelationship]:
    """Fetch all DEPENDS_ON edges for a project, sorted inbound-first."""
    records = await db.execute(
        _RELATIONSHIPS_QUERY,
        {'project_id': project_id, 'org_slug': org_slug},
        ['direction', 'other'],
    )
    relationships: list[ProjectRelationship] = []
    for record in records:
        direction = graph.parse_agtype(record['direction'])
        other = graph.parse_agtype(record['other'])
        if not direction or not other:
            continue
        relationships.append(
            ProjectRelationship(
                direction=direction,
                project=ProjectRelationshipSummary.model_validate(other),
            ),
        )
    return relationships


_PROJECT_EXISTS_QUERY: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    RETURN p.id AS id
"""


@projects_router.get(
    '/{project_id}/relationships', name='get_project_relationships'
)
async def list_project_relationships(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
) -> ProjectRelationshipsResponse:
    """List every DEPENDS_ON edge touching the project.

    Returns both inbound and outbound edges in a flat list with a
    ``direction`` field. Rows are sorted inbound first, then by
    the related project's name.
    """
    exists = await db.execute(
        _PROJECT_EXISTS_QUERY,
        {'project_id': project_id, 'org_slug': org_slug},
        ['id'],
    )
    if not exists:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )
    return ProjectRelationshipsResponse(
        relationships=await _fetch_relationships(db, project_id, org_slug),
    )


@projects_router.post(
    '/{project_id}/relationships/{target_id}',
    status_code=204,
)
async def create_project_relationship(
    org_slug: str,
    project_id: str,
    target_id: str,
    db: graph.Pool,
    valkey_client: OptionalValkeyClient,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:write'),
        ),
    ],
) -> None:
    """Create a single ``DEPENDS_ON`` edge from source to target project.

    Idempotent: if the edge already exists, returns 204 without error.

    Raises:
        400: ``project_id`` equals ``target_id`` (self-reference).
        404: Source or target project does not exist within ``org_slug``.
    """
    if project_id == target_id:
        raise fastapi.HTTPException(
            status_code=400,
            detail='A project cannot depend on itself',
        )

    query: typing.LiteralString = """
    MATCH (src:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    MATCH (tgt:Project {{id: {target_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    MERGE (src)-[:DEPENDS_ON]->(tgt)
    RETURN src.id AS source_id
    """
    records = await db.execute(
        query,
        {
            'project_id': project_id,
            'org_slug': org_slug,
            'target_id': target_id,
        },
        ['source_id'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Project {project_id!r} or target {target_id!r} not found'
            ),
        )
    # The source project gained a dependency, which can change a
    # condition-policy score that reads its neighbours. No-op unless a
    # condition policy exists.
    if await score_queue.condition_policies_exist(db):
        await score_queue.enqueue_recompute(
            valkey_client, project_id, 'dependency_change'
        )


@projects_router.delete(
    '/{project_id}/relationships/{target_id}',
    status_code=204,
)
async def delete_project_relationship(
    org_slug: str,
    project_id: str,
    target_id: str,
    db: graph.Pool,
    valkey_client: OptionalValkeyClient,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:write'),
        ),
    ],
) -> None:
    """Remove a ``DEPENDS_ON`` edge from source to target project.

    Raises:
        404: The edge does not exist (source, target, or the edge
            itself may be missing).
    """
    query: typing.LiteralString = """
    MATCH (src:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    MATCH (tgt:Project {{id: {target_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    MATCH (src)-[r:DEPENDS_ON]->(tgt)
    DELETE r
    RETURN src.id AS source_id
    """
    records = await db.execute(
        query,
        {
            'project_id': project_id,
            'org_slug': org_slug,
            'target_id': target_id,
        },
        ['source_id'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Relationship from {project_id!r} to {target_id!r} not found'
            ),
        )
    # The source project lost a dependency; re-score it so a condition
    # policy reading its neighbours reflects the change. No-op unless a
    # condition policy exists.
    if await score_queue.condition_policies_exist(db):
        await score_queue.enqueue_recompute(
            valkey_client, project_id, 'dependency_change'
        )


async def _validate_update_refs(
    db: graph.Pool,
    org_slug: str,
    data: ProjectUpdate,
) -> None:
    """Validate team, project type, and environment references.

    Raises HTTPException 422 if any referenced slugs do not exist.
    Called by the PATCH handler before executing the update.
    """
    if data.team_slug:
        team_check: typing.LiteralString = """
        MATCH (t:Team {{slug: {team_slug}}})
              -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
        RETURN t.slug AS slug
        """
        team_records = await db.execute(
            team_check,
            {'team_slug': data.team_slug, 'org_slug': org_slug},
            ['slug'],
        )
        if not team_records:
            raise fastapi.HTTPException(
                status_code=422,
                detail=(
                    f'Team {data.team_slug!r} not found in'
                    f' organization {org_slug!r}'
                ),
            )

    if data.project_type_slugs is not None:
        pt_check: typing.LiteralString = """
        MATCH (o:Organization {{slug: {org_slug}}})
        UNWIND {pt_slugs} AS pt_slug
        OPTIONAL MATCH (pt:ProjectType {{slug: pt_slug}})
                 -[:BELONGS_TO]->(o)
        RETURN pt_slug, pt IS NOT NULL AS found
        """
        pt_records = await db.execute(
            pt_check,
            {
                'org_slug': org_slug,
                'pt_slugs': data.project_type_slugs,
            },
            ['pt_slug', 'found'],
        )
        missing = [
            graph.parse_agtype(r['pt_slug'])
            for r in pt_records
            if not graph.parse_agtype(r['found'])
        ]
        if missing:
            raise fastapi.HTTPException(
                status_code=422,
                detail=(
                    f'Project type slug(s) not found: {sorted(missing)!r}'
                ),
            )

    if data.environments is not None and data.environments:
        await _validate_env_slugs(
            db,
            org_slug,
            list(data.environments.keys()),
        )


def _build_update_clauses(
    data: ProjectUpdate,
) -> tuple[str, dict[str, typing.Any]]:
    """Build Cypher relationship-change clauses for a project update.

    Returns ``(rel_clauses, env_params)`` where ``rel_clauses`` is
    appended to the main update query and ``env_params`` must be
    merged into the query parameter dict.
    """
    rel_clauses: str = ''
    if data.team_slug:
        # MERGE (not CREATE) so the retry loop in
        # _execute_project_update cannot accumulate duplicate edges
        # if AGE rolls back the SET phase but not the edge write.
        rel_clauses += """
    WITH p, o
    MATCH (new_t:Team {{slug: {new_team_slug}}})
          -[:BELONGS_TO]->(o)
    OPTIONAL MATCH (p)-[old_own:OWNED_BY]->(:Team)
    DELETE old_own
    MERGE (p)-[:OWNED_BY]->(new_t)
    """
    if data.project_type_slugs is not None:
        # MERGE (not CREATE) so the retry loop in
        # _execute_project_update cannot accumulate duplicate edges
        # if AGE rolls back the SET phase but not the edge write.
        rel_clauses += """
    WITH DISTINCT p, o
    OPTIONAL MATCH (p)-[old_type:TYPE]->(:ProjectType)
    DELETE old_type
    WITH DISTINCT p, o
    UNWIND {new_type_slugs} AS new_pt_slug
    MATCH (new_pt:ProjectType {{slug: new_pt_slug}})
          -[:BELONGS_TO]->(o)
    MERGE (p)-[:TYPE]->(new_pt)
    """
    new_env_entries = [
        {'slug': s, **ep} for s, ep in (data.environments or {}).items()
    ]
    new_env_tpl, new_env_params = _env_entries_template(new_env_entries)
    new_edge_props_tpl = _edge_props_map(new_env_entries)

    if data.environments is not None:
        # Replace the project's DEPLOYED_IN edges wholesale: delete the
        # existing ones, then re-create them with inline edge properties
        # (mirroring ``create_project``). We deliberately avoid
        # ``MERGE (p)-[r]->(e) SET r = {map}``: some Apache AGE builds
        # silently no-op a full-property ``SET r = {map}`` on a
        # relationship, dropping every edge attribute, whereas inline
        # ``CREATE ... {props}`` persists reliably. The DELETE and CREATE
        # run in the same transaction as one ``execute`` call, so a
        # retried attempt (see _execute_project_update) rolls back wholly
        # and cannot accumulate duplicate edges.
        rel_clauses += (
            ' WITH DISTINCT p, o'
            ' OPTIONAL MATCH'
            ' (p)-[old_env:DEPLOYED_IN]->(:Environment)'
            ' DELETE old_env'
        )
        if new_env_entries:
            rel_clauses += (
                ' WITH DISTINCT p, o'
                f' UNWIND {new_env_tpl} AS entry'
                ' MATCH (e:Environment'
                ' {{slug: entry.slug}})-[:BELONGS_TO]->(o)'
                ' CREATE (p)-[:DEPLOYED_IN' + new_edge_props_tpl + ']->(e)'
            )

    return rel_clauses, new_env_params


async def _execute_project_update(
    project_id: str,
    org_slug: str,
    data: ProjectUpdate,
    existing_p: dict[str, typing.Any],
    existing_team: str,
    existing_types: list[str],
    request: fastapi.Request,
    db: graph.Pool,
) -> ProjectResponse:
    """Execute the shared update logic for the PATCH handler.

    Merges ``data`` with the existing project node, validates
    references, builds and runs the Cypher update query, and
    returns the updated ``ProjectResponse``.

    Args:
        project_id: The project's nano-ID.
        org_slug: Organization slug from the URL path.
        data: Validated ``ProjectUpdate`` instance with the new values.
        existing_p: Current project node properties (flat dict).
        existing_team: Current team slug.
        existing_types: Current project-type slugs.
        db: Graph connection pool.

    """
    effective_team = data.team_slug or existing_team
    effective_types = data.project_type_slugs or existing_types

    dynamic_model = await blueprints.get_model(
        db,
        models.Project,
        context={'project_type': effective_types},
    )

    # Pre-parse JSON-string fields that the graph stores as strings.
    existing_json = deserialize_json_fields(existing_p, _PROJECT_JSON_FIELDS)
    existing_links: dict[str, typing.Any] = existing_json['links']
    existing_identifiers: dict[str, typing.Any] = existing_json['identifiers']

    # Merge provided fields with existing values.
    merged = {
        'name': data.name or existing_p.get('name', ''),
        'slug': data.slug or existing_p.get('slug', ''),
        'description': (
            data.description
            if data.description is not None
            else existing_p.get('description')
        ),
        'icon': (
            data.icon if data.icon is not None else existing_p.get('icon')
        ),
        'links': (data.links if data.links is not None else existing_links),
        'identifiers': (
            data.identifiers
            if data.identifiers is not None
            else existing_identifiers
        ),
    }

    # Merge blueprint extra fields: start from existing unknown keys,
    # then overlay any extras supplied by the caller.
    base_fields = set(ProjectUpdate.model_fields)
    skip = {
        'id',
        'team',
        'project_types',
        'environments',
        'created_at',
        'updated_at',
    }
    extra_fields = {
        k: v
        for k, v in existing_p.items()
        if k not in base_fields and k not in skip
    }
    extra_fields.update(
        {
            k: v
            for k, v in (data.model_extra or {}).items()
            if k not in _RESERVED_FIELDS
        }
    )

    try:
        project = dynamic_model(
            id=project_id,
            team=models.Team(
                name='',
                slug=effective_team,
                organization=models.Organization(
                    name='',
                    slug=org_slug,
                ),
            ),
            project_types=[],
            environments=[],
            **merged,  # type: ignore[arg-type]
            **extra_fields,
        )
    except pydantic.ValidationError as e:
        LOGGER.warning('Validation error updating project: %s', e)
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    raw_created = existing_p.get('created_at')
    project.created_at = (
        datetime.datetime.fromisoformat(raw_created)
        if raw_created
        else datetime.datetime.now(datetime.UTC)
    )
    project.updated_at = datetime.datetime.now(datetime.UTC)
    props = project.model_dump(
        mode='json',
        exclude={
            'team',
            'project_types',
            'environments',
        },
    )
    props = serialize_json_fields(props, _PROJECT_JSON_FIELDS)

    # Pre-validate referenced slugs before mutating to prevent
    # partial writes (team, project types, environments).
    await _validate_update_refs(db, org_slug, data)

    rel_clauses, new_env_params = _build_update_clauses(data)
    set_stmt = set_clause('p', props)

    update_query: str = (
        """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    WITH DISTINCT p, o
    """
        + set_stmt
        + rel_clauses
        + """
    WITH DISTINCT p, o
    """
        + _RETURN_FRAGMENT
    )

    update_params: dict[str, typing.Any] = {
        'project_id': project_id,
        'org_slug': org_slug,
        **props,
        'new_team_slug': data.team_slug or '',
        'new_type_slugs': data.project_type_slugs or [],
        **new_env_params,
    }
    # AGE sporadically raises "Entity failed to be updated" on
    # multi-stage MATCH/SET queries even when the entity exists.
    # The error is non-deterministic and resolves on retry, so wrap
    # the update in a short bounded retry loop.  ``UniqueViolation``
    # is a real conflict and is surfaced as 409 immediately.
    updated: list[dict[str, typing.Any]] = []
    for attempt in range(3):
        try:
            updated = await db.execute(
                update_query,
                update_params,
                ['project', 'outbound_count', 'inbound_count'],
            )
            break
        except psycopg.errors.UniqueViolation as e:
            raise fastapi.HTTPException(
                status_code=409,
                detail=str(e),
            ) from e
        except psycopg.errors.InternalError as e:
            if 'Entity failed to be updated' not in str(e) or attempt == 2:
                raise
            LOGGER.warning(
                'AGE update retry %d/3 for project %r: %s',
                attempt + 1,
                project_id,
                e,
            )
            await asyncio.sleep(0.05 * (attempt + 1))

    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )

    updated_data = graph.parse_agtype(updated[0]['project'])
    _flatten_edge_props(updated_data)
    _attach_project_relationships(
        updated_data,
        org_slug,
        request,
        graph.parse_agtype(updated[0]['outbound_count']),
        graph.parse_agtype(updated[0]['inbound_count']),
    )
    return ProjectResponse.model_validate(updated_data)


@projects_router.patch('/{project_id}')
async def patch_project(
    org_slug: str,
    project_id: str,
    operations: list[json_patch.PatchOperation],
    request: fastapi.Request,
    background: fastapi.BackgroundTasks,
    db: graph.Pool,
    valkey_client: OptionalValkeyClient,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:write'),
        ),
    ],
    transfer_repository: bool = False,
) -> ProjectMutationResponse:
    """Partially update a project using JSON Patch (RFC 6902).

    Parameters:
        org_slug: Organization slug from URL path.
        project_id: Project nano-ID from URL.
        operations: JSON Patch operations list.
        transfer_repository: When the patch changes
            ``project_type_slugs`` and the operator opted in (via the
            ``/lifecycle/preview`` UI affordance), also dispatch
            ``'relocated'`` so lifecycle plugins can move the backing
            remote (e.g. a GitHub repo transfer) to the new mapping.
            Defaults to ``False`` so a type change alone never moves
            the remote.

    Returns:
        The updated project.

    Raises:
        400: Invalid patch or read-only path.
        404: Project not found.
        409: Slug conflict.
        422: Patch test failed or environment validation failed.

    """
    # Fetch full current state (same query as get_project).
    fetch_query: typing.LiteralString = (
        """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    WITH DISTINCT p, o
    """
        + _RETURN_FRAGMENT
    )
    records = await db.execute(
        fetch_query,
        {
            'project_id': project_id,
            'org_slug': org_slug,
        },
        ['project', 'outbound_count', 'inbound_count'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )

    project_data = graph.parse_agtype(records[0]['project'])
    _flatten_edge_props(project_data)

    # Build patchable document from ProjectUpdate-compatible fields.
    parsed_json = deserialize_json_fields(project_data, _PROJECT_JSON_FIELDS)
    parsed_links: dict[str, typing.Any] = parsed_json['links']
    parsed_identifiers: dict[str, typing.Any] = parsed_json['identifiers']

    team_data: typing.Any = project_data.get('team') or {}
    current_team_slug: str = typing.cast(str, team_data.get('slug') or '')

    pts: list[typing.Any] = project_data.get('project_types') or []
    current_type_slugs: list[str] = [
        typing.cast(str, pt['slug']) for pt in pts if pt and pt.get('slug')
    ]

    envs: list[typing.Any] = project_data.get('environments') or []
    current_environments: dict[str, dict[str, typing.Any]] = {}
    for env in envs:
        if env and env.get('slug'):
            env_slug: str = typing.cast(str, env['slug'])
            edge_props: dict[str, typing.Any] = {
                k: v for k, v in env.items() if k not in _PROTECTED_ENV_KEYS
            }
            current_environments[env_slug] = edge_props

    base_fields = set(ProjectUpdate.model_fields)
    extras = {
        k: v
        for k, v in project_data.items()
        if k not in base_fields and k not in _RESERVED_FIELDS
    }
    patchable: dict[str, typing.Any] = {
        'name': project_data.get('name', ''),
        'slug': project_data.get('slug', ''),
        'description': project_data.get('description'),
        'icon': project_data.get('icon'),
        'team_slug': current_team_slug,
        'project_type_slugs': current_type_slugs,
        'environments': current_environments,
        'links': parsed_links,
        'identifiers': parsed_identifiers,
        **extras,
    }

    before_snapshot = dict(patchable)
    patched = json_patch.apply_patch(patchable, operations)

    try:
        update_data = ProjectUpdate(**patched)
    except pydantic.ValidationError as e:
        LOGGER.warning('Validation error patching project: %s', e)
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    response = await _execute_project_update(
        project_id,
        org_slug,
        update_data,
        project_data,
        current_team_slug,
        current_type_slugs,
        request,
        db,
    )
    await score_queue.enqueue_recompute(
        valkey_client, project_id, 'attribute_change'
    )
    # A changed attribute (e.g. ``deprecated``) can flip a condition
    # policy on any project that depends on this one, so re-score the
    # one-hop dependents too. No-op unless a condition policy exists.
    await score_queue.enqueue_dependents(valkey_client, db, project_id)
    # H13: ClickHouse insert is non-critical for the response, so move
    # it off the hot path. The graph write already succeeded; the
    # events row exists to feed the activity log and can lag by
    # milliseconds without anyone noticing.
    background.add_task(
        _emit_change_events,
        project_id,
        auth.principal_name,
        before_snapshot,
        patched,
    )
    # Only dispatch ``updated`` when the slug or description actually
    # changed: lifecycle plugins translate those into remote rename /
    # description writes, and firing on every PATCH (e.g. an icon
    # change) would pay an HTTP round trip for nothing.  Name does not
    # gate the dispatch because GitHub has no display-name field --
    # the plugin would always no-op.
    previous_slug = str(before_snapshot.get('slug') or '') or None
    previous_description = before_snapshot.get('description')
    slug_changed = previous_slug is not None and response.slug != previous_slug
    description_changed = response.description != previous_description
    lifecycle_results: list[LifecycleInvocation] = []
    if slug_changed or description_changed:
        try:
            lifecycle_results = await dispatch_lifecycle(
                db,
                project_id,
                org_slug,
                'updated',
                auth,
                previous_project_slug=previous_slug if slug_changed else None,
                project_name=response.name,
                project_description=response.description,
                project_ui_url=_build_project_ui_url(org_slug, project_id),
            )
        except Exception:
            LOGGER.exception(
                'Lifecycle dispatch failed after updating project %s',
                project_id,
            )
    # ``transfer_repository`` is a deliberate opt-in: it never fires for
    # an unchanged project-type set, and never fires implicitly on a
    # type change.  The UI surfaces the would-relocate preview from
    # ``/lifecycle/preview`` and only sets this flag when the operator
    # checks the "Also move repository" box.
    new_type_slugs_raw: typing.Any = patched.get('project_type_slugs') or []
    new_type_slugs: list[str] = [
        s
        for s in typing.cast(list[typing.Any], new_type_slugs_raw)
        if isinstance(s, str) and s
    ]
    types_changed = set(new_type_slugs) != set(current_type_slugs)
    # A team reassignment is also a relocation for team-keyed lifecycle
    # plugins (e.g. PagerDuty repoints the service's escalation policy to
    # the new team's).  Unlike the type-driven repo move, it is not gated
    # on ``transfer_repository`` -- it fires whenever the owning team
    # changes.  Type-keyed plugins (e.g. GitHub) see ``current_type_slugs``
    # unchanged and no-op.
    new_team_slug = update_data.team_slug
    team_changed = bool(new_team_slug) and new_team_slug != current_team_slug
    if (transfer_repository and types_changed) or team_changed:
        try:
            relocate_results = await dispatch_lifecycle(
                db,
                project_id,
                org_slug,
                'relocated',
                auth,
                previous_project_slug=previous_slug if slug_changed else None,
                previous_project_type_slugs=current_type_slugs,
                previous_team_slug=current_team_slug if team_changed else None,
                project_name=response.name,
                project_description=response.description,
                project_ui_url=_build_project_ui_url(org_slug, project_id),
            )
            lifecycle_results = [*lifecycle_results, *relocate_results]
        except Exception:
            LOGGER.exception(
                'Lifecycle relocate dispatch failed after updating project %s',
                project_id,
            )
    return ProjectMutationResponse(
        **response.model_dump(),
        lifecycle_results=lifecycle_results,
    )


@projects_router.get('/{project_id}/lifecycle/preview')
async def preview_lifecycle(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
    project_type_slugs: typing.Annotated[
        list[str],
        fastapi.Query(
            description=(
                'Hypothetical project-type slug set to evaluate. '
                'Repeatable, e.g. '
                '``?project_type_slugs=api&project_type_slugs=consumer``.'
            ),
        ),
    ],
) -> LifecyclePreviewResponse:
    """Preview the relocation outcome of a project-type change.

    Resolves every lifecycle plugin assigned to the project (project- +
    project-type-level), then asks each plugin's
    :meth:`LifecycleCapability.resolve_relocation_target` what target it
    would route to *today* vs *given the hypothetical type set*.  The UI
    uses ``would_relocate=True`` rows to surface the "Also move
    repository to ``<display>``?" opt-in checkbox on the project-type
    edit dialog.

    The plugin contract requires ``resolve_relocation_target`` to be
    local-only (no remote calls), so this endpoint is cheap to poll on
    every selection change.  Per-plugin exceptions are swallowed -- a
    broken plugin must not block the rest of the preview.
    """
    del auth  # read-only preview; authorization handled by the dependency.
    exists_query: typing.LiteralString = (
        'MATCH (p:Project {{id: {project_id}}}) '
        '-[:OWNED_BY]->(:Team) '
        '-[:BELONGS_TO]->(:Organization {{slug: {org_slug}}}) '
        'RETURN p.id AS id'
    )
    exists = await db.execute(
        exists_query,
        {'project_id': project_id, 'org_slug': org_slug},
        ['id'],
    )
    if not exists:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )
    bundle = await build_lifecycle_context_bundle(db, project_id)
    resolved = await resolve_all_capabilities(db, project_id, 'lifecycle')
    if not resolved:
        return LifecyclePreviewResponse(previews=[])

    # Strip empties + duplicates while preserving order so the
    # hypothetical type set behaves like the stored one.
    next_types: list[str] = []
    seen: set[str] = set()
    for slug in project_type_slugs:
        slug = slug.strip()
        if slug and slug not in seen:
            next_types.append(slug)
            seen.add(slug)

    previews: list[LifecyclePreviewEntry] = []
    for plugin in resolved:
        handler = typing.cast(LifecycleCapability, plugin.capability_cls())
        current_ctx = PluginContext(
            project_id=project_id,
            project_slug=bundle.project_slug,
            org_slug=org_slug,
            team_slug=bundle.team_slug,
            assignment_options=plugin.capability_options,
            integration_slug=plugin.integration_slug,
            integration_options=plugin.integration_options,
            capability_options=plugin.capability_options,
            project_links=bundle.project_links,
            project_type_slugs=bundle.project_type_slugs,
        )
        next_ctx = current_ctx.model_copy(
            update={'project_type_slugs': next_types}
        )
        current_target = await _safe_resolve_target(handler, current_ctx)
        next_target = await _safe_resolve_target(handler, next_ctx)
        would_relocate = next_target is not None and (
            current_target is None
            or current_target.identifier != next_target.identifier
        )
        previews.append(
            LifecyclePreviewEntry(
                integration_id=plugin.integration_id,
                plugin_slug=plugin.plugin_slug,
                current_target=current_target,
                next_target=next_target,
                would_relocate=would_relocate,
            )
        )
    return LifecyclePreviewResponse(previews=previews)


async def _safe_resolve_target(
    handler: LifecycleCapability,
    ctx: PluginContext,
) -> RelocationTarget | None:
    """Call ``resolve_relocation_target``, swallowing plugin errors.

    A broken plugin must not poison the preview for the others; log and
    return ``None`` so the row reports ``would_relocate=False``.  The
    plugin contract guarantees the call is local-only, so credentials
    can be an empty dict.
    """
    try:
        return await handler.resolve_relocation_target(ctx, {})
    except Exception:
        LOGGER.exception(
            'resolve_relocation_target raised for integration %s '
            'on project %s',
            ctx.integration_slug,
            ctx.project_id,
        )
        return None


async def _set_archived_state(
    org_slug: str,
    project_id: str,
    archived: bool,
    request: fastapi.Request,
    db: graph.Pool,
) -> ProjectResponse:
    """Toggle archived state on a project and return the updated entity."""
    now = datetime.datetime.now(datetime.UTC).isoformat()
    archived_at: str | None = now if archived else None
    query: typing.LiteralString = (
        """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    SET p.archived = {archived},
        p.archived_at = {archived_at},
        p.updated_at = {updated_at}
    WITH DISTINCT p, o
    """
        + _RETURN_FRAGMENT
    )
    records = await db.execute(
        query,
        {
            'project_id': project_id,
            'org_slug': org_slug,
            'archived': archived,
            'archived_at': archived_at,
            'updated_at': now,
        },
        ['project', 'outbound_count', 'inbound_count'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )
    project_data = graph.parse_agtype(records[0]['project'])
    _flatten_edge_props(project_data)
    _attach_project_relationships(
        project_data,
        org_slug,
        request,
        graph.parse_agtype(records[0]['outbound_count']),
        graph.parse_agtype(records[0]['inbound_count']),
    )
    return ProjectResponse.model_validate(project_data)


@projects_router.post('/{project_id}/archive')
async def archive_project(
    org_slug: str,
    project_id: str,
    request: fastapi.Request,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:write'),
        ),
    ],
) -> ArchiveProjectResponse:
    """Archive a project (soft-hide from default listings)."""
    project = await _set_archived_state(
        org_slug, project_id, True, request, db
    )
    # State change is already committed; never let an unexpected
    # dispatcher failure turn a successful archive into a 500.
    try:
        results = await dispatch_lifecycle(
            db, project_id, org_slug, 'archived', auth
        )
    except Exception:
        LOGGER.exception(
            'Lifecycle dispatch failed after archiving project %s',
            project_id,
        )
        results = []
    return ArchiveProjectResponse(
        **project.model_dump(),
        lifecycle_results=results,
    )


@projects_router.post('/{project_id}/unarchive')
async def unarchive_project(
    org_slug: str,
    project_id: str,
    request: fastapi.Request,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:write'),
        ),
    ],
) -> ArchiveProjectResponse:
    """Restore an archived project to the active state."""
    project = await _set_archived_state(
        org_slug, project_id, False, request, db
    )
    # State change is already committed; never let an unexpected
    # dispatcher failure turn a successful unarchive into a 500.
    try:
        results = await dispatch_lifecycle(
            db, project_id, org_slug, 'unarchived', auth
        )
    except Exception:
        LOGGER.exception(
            'Lifecycle dispatch failed after unarchiving project %s',
            project_id,
        )
        results = []
    return ArchiveProjectResponse(
        **project.model_dump(),
        lifecycle_results=results,
    )


@projects_router.delete('/{project_id}')
async def delete_project(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:delete'),
        ),
    ],
    delete_repository: bool = True,
) -> ProjectDeletedResponse:
    """Delete a project.

    When ``delete_repository`` is true (the default), each assigned
    lifecycle plugin's ``on_project_deleted`` hook is also invoked so
    the backing remote (e.g. a GitHub repo) is removed alongside the
    Imbi project node.  Set ``delete_repository=false`` to keep the
    remote in place -- useful when the repository has historical value
    that should survive the project being retired.

    Returns a 200 with the per-plugin :class:`LifecycleInvocation`
    list rather than the bare 204 the pre-2.8 endpoint emitted.  An
    empty ``lifecycle_results`` list means either no lifecycle plugins
    were assigned, or ``delete_repository=false`` short-circuited the
    dispatch.
    """
    # Capture the lifecycle context bundle *before* the DETACH DELETE
    # so the project's links / slug / type slugs survive the write and
    # the downstream dispatcher doesn't try to look them up against a
    # node that no longer exists.
    bundle = (
        await build_lifecycle_context_bundle(db, project_id)
        if delete_repository
        else None
    )

    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    DETACH DELETE p
    RETURN p
    """
    records = await db.execute(
        query,
        {
            'project_id': project_id,
            'org_slug': org_slug,
        },
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )

    # Project node is gone; never let a dispatch hiccup turn a
    # successful delete into a 500.  ``delete_repository=false`` skips
    # the dispatch entirely so the operator can retire the project
    # without nuking the remote.
    lifecycle_results: list[LifecycleInvocation] = []
    if delete_repository and bundle is not None:
        try:
            lifecycle_results = await dispatch_lifecycle(
                db,
                project_id,
                org_slug,
                'deleted',
                auth,
                bundle=bundle,
            )
        except Exception:
            LOGGER.exception(
                'Lifecycle dispatch failed after deleting project %s',
                project_id,
            )
    return ProjectDeletedResponse(lifecycle_results=lifecycle_results)
