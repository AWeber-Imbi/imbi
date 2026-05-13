"""Release CRUD and deployment-edge endpoints.

Releases are identified by a per-project ``version`` string. The
``Release`` node is connected to its ``Project`` via an incoming
``HAS_RELEASE`` edge and to every ``Environment`` it has been
deployed to via a ``DEPLOYED_TO`` edge carrying an append-only
``deployments`` history.

"""

import asyncio
import datetime
import json
import logging
import typing

import fastapi
import nanoid
import pydantic
from imbi_common import graph, models
from imbi_common.plugins.base import CheckStatus

from imbi_api import patch as json_patch
from imbi_api.auth import permissions
from imbi_api.plugins import call_with_timeout

LOGGER = logging.getLogger(__name__)

releases_router = fastapi.APIRouter(tags=['Releases'])


_DEPLOYMENT_STATUS = typing.Literal[
    'pending',
    'in_progress',
    'success',
    'failed',
    'rolled_back',
]


# -- Request / Response models ------------------------------------------


class ReleaseCreate(pydantic.BaseModel):
    """Request body for creating a release."""

    model_config = pydantic.ConfigDict(extra='forbid')

    version: str
    title: str
    description: str | None = None
    links: list[models.ReleaseLink] = []
    created_by: str | None = None


class ReleaseUpdate(pydantic.BaseModel):
    """JSON Patch-compatible release shape.

    Only ``title``, ``description``, and ``links`` may be patched;
    ``version`` / ``id`` / timestamps / project are read-only.
    """

    model_config = pydantic.ConfigDict(extra='forbid')

    title: str | None = None
    description: str | None = None
    links: list[models.ReleaseLink] | None = None


class ReleaseResponse(pydantic.BaseModel):
    """Response body for a release."""

    id: str
    project_id: str
    version: str
    title: str
    description: str | None = None
    links: list[models.ReleaseLink] = []
    created_at: datetime.datetime
    updated_at: datetime.datetime | None = None
    created_by: str

    @pydantic.field_validator('links', mode='before')
    @classmethod
    def _parse_links(cls, value: typing.Any) -> typing.Any:
        if isinstance(value, str):
            return json.loads(value)
        return value


class DeploymentEventInput(pydantic.BaseModel):
    """Request body for recording a deployment event."""

    model_config = pydantic.ConfigDict(extra='forbid')

    status: _DEPLOYMENT_STATUS
    note: str | None = None


class ReleaseEnvironmentRef(pydantic.BaseModel):
    """Minimal environment identity returned on edge responses."""

    slug: str
    name: str


class ReleaseEnvironmentEdgeResponse(pydantic.BaseModel):
    """Response body for a release/environment deployment edge."""

    environment: ReleaseEnvironmentRef
    deployments: list[models.DeploymentEvent] = []
    current_status: _DEPLOYMENT_STATUS | None = None


class CurrentReleaseEnvironment(pydantic.BaseModel):
    """Latest deployment state for one environment of a project.

    ``release`` and ``current_status`` are ``None`` when the project is
    configured to deploy in the environment but has no recorded
    deployment events there yet.

    ``external_run_url`` and ``ci_status`` are populated by the
    deployment-plugin hydration pass: the former is the workflow run
    URL of the latest event (when present), the latter the aggregate
    check-runs status of the deployed version (``None`` when the
    plugin can't or won't report it).
    """

    environment: ReleaseEnvironmentRef
    release: ReleaseResponse | None = None
    current_status: _DEPLOYMENT_STATUS | None = None
    last_event_at: datetime.datetime | None = None
    external_run_url: str | None = None
    ci_status: CheckStatus | None = None


# -- Helpers ------------------------------------------------------------


_RELEASE_READONLY_PATHS: frozenset[str] = frozenset(
    [
        '/id',
        '/version',
        '/project_id',
        '/created_at',
        '/updated_at',
        '/created_by',
    ]
)


