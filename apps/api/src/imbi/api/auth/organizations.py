"""Membership of the organization in the request path.

Most permissions are not scoped to an organization. A router mounted at
``/organizations/{org_slug}/...`` that holds data for one organization
uses :func:`member_org_id` as a router dependency, so that a caller
can only use the routes of an organization that they are a member of
(``MEMBER_OF``). A caller that is not a member gets
``403 organization_forbidden``, as in :mod:`imbi.api.auth.autonomous`.
There is no admin bypass.

A member's permissions on these routes are those of their role in that
organization only (issue #455): :func:`check_member` narrows
``AuthContext.permissions`` to them. FastAPI gives every dependency of a
request the same ``AuthContext``, and a router dependency runs before
the route's own, so each ``require_permission`` check sees the narrowed
set.
"""

import logging
import typing

import fastapi

from imbi.api.auth import autonomous, permissions
from imbi.common import graph
from imbi.common.auth import permissions as common_permissions

LOGGER = logging.getLogger(__name__)

#: The org id, and whether the user with ``email`` is a member of it.
_ORG_MEMBER_QUERY: typing.LiteralString = """
MATCH (o:Organization {{slug: {org_slug}}})
OPTIONAL MATCH (u:User {{email: {email}}})-[:MEMBER_OF]->(o)
RETURN o.id AS id, u IS NOT NULL AS member
"""


def organization_id(value: object, slug: str) -> str:
    """The id of an organization node, parsed.

    An organization made before nodes had an ``id`` has none until the
    startup backfill (:mod:`imbi.api.graph_ids`) gives it one. Its
    data must never be keyed as ``"None"``, so this fails closed.

    Raises:
        500: The organization has no id.

    """
    if value is None or value == '':
        LOGGER.error(
            'Organization %r has no id; the graph id backfill has not run',
            slug,
        )
        raise fastapi.HTTPException(
            status_code=500, detail=f'Organization {slug!r} has no id'
        )
    return str(value)


async def org_permissions(
    db: graph.Graph, auth: permissions.AuthContext, org_slug: str
) -> set[str]:
    """The caller's permissions in ``org_slug``: those of their role in
    that organization, still limited by the scopes of an API key."""
    granted: set[str] = set()
    if auth.user is not None:
        granted = await common_permissions.load_principal_permissions(
            db, 'User', 'email', auth.user.email, org_slug=org_slug
        )
    elif auth.service_account is not None:
        granted = await common_permissions.load_principal_permissions(
            db,
            'ServiceAccount',
            'slug',
            auth.service_account.slug,
            org_slug=org_slug,
        )
    return auth.permissions & granted


async def member_org_id(
    org_slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
) -> str:
    """Return the id of the organization when the caller is a member.

    Raises:
        403: The caller is not a member of the organization.
        404: No such organization.

    """
    return await check_member(org_slug, db, auth)


async def check_member(
    org_slug: str, db: graph.Graph, auth: permissions.AuthContext
) -> str:
    """Return the id of the organization when ``auth`` is a member.

    Raises:
        403: The caller is not a member of the organization.
        404: No such organization.

    """
    records = await db.execute(
        _ORG_MEMBER_QUERY,
        {
            'org_slug': org_slug,
            'email': auth.user.email if auth.user else None,
        },
        ['id', 'member'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Organization with slug {org_slug!r} not found',
        )
    if auth.user is None:
        await autonomous.require_organization_membership(
            db, auth, org_slug=org_slug
        )
    elif not graph.parse_agtype(records[0]['member']):
        raise autonomous.forbidden(
            'organization_forbidden',
            (
                f'Principal {auth.principal_name!r} is not a member of '
                f'organization {org_slug!r}.'
            ),
            org_slug=org_slug,
        )
    auth.permissions = await org_permissions(db, auth, org_slug)
    return organization_id(graph.parse_agtype(records[0]['id']), org_slug)


#: The id of the organization in the path, for a caller that is a member.
MemberOrgId = typing.Annotated[str, fastapi.Depends(member_org_id)]
