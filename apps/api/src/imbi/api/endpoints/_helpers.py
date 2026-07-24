"""Shared helpers for endpoint handlers."""

import collections.abc
import contextlib
import datetime
import json
import logging
import typing
import urllib.parse

import fastapi
import psycopg

from imbi.api import patch as json_patch
from imbi.common import graph
from imbi.common import models as common_models
from imbi.common.plugins.base import PluginContext, ServiceConnection

LOGGER = logging.getLogger(__name__)

T = typing.TypeVar('T')


async def fetch_or_404(
    fetch: collections.abc.Callable[..., collections.abc.Awaitable[T | None]],
    /,
    *args: typing.Any,
    detail: str,
    **kwargs: typing.Any,
) -> T:
    """Await ``fetch`` and raise 404 when it returns ``None``.

    Centralizes the ``await fetch(...) -> None -> raise 404`` pattern that
    every ``get_<resource>`` endpoint duplicates. ``detail`` is passed to
    the ``HTTPException`` unchanged.
    """
    result = await fetch(*args, **kwargs)
    if result is None:
        raise fastapi.HTTPException(status_code=404, detail=detail)
    return result


@contextlib.contextmanager
def conflict_on_unique_violation(
    detail: str,
) -> collections.abc.Generator[None]:
    """Translate ``psycopg.errors.UniqueViolation`` into a 409.

    Replaces the boilerplate try/except → ``HTTPException(409, ...)`` block
    that every create/update endpoint repeats around a single graph write
    that could collide on a unique edge or property.
    """
    try:
        yield
    except psycopg.errors.UniqueViolation as exc:
        raise fastapi.HTTPException(
            status_code=409,
            detail=detail,
        ) from exc


_USER_UPDATE_ROLE_QUERY: typing.LiteralString = """
MATCH (p:User {{email: {principal_value}}})
      -[m:MEMBER_OF]->(o:Organization {{slug: {org_slug}}})
SET m.role = {role_slug}
RETURN m.role AS role
"""

_SA_UPDATE_ROLE_QUERY: typing.LiteralString = """
MATCH (p:ServiceAccount {{slug: {principal_value}}})
      -[m:MEMBER_OF]->(o:Organization {{slug: {org_slug}}})
SET m.role = {role_slug}
RETURN m.role AS role
"""

_ROLE_EXISTS_QUERY: typing.LiteralString = (
    'MATCH (r:Role {{slug: {role_slug}}}) RETURN r.slug AS slug'
)


async def update_membership_role(
    db: graph.Graph,
    principal_label: typing.Literal['User', 'ServiceAccount'],
    principal_match_prop: typing.Literal['email', 'slug'],
    principal_value: str,
    org_slug: str,
    role_slug: str,
) -> None:
    """Update a principal's role in an organization.

    Parameters:
        db: Graph pool.
        principal_label: Node label of the principal ('User' or
            'ServiceAccount').
        principal_match_prop: Property used to match the principal
            ('email' or 'slug'). Must align with ``principal_label``:
            ``email`` for ``User`` and ``slug`` for ``ServiceAccount``.
        principal_value: Value for ``principal_match_prop``.
        org_slug: Slug of the organization.
        role_slug: Slug of the new role.

    Raises:
        fastapi.HTTPException: HTTP 404 if the target role does not
            exist or the principal is not a member of the organization.

    """
    role_records = await db.execute(
        _ROLE_EXISTS_QUERY,
        {'role_slug': role_slug},
        ['slug'],
    )
    if not role_records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Role {role_slug!r} not found',
        )

    if principal_label == 'User' and principal_match_prop == 'email':
        query = _USER_UPDATE_ROLE_QUERY
    elif (
        principal_label == 'ServiceAccount' and principal_match_prop == 'slug'
    ):
        query = _SA_UPDATE_ROLE_QUERY
    else:
        raise ValueError(
            f'Unsupported principal_label/match_prop combination:'
            f' {principal_label}/{principal_match_prop}'
        )

    records = await db.execute(
        query,
        {
            'principal_value': principal_value,
            'org_slug': org_slug,
            'role_slug': role_slug,
        },
        ['role'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'{principal_label} {principal_value!r} is not a member'
                f' of organization {org_slug!r}'
            ),
        )