def _serialize_links(
    links: list[models.ReleaseLink] | list[dict[str, typing.Any]],
) -> str:
    """Serialize a list of release links to a JSON string for storage."""
    out: list[dict[str, typing.Any]] = []
    for link in links:
        if isinstance(link, models.ReleaseLink):
            out.append(link.model_dump(mode='json'))
        else:
            out.append(models.ReleaseLink(**link).model_dump(mode='json'))
    return json.dumps(out)


def _parse_deployments(
    raw: typing.Any,
) -> list[models.DeploymentEvent]:
    """Parse the JSON-encoded ``deployments`` edge property."""
    if not raw:
        return []
    data = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(data, list):
        return []
    items: list[typing.Any] = data  # type: ignore[assignment]
    return [models.DeploymentEvent.model_validate(e) for e in items]


def _release_to_response(
    data: dict[str, typing.Any],
    project_id: str,
) -> ReleaseResponse:
    """Build a ``ReleaseResponse`` from a parsed release node dict."""
    raw_links: typing.Any = data.get('links') or []
    if isinstance(raw_links, str):
        raw_links = json.loads(raw_links)
    return ReleaseResponse.model_validate(
        {
            'id': data['id'],
            'project_id': project_id,
            'version': data['version'],
            'title': data['title'],
            'description': data.get('description'),
            'links': raw_links,
            'created_at': data['created_at'],
            'updated_at': data.get('updated_at'),
            'created_by': data['created_by'],
        }
    )


async def _project_exists(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
) -> bool:
    """Return True when the project exists in the given organization."""
    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    RETURN p.id AS id
    """
    rows = await db.execute(
        query,
        {'project_id': project_id, 'org_slug': org_slug},
        ['id'],
    )
    return bool(rows)


async def _fetch_release(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
    version: str,
) -> dict[str, typing.Any] | None:
    """Fetch a release node by project and version."""
    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    MATCH (p)-[:HAS_RELEASE]->(r:Release {{version: {version}}})
    RETURN r{{.*}} AS release
    """
    rows = await db.execute(
        query,
        {
            'project_id': project_id,
            'org_slug': org_slug,
            'version': version,
        },
        ['release'],
    )
    if not rows:
        return None
    return typing.cast(
        dict[str, typing.Any], graph.parse_agtype(rows[0]['release'])
    )


_RUN_STATUS_TO_EVENT_STATUS: dict[str, _DEPLOYMENT_STATUS] = {
    'queued': 'pending',
    'in_progress': 'in_progress',
    'success': 'success',
    'failure': 'failed',
    # The DeploymentEvent literal has no 'cancelled' bucket; treat
    # it as a failed terminal so the train stops showing "deploying…".
    'cancelled': 'failed',
}


