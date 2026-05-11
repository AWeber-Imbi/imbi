"""Auto-assignment of the default role on user login.

When a user successfully authenticates but has no ``MEMBER_OF`` edge
to any organization yet, they would otherwise receive an empty
permission set and be 403'd everywhere.

``ensure_user_membership`` resolves the role flagged with
``is_default: true`` (seeded by :mod:`imbi_api.auth.seed`) and creates
a ``MEMBER_OF {role: <slug>}`` edge to the target organization. The
target is the sole ``Organization`` if there is exactly one; otherwise
it falls back to the seeded ``slug='default'`` organization. If the
target cannot be resolved unambiguously, the helper logs a warning
and returns ``None`` so login still succeeds.
"""

import logging
import typing

from imbi_common import graph

LOGGER = logging.getLogger(__name__)


_DEFAULT_ROLE_QUERY: typing.LiteralString = (
    'MATCH (r:Role {{is_default: true}}) RETURN r.slug AS slug LIMIT 1'
)

_TARGET_ORG_QUERY: typing.LiteralString = (
    'MATCH (o:Organization) RETURN collect(o.slug) AS slugs'
)

_USER_HAS_MEMBERSHIP_QUERY: typing.LiteralString = (
    'MATCH (u:User {{email: {email}}}) '
    'OPTIONAL MATCH (u)-[m:MEMBER_OF]->() '
    'RETURN count(m) AS edges'
)

# MERGE rather than CREATE so two concurrent logins for the same
# previously-unassigned user cannot leave behind duplicate MEMBER_OF
# edges. ``role_slug`` is part of the merge pattern, so this is
# idempotent only for the same role value — fine here because the
# caller invokes this helper only when the user has zero memberships
# of any kind.
_CREATE_MEMBERSHIP_QUERY: typing.LiteralString = (
    'MATCH (u:User {{email: {email}}}), '
    '(o:Organization {{slug: {org_slug}}}) '
    'MERGE (u)-[:MEMBER_OF {{role: {role_slug}}}]->(o) '
    'RETURN u.email AS email'
)


async def ensure_user_membership(
    db: graph.Graph,
    email: str,
) -> str | None:
    """Assign the default role to ``email`` if the user has no membership.

    Args:
        db: Graph database connection.
        email: User email used to look up the ``User`` node.

    Returns:
        The role slug that was assigned, or ``None`` if the user
        already had a membership, or if the default role / target
        organization could not be resolved.
    """
    edges = await _count_memberships(db, email)
    if edges is None or edges > 0:
        return None

    role_slug = await _resolve_default_role(db)
    if role_slug is None:
        LOGGER.warning(
            'No Role with is_default=true; cannot auto-assign for %s',
            email,
        )
        return None

    org_slug = await _resolve_target_org(db)
    if org_slug is None:
        LOGGER.warning(
            'No unambiguous target Organization for default role '
            'assignment of %s',
            email,
        )
        return None

    created = await _create_membership(db, email, org_slug, role_slug)
    if created:
        LOGGER.info(
            'Assigned default role %r in organization %r to %s',
            role_slug,
            org_slug,
            email,
        )
        return role_slug
    return None


async def _count_memberships(
    db: graph.Graph,
    email: str,
) -> int | None:
    records = await db.execute(
        _USER_HAS_MEMBERSHIP_QUERY,
        {'email': email},
        columns=['edges'],
    )
    if not records:
        return None
    raw = graph.parse_agtype(records[0].get('edges'))
    if raw is None:
        return None
    return int(raw)


async def _resolve_default_role(db: graph.Graph) -> str | None:
    records = await db.execute(_DEFAULT_ROLE_QUERY, columns=['slug'])
    if not records:
        return None
    raw = graph.parse_agtype(records[0].get('slug'))
    return raw if isinstance(raw, str) else None


async def _resolve_target_org(db: graph.Graph) -> str | None:
    records = await db.execute(_TARGET_ORG_QUERY, columns=['slugs'])
    if not records:
        return None
    raw: typing.Any = graph.parse_agtype(records[0].get('slugs'))
    if not isinstance(raw, list):
        return None
    slugs: list[str] = [
        item
        for item in typing.cast(list[str | typing.Any], raw)
        if isinstance(item, str)
    ]
    if len(slugs) == 1:
        return slugs[0]
    if 'default' in slugs:
        return 'default'
    return None


async def _create_membership(
    db: graph.Graph,
    email: str,
    org_slug: str,
    role_slug: str,
) -> bool:
    records = await db.execute(
        _CREATE_MEMBERSHIP_QUERY,
        {'email': email, 'org_slug': org_slug, 'role_slug': role_slug},
        columns=['email'],
    )
    return bool(records)