_SAFE_AUDIT_URL_SCHEMES: frozenset[str] = frozenset({'http', 'https'})


def safe_audit_url(value: str | None) -> str | None:
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


def deployed_operation_log(
    *,
    project_id: str,
    project_slug: str,
    environment_slug: str,
    recorded_by: str,
    performed_by: str | None,
    action: str,
    version: str | None,
    plugin_slug: str = '',
    run_url: str | None = None,
    release_url: str | None = None,
    from_environment: str | None = None,
    external_run_id: str | None = None,
    occurred_at: datetime.datetime | None = None,
) -> common_models.OperationLog:
    """Build a ``Deployed`` ``operations_log`` row.

    Shared by the in-product deploy/promote audit writer and the
    maintenance ops-log backfill so the history pane renders every
    deploy identically. Plugin-supplied URLs (``run_url`` /
    ``release_url``) are filtered through :func:`safe_audit_url` so
    non-http(s) schemes never reach the audit JSON or the ``link``.

    ``occurred_at`` is only overridden when supplied; callers that
    backfill historical deploys pin it to the real deploy time because
    ``lookup_ops_log_performed_by`` ranks with
    ``argMax(performed_by, occurred_at)`` -- the row must sort by when
    the deploy actually happened, not when it was recorded. Omitting it
    keeps the model default (now).
    """
    safe_run_url = safe_audit_url(run_url)
    description = json.dumps(
        {
            'action': action,
            'plugin_slug': plugin_slug,
            'run_url': safe_run_url,
            'release_url': safe_audit_url(release_url),
            'from_environment': from_environment,
        },
        sort_keys=True,
    )
    fields: dict[str, typing.Any] = {
        'recorded_by': recorded_by,
        'performed_by': performed_by,
        'project_id': project_id,
        'project_slug': project_slug,
        'environment_slug': environment_slug,
        'entry_type': 'Deployed',
        'description': description,
        'link': safe_run_url,
        'version': version,
        'plugin_slug': plugin_slug,
        'external_run_id': external_run_id,
    }
    if occurred_at is not None:
        fields['occurred_at'] = occurred_at
    return common_models.OperationLog(**fields)


async def lookup_project_slugs(
    db: graph.Graph,
    project_id: str,
) -> tuple[str, str | None]:
    """Look up the project's slug and the slug of its owning team.

    Returns ``('', None)`` on lookup failure or missing project — these
    are template-only inputs (never authorization-relevant) and audit
    writes also tolerate an empty slug.
    """
    query: typing.LiteralString = (
        'MATCH (p:Project {{id: {project_id}}}) '
        'OPTIONAL MATCH (p)-[:OWNED_BY]->(t:Team) '
        'RETURN p.slug AS slug, t.slug AS team_slug'
    )
    try:
        records = await db.execute(
            query,
            {'project_id': project_id},
            ['slug', 'team_slug'],
        )
    except Exception:  # noqa: BLE001
        LOGGER.debug('Project slug lookup failed', exc_info=True)
        return '', None
    if not records:
        return '', None
    slug_raw = graph.parse_agtype(records[0]['slug'])
    team_raw = graph.parse_agtype(records[0].get('team_slug'))
    return (
        str(slug_raw) if slug_raw else '',
        str(team_raw) if team_raw else None,
    )