async def _hydrate_release_train(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
    auth: permissions.AuthContext,
    by_env: dict[
        str,
        tuple[
            dict[str, typing.Any],
            dict[str, typing.Any] | None,
            models.DeploymentEvent | None,
        ],
    ],
) -> dict[str, CheckStatus | None]:
    """Hydrate live deploy run + CI check-runs status per env.

    Mutates ``by_env`` in place: when the plugin reports a terminal
    status for an in-flight workflow run we update the in-memory event
    so the response reflects the live state, and we append a fresh
    ``DeploymentEvent`` to the edge so the system self-heals on
    subsequent reads.  Returns a slug → ``CheckStatus`` map that the
    caller folds into the response.

    Failures are tolerated silently — the release train must keep
    rendering even if the plugin can't be resolved or its calls hiccup.
    """
    in_flight: list[tuple[str, str, models.DeploymentEvent]] = []
    deployed: list[tuple[str, str]] = []
    for slug, (_env, release_raw, event) in by_env.items():
        if release_raw is None:
            continue
        version = str(release_raw.get('version') or '')
        if not version:
            continue
        deployed.append((slug, version))
        if (
            event is not None
            and event.status == 'in_progress'
            and event.external_run_id
        ):
            in_flight.append((slug, version, event))

    if not in_flight and not deployed:
        return {}

    # Lazy import to avoid a circular dependency: project_deployments
    # already imports ``append_deployment_event`` from this module.
    from imbi_api.endpoints.project_deployments import (
        _handler,  # pyright: ignore[reportPrivateUsage]
        _resolve_and_context,  # pyright: ignore[reportPrivateUsage]
    )

    try:
        resolved, ctx, credentials = await _resolve_and_context(
            db, org_slug, project_id, auth
        )
    except fastapi.HTTPException:
        return {}
    except Exception:  # noqa: BLE001
        LOGGER.debug(
            'release-train hydration: plugin resolution failed',
            exc_info=True,
        )
        return {}
    handler = _handler(resolved)

    run_results = await asyncio.gather(
        *(
            call_with_timeout(
                handler.get_deployment_status(
                    ctx, credentials, run_id=str(event.external_run_id)
                )
            )
            for _, _, event in in_flight
        ),
        return_exceptions=True,
    )
    ci_results = await asyncio.gather(
        *(
            call_with_timeout(
                handler.get_check_status(ctx, credentials, committish=version)
            )
            for _, version in deployed
        ),
        return_exceptions=True,
    )

    for (slug, version, event), result in zip(
        in_flight, run_results, strict=True
    ):
        if isinstance(result, BaseException):
            continue
        new_status = _RUN_STATUS_TO_EVENT_STATUS.get(result.status)
        if new_status is None or new_status == event.status:
            continue
        new_event = event.model_copy(
            update={
                'status': new_status,
                'timestamp': datetime.datetime.now(datetime.UTC),
            }
        )
        env, release_raw, _ = by_env[slug]
        by_env[slug] = (env, release_raw, new_event)
        if new_status in ('success', 'failed'):
            try:
                await append_deployment_event(
                    db,
                    org_slug=org_slug,
                    project_id=project_id,
                    version=version,
                    env_slug=slug,
                    status=new_status,
                    note='via release-train hydration',
                    external_run_id=event.external_run_id,
                    external_run_url=event.external_run_url,
                )
            except Exception:
                LOGGER.exception(
                    'release-train hydration: failed to persist '
                    'terminal event for %s/%s',
                    project_id,
                    slug,
                )

    ci_status_by_slug: dict[str, CheckStatus | None] = {}
    for (slug, _version), ci_result in zip(deployed, ci_results, strict=True):
        if isinstance(ci_result, BaseException) or ci_result == 'unknown':
            ci_status_by_slug[slug] = None
        else:
            ci_status_by_slug[slug] = ci_result
    return ci_status_by_slug


# -- Endpoints ----------------------------------------------------------


@releases_router.post('/', status_code=201, response_model=ReleaseResponse)
async def create_release(
    org_slug: str,
    project_id: str,
    data: ReleaseCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:write'),
        ),
    ],
) -> ReleaseResponse:
    """Create a new release for a project."""
    version = data.version

    if not await _project_exists(db, org_slug, project_id):
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )

    # Per-project version uniqueness pre-check.
    existing_query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
          -[:HAS_RELEASE]->(r:Release {{version: {version}}})
    RETURN r.id AS id
    """
    existing = await db.execute(
        existing_query,
        {'project_id': project_id, 'version': version},
        ['id'],
    )
    if existing:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Release {version!r} already exists'
                f' for project {project_id!r}'
            ),
        )

    # Spec calls for ``auth.user.username``; the User model uses
    # ``email`` as the principal identity (no ``username`` field).
    # ``principal_name`` returns the user's email or the service
    # account's slug — matching the convention used by opslog.
    created_by = data.created_by or auth.principal_name
    now = datetime.datetime.now(datetime.UTC)
    props: dict[str, typing.Any] = {
        'id': nanoid.generate(),
        'version': version,
        'title': data.title,
        'description': data.description,
        'links': _serialize_links(data.links),
        'created_by': created_by,
        'created_at': now.isoformat(),
        'updated_at': now.isoformat(),
    }

    create_query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
    CREATE (r:Release {{
        id: {id},
        version: {version},
        title: {title},
        description: {description},
        links: {links},
        created_by: {created_by},
        created_at: {created_at},
        updated_at: {updated_at}
    }})
    CREATE (p)-[:HAS_RELEASE]->(r)
    RETURN r{{.*}} AS release
    """
    rows = await db.execute(
        create_query,
        {'project_id': project_id, **props},
        ['release'],
    )
    if not rows:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )
    release_data = graph.parse_agtype(rows[0]['release'])
    return _release_to_response(release_data, project_id)


