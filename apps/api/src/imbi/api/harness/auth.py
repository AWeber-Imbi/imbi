"""Authentication of runners and agent tokens (ADR 0022).

The harness routes accept credentials that no other route accepts:

- A runner credential, for the runner routes (:func:`current_runner`).
- An agent token, for the ADR 0020 harness routes and the
  ``/harness/tasks`` routes (:func:`harness_caller`). It is valid only
  while its chain is pinned to its runner in its attempt.

The ADR 0020 harness routes also keep accepting the client credential
of the agent's service account, for a task whose chain no runner holds.
"""

import dataclasses
import typing
import uuid

import fastapi
from fastapi import security

from imbi.api import harness
from imbi.api.auth import autonomous, organizations, permissions
from imbi.api.harness import tokens
from imbi.common import graph, models
from imbi.common.auth import permissions as common_permissions

_bearer = common_permissions.oauth2_scheme

#: The bearer credentials of a request, if any.
Credentials = typing.Annotated[
    security.HTTPAuthorizationCredentials | None, fastapi.Depends(_bearer)
]


@dataclasses.dataclass(frozen=True)
class HarnessCaller:
    """The caller of a harness route, and its grant for an agent token."""

    auth: permissions.AuthContext
    grant: tokens.AgentGrant | None = None


def _unauthorized(error: str, message: str) -> fastapi.HTTPException:
    return fastapi.HTTPException(
        status_code=401,
        detail={'error': error, 'message': message},
        headers={'WWW-Authenticate': 'Bearer'},
    )


async def check_grant(
    store: harness.HarnessStore, grant: tokens.AgentGrant
) -> None:
    """Refuse a grant whose chain attempt is no longer current.

    Raises:
        401: ``stale_attempt``: the chain is not pinned to the runner in
            this attempt, or the runner is not busy.

    """
    chain = await store.chain(grant.chain_id)
    if (
        chain is None
        or chain['state'] != 'running'
        or chain['runner_id'] != grant.runner_id
        or chain['attempt'] != grant.attempt
        or chain['organization_id'] != grant.organization_id
        or chain['runner_state'] != 'busy'
    ):
        raise _unauthorized(
            'stale_attempt',
            'The agent token is for a chain attempt that is not current',
        )


async def harness_caller(
    db: graph.Pool, store: harness.Store, credentials: Credentials
) -> HarnessCaller:
    """Authenticate an agent token, or any credential that
    :func:`permissions.get_current_user` accepts.

    An agent token authenticates as the service account of its agent,
    with no permissions.

    Raises:
        401: The credential is not valid, or the agent token is for a
            chain attempt that is not current.

    """
    if credentials is None or not tokens.is_agent_token(
        credentials.credentials
    ):
        return HarnessCaller(
            await permissions.get_current_user(db, credentials)
        )
    slug, grant = tokens.verify_agent_token(credentials.credentials)
    await check_grant(store, grant)
    accounts = await db.match(models.ServiceAccount, {'slug': slug})
    if not accounts or not accounts[0].is_active:
        raise _unauthorized(
            'invalid_agent_token', 'The service account is not active'
        )
    return HarnessCaller(
        permissions.AuthContext(
            service_account=accounts[0], auth_method='client_credentials'
        ),
        grant,
    )


Caller = typing.Annotated[HarnessCaller, fastapi.Depends(harness_caller)]


async def harness_member_org_id(
    org_slug: str, db: graph.Pool, caller: Caller
) -> str:
    """:func:`organizations.member_org_id` for the harness routes.

    An agent token also works only in the organization of its chain.

    Raises:
        403: The caller is not a member of the organization, or the
            agent token is for another organization.
        404: No such organization.

    """
    org_id = await organizations.check_member(org_slug, db, caller.auth)
    if caller.grant is not None and caller.grant.organization_id != org_id:
        raise autonomous.forbidden(
            'organization_forbidden',
            f'The agent token is not for organization {org_slug!r}.',
            org_slug=org_slug,
        )
    return org_id


HarnessOrgId = typing.Annotated[str, fastapi.Depends(harness_member_org_id)]


async def agent_caller(caller: Caller) -> HarnessCaller:
    """Return the caller when it has an agent token.

    Raises:
        401: ``agent_token_required``.

    """
    if caller.grant is None:
        raise _unauthorized(
            'agent_token_required', 'This route needs an agent token'
        )
    return caller


AgentCaller = typing.Annotated[HarnessCaller, fastapi.Depends(agent_caller)]


async def current_runner(
    runner_id: uuid.UUID, store: harness.Store, credentials: Credentials
) -> dict[str, typing.Any]:
    """Return the runner in the path when the runner credential is its.

    Raises:
        401: ``invalid_runner_credential``: not the credential of a live
            runner with this id. The runner stops and registers again.

    """
    token = credentials.credentials if credentials else ''
    runner = None
    if token.startswith(tokens.RUNNER_PREFIX):
        runner = await store.runner_by_credential(runner_id, token)
    if runner is None:
        raise _unauthorized(
            'invalid_runner_credential',
            'Not the credential of a live runner with this id',
        )
    return runner


Runner = typing.Annotated[
    dict[str, typing.Any], fastapi.Depends(current_runner)
]