async def lookup_project_links(
    db: graph.Graph,
    project_id: str,
) -> dict[str, str]:
    """Return the project's external link map.

    Returns ``{}`` on lookup failure or when no links are set. Plugins
    use these as a side-channel for per-project state (e.g. resolving
    a GitHub owner/repo from the ``github-repository`` link) so that
    callers don't have to duplicate the data as assignment options.
    """
    query: typing.LiteralString = (
        'MATCH (p:Project {{id: {project_id}}}) RETURN p.links AS links'
    )
    try:
        records = await db.execute(
            query, {'project_id': project_id}, ['links']
        )
    except Exception:  # noqa: BLE001
        LOGGER.debug('Project links lookup failed', exc_info=True)
        return {}
    if not records:
        return {}
    raw = graph.parse_agtype(records[0].get('links'))
    # ``links`` is persisted as a JSON-encoded string on the AGE node
    # (not a property map), so ``parse_agtype`` returns ``str`` here —
    # decode it once more to recover the dict.
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except TypeError, ValueError:
            return {}
    if not isinstance(raw, dict):
        return {}
    items = typing.cast('dict[object, object]', raw)
    return {str(k): str(v) for k, v in items.items() if v}


async def update_project_link(
    db: graph.Graph,
    project_id: str,
    key: str,
    url: str,
) -> bool:
    """Set a single entry in the project's external link map.

    Reads the current links (via :func:`lookup_project_links`), sets
    ``links[key] = url``, and writes the map back as the JSON-encoded
    string ``p.links`` is stored as on the AGE node. Returns ``True`` when
    a write happened and ``False`` when the link already had ``url`` (a
    no-op). Used to self-heal a stale ``github-repository`` link after a
    deployment plugin reports the remote repository was renamed.
    """
    links = await lookup_project_links(db, project_id)
    if links.get(key) == url:
        return False
    links[key] = url
    query: typing.LiteralString = (
        'MATCH (p:Project {{id: {project_id}}}) '
        'SET p.links = {links} RETURN p.id AS id'
    )
    await db.execute(
        query,
        {'project_id': project_id, 'links': json.dumps(links)},
        ['id'],
    )
    return True


async def persist_link_writeback(db: graph.Graph, ctx: PluginContext) -> None:
    """Persist a project-link URL a plugin reported on ``ctx``.

    A deployment / lifecycle plugin sets ``ctx.link_writeback`` when the
    canonical URL for one of the project's external links has changed --
    e.g. after creating a new repo, after a rename that returned a
    ``301``, or after a transfer to a new owner. Rewrite the project's
    stored link so later calls hit the canonical URL and the UI shows
    the current name. Best-effort: a write failure is logged and
    swallowed so persistence never fails the user-facing request whose
    result we already have.
    """
    writeback = ctx.link_writeback
    if writeback is None:
        return
    try:
        changed = await update_project_link(
            db, ctx.project_id, writeback.link_key, writeback.new_url
        )
    except Exception:  # noqa: BLE001
        LOGGER.warning(
            'Failed to persist link writeback for project %s',
            ctx.project_id,
            exc_info=True,
        )
        return
    if changed:
        LOGGER.info(
            'Persisted %s link for project %s (%s -> %s)',
            writeback.link_key,
            ctx.project_id,
            writeback.old_owner_repo,
            writeback.new_owner_repo,
        )


async def merge_project_links(
    db: graph.Graph,
    project_id: str,
    *,
    add: dict[str, str] | None = None,
    remove: collections.abc.Iterable[str] | None = None,
) -> bool:
    """Apply additions and removals to the project's external link map.

    Reads the current links once, applies ``add`` (set/overwrite) and
    ``remove`` (drop keys), and writes the map back as the JSON-encoded
    string ``p.links`` is stored as on the AGE node. Returns ``True``
    when the map changed. Companion to :func:`update_project_link` for
    the multi-key / removal case driven by a service writeback.
    """
    links = await lookup_project_links(db, project_id)
    updated = dict(links)
    for key, url in (add or {}).items():
        if url:
            updated[key] = url
    for key in remove or ():
        updated.pop(key, None)
    if updated == links:
        return False
    query: typing.LiteralString = (
        'MATCH (p:Project {{id: {project_id}}}) '
        'SET p.links = {links} RETURN p.id AS id'
    )
    await db.execute(
        query,
        {'project_id': project_id, 'links': json.dumps(updated)},
        ['id'],
    )
    return True