@releases_router.get('/', response_model=list[ReleaseResponse])
async def list_releases(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
) -> list[ReleaseResponse]:
    """List all releases for a project, newest first."""
    del auth
    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    MATCH (p)-[:HAS_RELEASE]->(r:Release)
    RETURN r{{.*}} AS release
    ORDER BY r.created_at DESC
    """
    rows = await db.execute(
        query,
        {'project_id': project_id, 'org_slug': org_slug},
        ['release'],
    )
    return [
        _release_to_response(graph.parse_agtype(r['release']), project_id)
        for r in rows
    ]


@releases_router.get(
    '/current',
    response_model=list[CurrentReleaseEnvironment],
)
async def list_current_releases(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
) -> list[CurrentReleaseEnvironment]:
    """List the most-current release per environment for a project.

    For each environment the project is configured to deploy in
    (``DEPLOYED_IN``), returns the release whose ``DEPLOYED_TO`` edge
    contains the deployment event with the latest timestamp.
    Environments with no deployment events are returned with
    ``release=None``. Results are sorted by ``Environment.sort_order``
    ascending, then by name.

    The deployment plugin (when bound) is consulted for live workflow
    run status on any in-flight ``DeploymentEvent`` and aggregate CI
    check-runs status on each env's currently-deployed version.
    Hydration failures are tolerated silently.
    """
    if not await _project_exists(db, org_slug, project_id):
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )

    query: typing.LiteralString = """
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
    rows = await db.execute(
        query,
        {'project_id': project_id, 'org_slug': org_slug},
        ['env', 'release', 'deployments'],
    )

    # Group by env.slug; keep the (release, event) pair with the latest
    # event timestamp. Envs with no deployments are seeded with None.
    by_env: dict[
        str,
        tuple[
            dict[str, typing.Any],
            dict[str, typing.Any] | None,
            models.DeploymentEvent | None,
        ],
    ] = {}

    for row in rows:
        env = graph.parse_agtype(row['env'])
        if not env:
            continue
        slug = env['slug']
        release_raw = graph.parse_agtype(row['release'])
        events = _parse_deployments(graph.parse_agtype(row['deployments']))

        if release_raw is None or not events:
            by_env.setdefault(slug, (env, None, None))
            continue

        latest = max(events, key=lambda ev: ev.timestamp)
        existing = by_env.get(slug)
        if (
            existing is None
            or existing[2] is None
            or latest.timestamp > existing[2].timestamp
        ):
            by_env[slug] = (env, release_raw, latest)

    ci_status_by_slug = await _hydrate_release_train(
        db, org_slug, project_id, auth, by_env
    )

    sortable: list[tuple[int, str, CurrentReleaseEnvironment]] = []
    for env, release_raw, event in by_env.values():
        release_resp = (
            _release_to_response(release_raw, project_id)
            if release_raw is not None
            else None
        )
        item = CurrentReleaseEnvironment(
            environment=ReleaseEnvironmentRef(
                slug=env['slug'], name=env['name']
            ),
            release=release_resp,
            current_status=event.status if event else None,
            last_event_at=event.timestamp if event else None,
            external_run_url=event.external_run_url if event else None,
            ci_status=ci_status_by_slug.get(env['slug']),
        )
        sortable.append((env.get('sort_order') or 0, env['name'], item))

    sortable.sort(key=lambda t: (t[0], t[1]))
    return [item for _, _, item in sortable]


