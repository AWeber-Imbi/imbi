"""Membership of the organization in the request path.

Most permissions are not scoped to an organization. A router mounted at
``/organizations/{org_slug}/...`` that holds data for one organization
uses :func:`member_org_id` as a router dependency, so that a caller
can only use the routes of an organization that they are a member of
(``MEMBER_OF``). A caller that is not a member gets
``403 organization_forbidden``, as in :mod:`imbi.api.auth.autonomous`.
There is no admin bypass.
"""

import typing

import fastapi

from imbi.api.auth import autonomous, permissions
from imbi.common import graph

#: The org id, and whether the user with ``email`` is a member of it.
_ORG_MEMBER_QUERY: typing.LiteralString = """
MATCH (o:Organization {{slug: {org_slug}}})
OPTIONAL MATCH (u:User {{email: {email}}})-[:MEMBER_OF]->(o)
RETURN o.id AS id, u IS NOT NULL AS member
"""


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
    return str(graph.parse_agtype(records[0]['id']))


#: The id of the organization in the path, for a caller that is a member.
MemberOrgId = typing.Annotated[str, fastapi.Depends(member_org_id)]
