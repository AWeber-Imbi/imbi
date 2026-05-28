"""Shared helpers for endpoint handlers."""

import json
import logging
import typing

import fastapi
from imbi_common import graph
from imbi_common.plugins.base import PluginContext

from imbi_api import patch as json_patch

LOGGER = logging.getLogger(__name__)


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
        except (TypeError, ValueError):
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


async def heal_relocated_link(db: graph.Graph, ctx: PluginContext) -> None:
    """Persist a repository rename a plugin reported on ``ctx``.

    A deployment / lifecycle plugin sets ``ctx.repository_relocation``
    when the remote reports the repository has permanently moved (e.g. a
    GitHub ``301`` after a rename). Rewrite the project's stored link so
    later calls skip the redirect and the UI shows the current name.
    Best-effort: a write failure is logged and swallowed so self-healing
    never fails the user-facing request whose result we already have.
    """
    reloc = ctx.repository_relocation
    if reloc is None:
        return
    try:
        changed = await update_project_link(
            db, ctx.project_id, reloc.link_key, reloc.new_url
        )
    except Exception:  # noqa: BLE001
        LOGGER.warning(
            'Failed to self-heal relocated repository link for project %s',
            ctx.project_id,
            exc_info=True,
        )
        return
    if changed:
        LOGGER.info(
            'Self-healed %s link for project %s after repo rename %s -> %s',
            reloc.link_key,
            ctx.project_id,
            reloc.old_owner_repo,
            reloc.new_owner_repo,
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