async def lookup_project_exists_in(
    db: graph.Graph,
    project_id: str,
) -> list[ServiceConnection]:
    """Return the project's ``EXISTS_IN`` connections.

    One :class:`ServiceConnection` per
    ``(:Project)-[:EXISTS_IN]->(:Integration)`` edge, carrying the
    integration slug, the edge ``identifier``, and the canonical API
    URL. Returns ``[]`` on lookup failure or when the project exists in
    no integrations. Populated onto :attr:`PluginContext.service_connections`
    so plugins can read the relationship without re-querying the graph.
    """
    query: typing.LiteralString = (
        'MATCH (p:Project {{id: {project_id}}}) '
        '-[ei:EXISTS_IN]->(i:Integration) '
        'RETURN i.slug AS integration_slug, '
        'ei.identifier AS identifier, '
        'ei.canonical_url AS canonical_url'
    )
    try:
        records = await db.execute(
            query,
            {'project_id': project_id},
            ['integration_slug', 'identifier', 'canonical_url'],
        )
    except Exception:  # noqa: BLE001
        LOGGER.debug('Project EXISTS_IN lookup failed', exc_info=True)
        return []
    connections: list[ServiceConnection] = []
    for r in records:
        slug = graph.parse_agtype(r.get('integration_slug'))
        if not slug:
            continue
        identifier = graph.parse_agtype(r.get('identifier'))
        canonical_url = graph.parse_agtype(r.get('canonical_url'))
        connections.append(
            ServiceConnection(
                integration_slug=str(slug),
                identifier='' if identifier is None else str(identifier),
                canonical_url=(
                    None if canonical_url is None else str(canonical_url)
                ),
            )
        )
    return connections


async def persist_service_writeback(
    db: graph.Graph, ctx: PluginContext
) -> None:
    """Persist a project's service relationship a plugin reported on ``ctx``.

    A lifecycle plugin sets ``ctx.service_writeback`` when a call
    created, moved, or tore down the project's relationship with the
    Integration it is bound to (``ctx.integration_slug``). Upsert the
    ``EXISTS_IN`` edge (identifier + canonical API URL) and merge any
    dashboard links into ``Project.links`` -- or, when ``remove`` is set,
    delete the edge and drop those link keys. Best-effort: a write
    failure is logged and swallowed so persistence never fails the
    user-facing request whose result we already have.
    """
    writeback = ctx.service_writeback
    if writeback is None:
        return
    slug = ctx.integration_slug
    if not slug:
        LOGGER.warning(
            'Service writeback for project %s has no bound '
            'integration_slug; skipping',
            ctx.project_id,
        )
        return
    try:
        if writeback.remove:
            await _delete_exists_in(db, ctx.org_slug, ctx.project_id, slug)
            await merge_project_links(
                db, ctx.project_id, remove=writeback.dashboard_links.keys()
            )
        else:
            await _merge_exists_in(
                db,
                ctx.org_slug,
                ctx.project_id,
                slug,
                writeback.identifier,
                writeback.canonical_url,
                writeback.webhook_secret_enc,
            )
            await merge_project_links(
                db, ctx.project_id, add=writeback.dashboard_links
            )
    except Exception:  # noqa: BLE001
        LOGGER.warning(
            'Failed to persist service writeback for project %s (%s)',
            ctx.project_id,
            slug,
            exc_info=True,
        )
        return
    LOGGER.info(
        'Persisted EXISTS_IN edge for project %s -> %s (%s)',
        ctx.project_id,
        slug,
        'removed' if writeback.remove else writeback.identifier,
    )


