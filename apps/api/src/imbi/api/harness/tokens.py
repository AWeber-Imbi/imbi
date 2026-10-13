"""Runner, executor, and agent credentials (ADR 0022).

imbi-api mints every credential of a runner:

- The **runner credential** and the **executor credential** come from
  registration. Each is a random secret with a prefix (``ihr_``,
  ``ihe_``). Imbi stores only its SHA-256 hash. It is not a JWT, so a
  route outside the harness refuses it as an invalid token.
- The **agent token** comes from a claim. It is a JWT for the service
  account of the task's agent, with the audience :data:`AUDIENCE` and
  the chain, attempt, runner, and organization of the claim. The shared
  token check (:func:`imbi.common.auth.core.verify_token`) names no
  audience, so PyJWT refuses a token that has one: every route outside
  the harness refuses an agent token.

A claim is valid only while its chain is pinned to the runner in that
attempt: :mod:`imbi.api.harness.auth` checks this on every call. So
the lease sweep makes every token of a lost runner invalid at once,
and the long :data:`AGENT_TOKEN_TTL_SECONDS` is only a ceiling.
"""

import dataclasses
import datetime
import hashlib
import secrets
import typing
import uuid

import fastapi
import jwt

from imbi.common.auth import permissions

#: The audience of an agent token.
AUDIENCE = 'imbi-harness'
#: The ``type`` claim of an agent token.
AGENT_TOKEN_TYPE = 'harness_agent'
#: The ceiling of an agent token. A task can wait days on a person.
AGENT_TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60

RUNNER_PREFIX = 'ihr_'
EXECUTOR_PREFIX = 'ihe_'

_CLAIMS = (
    'sub',
    'jti',
    'type',
    'exp',
    'aud',
    'chain',
    'attempt',
    'runner',
    'org',
)


@dataclasses.dataclass(frozen=True)
class AgentGrant:
    """What an agent token allows: the tasks of one chain attempt."""

    chain_id: uuid.UUID
    attempt: int
    runner_id: uuid.UUID
    organization_id: str


def new_secret(prefix: str) -> tuple[str, str]:
    """Return a new credential with ``prefix`` and its hash."""
    token = prefix + secrets.token_urlsafe(32)
    return token, hash_secret(token)


def hash_secret(token: str) -> str:
    """Return the stored hash of a runner or executor credential."""
    return hashlib.sha256(token.encode()).hexdigest()


def mint_agent_token(
    service_account: str, grant: AgentGrant
) -> tuple[str, datetime.datetime]:
    """Return an agent token for ``service_account`` and its expiry."""
    settings = permissions.auth_settings()
    now = datetime.datetime.now(datetime.UTC)
    expires = now + datetime.timedelta(seconds=AGENT_TOKEN_TTL_SECONDS)
    token = jwt.encode(
        {
            'sub': service_account,
            'jti': secrets.token_urlsafe(16),
            'type': AGENT_TOKEN_TYPE,
            'aud': AUDIENCE,
            'iat': now,
            'exp': expires,
            'chain': str(grant.chain_id),
            'attempt': grant.attempt,
            'runner': str(grant.runner_id),
            'org': grant.organization_id,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return token, expires


def is_agent_token(token: str) -> bool:
    """Return whether ``token`` says that it is an agent token.

    The signature is not checked here; :func:`verify_agent_token` does.
    """
    try:
        claims = jwt.decode(token, options={'verify_signature': False})
    except jwt.InvalidTokenError:
        return False
    return claims.get('aud') == AUDIENCE


def _unauthorized(message: str) -> fastapi.HTTPException:
    return fastapi.HTTPException(
        status_code=401,
        detail={'error': 'invalid_agent_token', 'message': message},
    )


def verify_agent_token(token: str) -> tuple[str, AgentGrant]:
    """Return the service account slug and the grant of an agent token.

    Raises:
        401: ``invalid_agent_token``: the token is not a valid agent
            token.

    """
    settings = permissions.auth_settings()
    try:
        claims: dict[str, typing.Any] = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=AUDIENCE,
            options={'require': list(_CLAIMS)},
        )
        if claims['type'] != AGENT_TOKEN_TYPE:
            raise _unauthorized('Not an agent token')
        return str(claims['sub']), AgentGrant(
            chain_id=uuid.UUID(str(claims['chain'])),
            attempt=int(claims['attempt']),
            runner_id=uuid.UUID(str(claims['runner'])),
            organization_id=str(claims['org']),
        )
    except (jwt.InvalidTokenError, KeyError, ValueError) as err:
        raise _unauthorized('Invalid agent token') from err
