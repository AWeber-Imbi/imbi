"""Shared helpers for endpoint handlers."""

import logging
import typing

import fastapi
from imbi_common import graph

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