@releases_router.get('/{version}', response_model=ReleaseResponse)
async def get_release(
    org_slug: str,
    project_id: str,
    version: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
) -> ReleaseResponse:
    """Get a single release by version."""
    del auth
    data = await _fetch_release(db, org_slug, project_id, version)
    if data is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Release {version!r} for project {project_id!r} not found'
            ),
        )
    return _release_to_response(data, project_id)


@releases_router.patch('/{version}', response_model=ReleaseResponse)
async def patch_release(
    org_slug: str,
    project_id: str,
    version: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:write'),
        ),
    ],
) -> ReleaseResponse:
    """Apply a JSON Patch (RFC 6902) to a release."""
    del auth
    data = await _fetch_release(db, org_slug, project_id, version)
    if data is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Release {version!r} for project {project_id!r} not found'
            ),
        )

    raw_links: typing.Any = data.get('links') or []
    if isinstance(raw_links, str):
        raw_links = json.loads(raw_links)
    patchable: dict[str, typing.Any] = {
        'title': data['title'],
        'description': data.get('description'),
        'links': raw_links,
    }

    patched = json_patch.apply_patch(
        patchable, operations, _RELEASE_READONLY_PATHS
    )

    try:
        update = ReleaseUpdate(**patched)
    except pydantic.ValidationError as e:
        LOGGER.warning('Validation error patching release: %s', e)
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    now = datetime.datetime.now(datetime.UTC)
    # ``patched`` is the post-JSON-Patch document — treat it as the
    # source of truth rather than the ``ReleaseUpdate`` view so that
    # explicit nulls (e.g. ``remove`` of ``/description``) survive.
    # Use key presence, not truthiness, so explicit empty strings
    # (``replace /title ""``) are persisted rather than silently
    # reverted to the old value.
    merged_title = patched['title'] if 'title' in patched else data['title']
    merged_description = patched.get('description')
    merged_links_raw = patched.get('links', raw_links)
    serialized_links = _serialize_links(merged_links_raw)
    del update

    update_query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
          -[:HAS_RELEASE]->(r:Release {{version: {version}}})
    SET r.title = {title},
        r.description = {description},
        r.links = {links},
        r.updated_at = {updated_at}
    RETURN r{{.*}} AS release
    """
    rows = await db.execute(
        update_query,
        {
            'project_id': project_id,
            'version': version,
            'title': merged_title,
            'description': merged_description,
            'links': serialized_links,
            'updated_at': now.isoformat(),
        },
        ['release'],
    )
    if not rows:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Release {version!r} for project {project_id!r} not found'
            ),
        )
    release_data = graph.parse_agtype(rows[0]['release'])
    return _release_to_response(release_data, project_id)


# -- Deployment edge ----------------------------------------------------


async def _fetch_deployment_edge(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
    version: str,
    env_slug: str,
) -> tuple[dict[str, typing.Any] | None, list[models.DeploymentEvent]]:
    """Fetch environment and any existing DEPLOYED_TO edge."""
    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
          -[:HAS_RELEASE]->(r:Release {{version: {version}}})
    MATCH (e:Environment {{slug: {env_slug}}})
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (r)-[d:DEPLOYED_TO]->(e)
    RETURN e{{.slug, .name}} AS env,
           CASE WHEN d IS NULL THEN null ELSE d.deployments END
               AS deployments
    """
    rows = await db.execute(
        query,
        {
            'project_id': project_id,
            'version': version,
            'env_slug': env_slug,
            'org_slug': org_slug,
        },
        ['env', 'deployments'],
    )
    if not rows:
        return None, []
    env = graph.parse_agtype(rows[0]['env'])
    deployments = _parse_deployments(
        graph.parse_agtype(rows[0]['deployments'])
    )
    return env, deployments


