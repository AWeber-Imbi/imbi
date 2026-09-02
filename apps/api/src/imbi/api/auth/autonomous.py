"""Authorization for principals that act with no human behind them.

A capability call normally runs on the acting *user's* credential: the
host loads their :class:`~imbi.api.identity.models.IdentityConnection`
for the Integration and threads the OAuth token into the plugin.  A
service account presenting a client-credentials or API-key token has no
such connection and no route to acquire one --
``IdentityConnection`` is keyed ``{integration_id, user_id}`` and is only
ever written by the interactive OAuth flow.  Answering it with the
``401 identity_required`` challenge is a category error: that header
exists to make a browser render a Connect button, and there is no
browser.

So a *userless* principal falls back to the Integration's own service
credential (a PAT, or a GitHub App installation token minted from
``app_id`` + ``private_key``).  That fallback is what this module bounds.
The authority envelope is deliberately three independent axes, none of
which subsumes another:

1. The capability's own permission (``project:deployment:write``, ...),
   enforced where it always was -- on the endpoint.
2. :data:`ACT_AS_SERVICE_PERMISSION`, an additive second grant.  Acting
   with an Integration's credential is a capability-independent
   decision, so the permission is too; it parallels
   ``scheduler:impersonate``, which is likewise scoped to the act rather
   than to the target.
3. Membership in the organization owning the project.  Service accounts
   already carry ``MEMBER_OF`` edges, and the deployment router enforces
   no organization scoping of its own -- the ``org_slug`` path segment
   is decorative -- so without this a service account holding
   ``project:deployment:write`` reaches every project in every
   organization.

Environments add a fourth (``Environment.allow_autonomous``), enforced
by the deployment endpoints alongside ``can_deploy`` / ``can_promote``
because only they know which environment is in scope.

Every refusal here is a ``403`` carrying a discriminated
``detail.error``, following the ``identity_required`` shape the UI
already consumes.  ``403`` rather than ``424``/``503`` because consuming
clients retry ``5xx`` on the assumption that it is transient, and none
of these states will change on retry -- an autonomous daemon needs to
branch on the cause, not spin.
"""

from __future__ import annotations

import logging
import typing

import fastapi

from imbi.common import graph
from imbi.common.auth import permissions

LOGGER = logging.getLogger(__name__)

#: Additive, cross-cutting permission a userless principal needs on top
#: of the capability's own before it may act with an Integration's
#: credential.  ``deployment`` is the only capability wired to it today;
#: ``configuration``, ``logs``, ``lifecycle``, and ``analysis`` can adopt
#: the same fallback unchanged, which is why the name says nothing about
#: deploying.
ACT_AS_SERVICE_PERMISSION = 'integration:act-as-service'

_SA_MEMBERSHIP_QUERY: typing.LiteralString = """
MATCH (s:ServiceAccount {{slug: {slug}}})
      -[:MEMBER_OF]->(:Organization {{slug: {org_slug}}})
RETURN s.slug AS slug
"""


def is_userless(auth: permissions.AuthContext) -> bool:
    """True when no human identity backs this principal.

    The question credential resolution asks: with no acting user there
    can be no ``IdentityConnection``, so a missing one is expected
    rather than an error.  Includes Imbi's own background workers --
    they too must fall back to the Integration's credential.
    """
    return auth.user is None


def is_autonomous(auth: permissions.AuthContext) -> bool:
    """True when this principal must satisfy the gates in this module.

    A userless principal that was *authenticated* -- a service account
    presenting a client-credentials or API-key token.  Imbi's own
    in-process workers are excluded: they hold no granted permissions
    and no organization membership, so checking either would deny work
    an operator authorized when they configured the sweep, not when they
    granted a role.  See ``imbi.api.auth.principals.system_auth``.
    """
    return is_userless(auth) and not auth.internal


def forbidden(
    error: str, message: str, **fields: typing.Any
) -> fastapi.HTTPException:
    """Build a ``403`` with a discriminated ``detail.error``.

    ``message`` is for a human reading a log or a UI toast; ``error``
    and ``fields`` are what a daemon branches on.
    """
    detail: dict[str, typing.Any] = {'error': error, 'message': message}
    detail.update(fields)
    return fastapi.HTTPException(status_code=403, detail=detail)


def require_act_as_service(
    auth: permissions.AuthContext, *, integration_id: str
) -> None:
    """Refuse a userless principal that was not granted the fallback.

    No admin bypass: ``AuthContext.is_admin`` is a property of a *user*
    and is always ``False`` here, so the grant has to be explicit.
    """
    if ACT_AS_SERVICE_PERMISSION in auth.permissions:
        return
    LOGGER.warning(
        'Refusing service-credential fallback for principal %s on '
        'integration %s: missing %s',
        auth.principal_name,
        integration_id,
        ACT_AS_SERVICE_PERMISSION,
    )
    raise forbidden(
        'service_credential_forbidden',
        (
            f'Principal {auth.principal_name!r} may not act with an '
            f"Integration's own credential: grant "
            f'{ACT_AS_SERVICE_PERMISSION!r}.'
        ),
        integration_id=integration_id,
    )


async def require_organization_membership(
    db: graph.Graph, auth: permissions.AuthContext, *, org_slug: str
) -> None:
    """Refuse a userless principal outside ``org_slug``.

    Converts "any project in any organization" into "projects in
    organizations this service account was deliberately added to".
    A principal that is neither a user nor a service account has no
    membership to check and is refused outright.
    """
    slug = auth.service_account.slug if auth.service_account else None
    if slug:
        rows = await db.execute(
            _SA_MEMBERSHIP_QUERY,
            {'slug': slug, 'org_slug': org_slug},
            ['slug'],
        )
        if rows:
            return
    LOGGER.warning(
        'Refusing principal %s on organization %s: not a member',
        auth.principal_name,
        org_slug,
    )
    raise forbidden(
        'organization_forbidden',
        (
            f'Principal {auth.principal_name!r} is not a member of '
            f'organization {org_slug!r}.'
        ),
        org_slug=org_slug,
    )


def require_environment_autonomous(
    auth: permissions.AuthContext,
    *,
    environment: str,
    allow_autonomous: bool,
) -> None:
    """Refuse a userless principal in an environment that has not opted in.

    Default-false on :class:`~imbi.common.models.Environment`, so
    shipping the fallback grants nothing until an operator opts an
    environment in.  A no-op for human callers, whose authority in an
    environment stays ``can_deploy`` / ``can_promote`` alone.
    """
    if not is_autonomous(auth) or allow_autonomous:
        return
    raise forbidden(
        'environment_not_autonomous',
        (
            f'Environment {environment!r} has allow_autonomous=false; '
            'autonomous principals may not deploy or promote into it.'
        ),
        environment=environment,
    )


def require_no_ci_override(
    auth: permissions.AuthContext, *, acknowledged: bool, committish: str
) -> None:
    """Refuse a userless principal that acknowledged a CI failure itself.

    ``acknowledge_ci_failure`` means "an operator who has seen the
    failure and decided to ship anyway".  A daemon setting it asserts
    something nobody did.  Refused whether CI is red or green, because
    the claim is false either way.

    This costs little: only ``'fail'`` gates at all, so a rollback to a
    genuinely good ref is unaffected.  The only case denied is a daemon
    shipping a commit whose CI is failing, which is precisely where a
    human belongs.
    """
    if not acknowledged or not is_autonomous(auth):
        return
    raise forbidden(
        'ci_override_forbidden',
        (
            'acknowledge_ci_failure asserts that an operator reviewed the '
            'failing checks; an autonomous principal cannot make that '
            'claim.'
        ),
        committish=committish,
    )