async def _merge_exists_in(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
    integration_slug: str,
    identifier: str,
    canonical_url: str,
    webhook_secret_enc: str | None = None,
) -> None:
    """Upsert the ``EXISTS_IN`` edge for ``(project, integration)``.

    ``webhook_secret_enc`` is an opaque, already-encrypted secret (the
    plugin encrypts it; this never decrypts or re-encrypts it) stored on
    the edge alongside ``identifier`` for a gateway to read back at
    webhook-delivery time. When ``None`` the ``SET`` omits it, so an
    existing edge's secret is left untouched.
    """
    # Conditionally append the secret to the SET clause so a writeback
    # without one cannot null out a previously-stored secret. Both
    # branches are string literals, keeping the query a ``LiteralString``.
    secret_set: typing.LiteralString = (
        ',\n        ei.webhook_secret_enc = {webhook_secret_enc}'
        if webhook_secret_enc is not None
        else ''
    )
    query: typing.LiteralString = (
        """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    MATCH (i:Integration {{slug: {integration_slug}}})
          -[:BELONGS_TO]->(o)
    MERGE (p)-[ei:EXISTS_IN]->(i)
    SET ei.identifier = {identifier},
        ei.canonical_url = {canonical_url}"""
        + secret_set
        + """
    RETURN ei.identifier AS identifier
    """
    )
    params: dict[str, typing.Any] = {
        'org_slug': org_slug,
        'project_id': project_id,
        'integration_slug': integration_slug,
        'identifier': identifier,
        'canonical_url': canonical_url,
    }
    if webhook_secret_enc is not None:
        params['webhook_secret_enc'] = webhook_secret_enc
    await db.execute(query, params, ['identifier'])


async def _delete_exists_in(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
    integration_slug: str,
) -> None:
    """Remove the ``EXISTS_IN`` edge for ``(project, integration)``.

    Idempotent.
    """
    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (p)-[ei:EXISTS_IN]->
          (i:Integration {{slug: {integration_slug}}})
    DELETE ei
    """
    await db.execute(
        query,
        {
            'org_slug': org_slug,
            'project_id': project_id,
            'integration_slug': integration_slug,
        },
        [],
    )


async def lookup_project_type_slugs(
    db: graph.Graph,
    project_id: str,
) -> list[str]:
    """Return slugs for every ProjectType the project is tagged with.

    Returns ``[]`` on lookup failure or when the project has no type
    edges. Plugins use this list as a side-channel for per-project
    discovery (e.g. ``owner`` derivation when the project lacks an
    explicit GitHub Repository link).
    """
    query: typing.LiteralString = (
        'MATCH (p:Project {{id: {project_id}}})-[:TYPE]->(pt:ProjectType) '
        'RETURN pt.slug AS slug'
    )
    try:
        records = await db.execute(query, {'project_id': project_id}, ['slug'])
    except Exception:  # noqa: BLE001
        LOGGER.debug('Project type lookup failed', exc_info=True)
        return []
    slugs: list[str] = []
    for row in records:
        raw = graph.parse_agtype(row.get('slug'))
        if isinstance(raw, str) and raw:
            slugs.append(raw)
    return slugs


def extract_role_slug(
    operations: list[json_patch.PatchOperation],
) -> str:
    """Extract ``role_slug`` from a JSON Patch membership update.

    The body must be a single ``replace`` (or ``add``) operation
    targeting ``/role_slug`` with a non-empty string value.

    Parameters:
        operations: The parsed JSON Patch operations.

    Returns:
        The new role slug.

    Raises:
        fastapi.HTTPException: HTTP 400 if the patch is malformed.

    """
    if len(operations) != 1:
        raise fastapi.HTTPException(
            status_code=400,
            detail=('Membership patch must contain exactly one operation'),
        )
    op = operations[0]
    if op.op not in ('replace', 'add'):
        raise fastapi.HTTPException(
            status_code=400,
            detail="Membership patch op must be 'replace' or 'add'",
        )
    if op.path != '/role_slug':
        raise fastapi.HTTPException(
            status_code=400,
            detail="Membership patch path must be '/role_slug'",
        )
    if not isinstance(op.value, str) or not op.value:
        raise fastapi.HTTPException(
            status_code=400,
            detail='role_slug value must be a non-empty string',
        )
    return op.value