def _edge_to_response(
    env: dict[str, typing.Any],
    deployments: list[models.DeploymentEvent],
) -> ReleaseEnvironmentEdgeResponse:
    """Build an edge response with derived ``current_status``."""
    return ReleaseEnvironmentEdgeResponse(
        environment=ReleaseEnvironmentRef(slug=env['slug'], name=env['name']),
        deployments=deployments,
        current_status=deployments[-1].status if deployments else None,
    )


#: Outcome reported by :func:`append_deployment_event`.  Lets callers
#: distinguish a brand-new row (``appended``) from a dedupe path that
#: refreshed an existing row in place (``updated``) versus a no-op
#: replay (``noop``).  The resync flow uses this to keep its summary
#: counters honest; the deploy/promote flows ignore it.
AppendOutcome = typing.Literal['appended', 'updated', 'noop']


async def append_deployment_event(
    db: graph.Graph,
    *,
    org_slug: str,
    project_id: str,
    version: str,
    env_slug: str,
    status: typing.Literal[
        'pending', 'in_progress', 'success', 'failed', 'rolled_back'
    ],
    note: str | None = None,
    external_run_id: str | None = None,
    external_run_url: str | None = None,
    timestamp: datetime.datetime | None = None,
) -> tuple[ReleaseEnvironmentEdgeResponse, AppendOutcome] | None:
    """Append a ``DeploymentEvent`` to ``Release -[:DEPLOYED_TO]-> Env``.

    Returns a ``(edge, outcome)`` tuple, or ``None`` when the named
    ``Release`` or ``Environment`` cannot be found — callers that
    auto-record from a deploy of a SHA (which has no ``Release`` node)
    treat ``None`` as "skip persistence, deploy still succeeded".

    ``outcome`` is one of ``'appended'`` (new row), ``'updated'``
    (dedupe path refreshed an existing row in place), or ``'noop'``
    (dedupe path matched an identical existing row and made no write).

    Deduplicates on ``external_run_id``: when the caller supplies one
    and the most recent existing event already carries the same id,
    the row is treated as a status update -- if ``status`` changed
    the existing event is updated in-place, otherwise the call is a
    no-op.  This lets resync re-replay the remote's recent history
    without doubling up rows on the edge, while still letting an
    in-flight workflow advance from ``in_progress`` -> ``success``.
    Callers that omit ``external_run_id`` keep the previous append-
    only semantics so the deploy / promote flows are unchanged.

    ``timestamp`` lets the resync flow record the remote's deployment
    creation time rather than ``now()``; defaults to now when omitted.
    """
    release = await _fetch_release(db, org_slug, project_id, version)
    if release is None:
        return None
    env, existing = await _fetch_deployment_edge(
        db, org_slug, project_id, version, env_slug
    )
    if env is None:
        return None
    if external_run_id and existing:
        # Walk newest-first so the "most recent event for this run"
        # wins when older entries with the same id exist (rare; only
        # possible if a caller appended duplicates before the dedupe
        # landed).  Comparing by status keeps the no-op fast path
        # cheap when resync re-runs against an idle remote.
        for idx in range(len(existing) - 1, -1, -1):
            candidate = existing[idx]
            if candidate.external_run_id == external_run_id:
                if (
                    candidate.status == status
                    and candidate.note == note
                    and candidate.external_run_url == external_run_url
                ):
                    return _edge_to_response(env, existing), 'noop'
                refreshed = candidate.model_copy(
                    update={
                        'status': status,
                        'note': note,
                        'external_run_url': external_run_url,
                        'timestamp': timestamp
                        or datetime.datetime.now(datetime.UTC),
                    }
                )
                updated_list = [
                    *existing[:idx],
                    refreshed,
                    *existing[idx + 1 :],
                ]
                updated_edge = await _set_deployments(
                    db,
                    project_id=project_id,
                    version=version,
                    env_slug=env_slug,
                    deployments=updated_list,
                    env=env,
                )
                return updated_edge, 'updated'
    event = models.DeploymentEvent(
        timestamp=timestamp or datetime.datetime.now(datetime.UTC),
        status=status,
        note=note,
        external_run_id=external_run_id,
        external_run_url=external_run_url,
    )
    deployments = [*existing, event]
    if existing:
        appended_edge = await _set_deployments(
            db,
            project_id=project_id,
            version=version,
            env_slug=env_slug,
            deployments=deployments,
            env=env,
        )
        return appended_edge, 'appended'
    created_edge = await _create_deployments_edge(
        db,
        project_id=project_id,
        version=version,
        env_slug=env_slug,
        org_slug=org_slug,
        deployments=deployments,
        env=env,
    )
    return created_edge, 'appended'


async def _set_deployments(
    db: graph.Graph,
    *,
    project_id: str,
    version: str,
    env_slug: str,
    deployments: list[models.DeploymentEvent],
    env: dict[str, typing.Any],
) -> ReleaseEnvironmentEdgeResponse:
    """Overwrite ``deployments`` on an existing ``DEPLOYED_TO`` edge."""
    serialized = json.dumps([e.model_dump(mode='json') for e in deployments])
    set_query: typing.LiteralString = """
    MATCH (:Project {{id: {project_id}}})
          -[:HAS_RELEASE]->(r:Release {{version: {version}}})
    MATCH (r)-[d:DEPLOYED_TO]->(:Environment {{slug: {env_slug}}})
    SET d.deployments = {deployments}
    RETURN d.deployments AS deployments
    """
    rows = await db.execute(
        set_query,
        {
            'project_id': project_id,
            'version': version,
            'env_slug': env_slug,
            'deployments': serialized,
        },
        ['deployments'],
    )
    if not rows:
        # The release or DEPLOYED_TO edge vanished between the read
        # phase and this write -- raise rather than silently report
        # success and skew resync counters.
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Release {version!r} or its deployment to '
                f'environment {env_slug!r} no longer exists'
            ),
        )
    return _edge_to_response(env, deployments)


async def _create_deployments_edge(
    db: graph.Graph,
    *,
    project_id: str,
    version: str,
    env_slug: str,
    org_slug: str,
    deployments: list[models.DeploymentEvent],
    env: dict[str, typing.Any],
) -> ReleaseEnvironmentEdgeResponse:
    """Create the first ``DEPLOYED_TO`` edge for ``(release, env)``."""
    serialized = json.dumps([e.model_dump(mode='json') for e in deployments])
    create_query: typing.LiteralString = """
    MATCH (:Project {{id: {project_id}}})
          -[:HAS_RELEASE]->(r:Release {{version: {version}}})
    MATCH (e:Environment {{slug: {env_slug}}})
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    CREATE (r)-[d:DEPLOYED_TO {{deployments: {deployments}}}]->(e)
    RETURN d.deployments AS deployments
    """
    rows = await db.execute(
        create_query,
        {
            'project_id': project_id,
            'version': version,
            'env_slug': env_slug,
            'org_slug': org_slug,
            'deployments': serialized,
        },
        ['deployments'],
    )
    if not rows:
        # Either the release or the (env, org) pair disappeared
        # between the read and this write; surface the failure rather
        # than silently report 'appended' with no persisted edge.
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Release {version!r} or environment {env_slug!r} in '
                f'organization {org_slug!r} no longer exists'
            ),
        )
    return _edge_to_response(env, deployments)


@releases_router.post(
    '/{version}/environments/{env_slug}',
    response_model=ReleaseEnvironmentEdgeResponse,
)
async def record_deployment(
    org_slug: str,
    project_id: str,
    version: str,
    env_slug: str,
    data: DeploymentEventInput,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:write'),
        ),
    ],
) -> ReleaseEnvironmentEdgeResponse:
    """Record a deployment event for a release in an environment."""
    del auth
    release = await _fetch_release(db, org_slug, project_id, version)
    if release is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Release {version!r} for project {project_id!r} not found'
            ),
        )

    env, existing = await _fetch_deployment_edge(
        db, org_slug, project_id, version, env_slug
    )
    if env is None:
        raise fastapi.HTTPException(
            status_code=422,
            detail=(
                f'Environment {env_slug!r} not found in'
                f' organization {org_slug!r}'
            ),
        )

    event = models.DeploymentEvent(
        timestamp=datetime.datetime.now(datetime.UTC),
        status=data.status,
        note=data.note,
    )
    deployments = [*existing, event]
    serialized = json.dumps(
        [e.model_dump(mode='json') for e in deployments],
    )

    if existing:
        set_query: typing.LiteralString = """
        MATCH (:Project {{id: {project_id}}})
              -[:HAS_RELEASE]->(r:Release {{version: {version}}})
        MATCH (r)-[d:DEPLOYED_TO]->(:Environment {{slug: {env_slug}}})
        SET d.deployments = {deployments}
        RETURN d.deployments AS deployments
        """
        await db.execute(
            set_query,
            {
                'project_id': project_id,
                'version': version,
                'env_slug': env_slug,
                'deployments': serialized,
            },
            ['deployments'],
        )
    else:
        create_query: typing.LiteralString = """
        MATCH (:Project {{id: {project_id}}})
              -[:HAS_RELEASE]->(r:Release {{version: {version}}})
        MATCH (e:Environment {{slug: {env_slug}}})
              -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
        CREATE (r)-[d:DEPLOYED_TO {{deployments: {deployments}}}]->(e)
        RETURN d.deployments AS deployments
        """
        await db.execute(
            create_query,
            {
                'project_id': project_id,
                'version': version,
                'env_slug': env_slug,
                'org_slug': org_slug,
                'deployments': serialized,
            },
            ['deployments'],
        )

    return _edge_to_response(env, deployments)


@releases_router.get(
    '/{version}/environments',
    response_model=list[ReleaseEnvironmentEdgeResponse],
)
async def list_deployment_edges(
    org_slug: str,
    project_id: str,
    version: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
) -> list[ReleaseEnvironmentEdgeResponse]:
    """List every environment edge for a release."""
    del auth
    release = await _fetch_release(db, org_slug, project_id, version)
    if release is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Release {version!r} for project {project_id!r} not found'
            ),
        )

    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    MATCH (p)-[:HAS_RELEASE]->(r:Release {{version: {version}}})
    MATCH (r)-[d:DEPLOYED_TO]->(e:Environment)
    RETURN e{{.slug, .name}} AS env, d.deployments AS deployments
    ORDER BY e.slug
    """
    rows = await db.execute(
        query,
        {
            'project_id': project_id,
            'org_slug': org_slug,
            'version': version,
        },
        ['env', 'deployments'],
    )
    results: list[ReleaseEnvironmentEdgeResponse] = []
    for row in rows:
        env = graph.parse_agtype(row['env'])
        if not env:
            continue
        deployments = _parse_deployments(
            graph.parse_agtype(row['deployments'])
        )
        results.append(_edge_to_response(env, deployments))
    return results


@releases_router.get(
    '/{version}/environments/{env_slug}',
    response_model=ReleaseEnvironmentEdgeResponse,
)
async def get_deployment_edge(
    org_slug: str,
    project_id: str,
    version: str,
    env_slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
) -> ReleaseEnvironmentEdgeResponse:
    """Get a single deployment edge by environment slug."""
    del auth
    release = await _fetch_release(db, org_slug, project_id, version)
    if release is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Release {version!r} for project {project_id!r} not found'
            ),
        )
    env, deployments = await _fetch_deployment_edge(
        db, org_slug, project_id, version, env_slug
    )
    if env is None or not deployments:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Deployment edge for release {version!r} in'
                f' environment {env_slug!r} not found'
            ),
        )
    return _edge_to_response(env, deployments)
