"""Workload identity: the source registry and core minting (WIF plan 4.1,
4.4).

The contracts are :mod:`imbi.common.plugins.identity`. Plugins declare
source classes in :attr:`PluginManifest.identity_sources
<imbi.common.plugins.base.PluginManifest.identity_sources>`. :func:`get`
creates one instance of each on first use. ``fake`` and
:class:`FakeExchanger` are for tests only.

:func:`vendor_token` is the one function that mints a vendor access
token. Every consumer calls it.
"""

import asyncio
import datetime
import typing
import uuid

import pydantic

from imbi.api.secret_broker import providers
from imbi.common import graph
from imbi.common.plugins.identity import (
    AccessToken,
    IdentityError,
    IdentityRequest,
    IdentitySource,
    InvalidConfiguration,
    TokenExchanger,
    validate_model,
)

if typing.TYPE_CHECKING:
    from imbi.api.secret_broker import store


# --- fakes ---------------------------------------------------------------


class FakeIdentitySource(IdentitySource):
    """A source for tests. It records each request and returns a new
    opaque JWT for each call."""

    type = 'fake'
    label = 'Fake (tests only)'

    def __init__(self) -> None:
        self.requests: list[IdentityRequest] = []
        self.fail: str | None = None

    def validate_config(
        self, config: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        if config:
            raise InvalidConfiguration(
                'The fake identity source takes no configuration'
            )
        return {}

    async def identity_token(
        self, config: dict[str, typing.Any], request: IdentityRequest
    ) -> str:
        if self.fail is not None:
            raise IdentityError(self.fail)
        self.requests.append(request)
        return f'fake-jwt-{uuid.uuid4()}'


class _FakeTarget(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='forbid')

    service_account_id: str = pydantic.Field(min_length=1)


class FakeExchanger(TokenExchanger):
    """An exchanger for tests. It refuses a JWT that it saw before."""

    vendor = 'fake'
    audience = 'https://fake.example.com'
    jwt_seconds = 300

    def __init__(self) -> None:
        self.seen: list[str] = []

    def validate_target(
        self, target: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        return validate_model(_FakeTarget, target)

    async def exchange(
        self, target: dict[str, typing.Any], identity_token: str
    ) -> AccessToken:
        if identity_token in self.seen:
            raise IdentityError('assertion_reused')
        self.seen.append(identity_token)
        return AccessToken(
            f'fake-token-{uuid.uuid4()}',
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1),
        )


# --- registry ------------------------------------------------------------

#: The sources, by type. One instance each.
SOURCES: dict[str, IdentitySource] = {'fake': FakeIdentitySource()}
#: The sources that :func:`_load` added, by type.
_LOADED: dict[str, IdentitySource] = {}
#: The ``(plugin slug, type)`` problems already logged.
_REPORTED: set[tuple[str, str]] = set()


def _load() -> None:
    providers.reconcile(
        'identity_sources',
        'identity source',
        SOURCES,
        _LOADED,
        _REPORTED,
        lambda cls: cls(),
    )


def all_sources() -> list[IdentitySource]:
    _load()
    return list(SOURCES.values())


def get(source_type: str) -> IdentitySource:
    """Return the source of a type.

    Raises:
        IdentityError: ``unknown_identity_source``.

    """
    _load()
    source = SOURCES.get(source_type)
    if source is None:
        raise IdentityError('unknown_identity_source')
    return source


# --- minting -------------------------------------------------------------

_AGENT_QUERY: typing.LiteralString = """
MATCH (a:Agent {{id: {id}}})-[:BELONGS_TO]->(:Organization {{id: {org}}})
RETURN a.id AS id
"""


async def vendor_token(
    db: graph.Graph,
    secrets: store.SecretStore,
    organization_id: str,
    exchanger: TokenExchanger,
    target: dict[str, typing.Any],
    *,
    agent_id: str,
) -> AccessToken:
    """Mint a vendor access token for one agent.

    The caller takes ``target`` from the record of the agent (its own
    binding, with a grant that names the agent), never from a request.
    Each call gets a new JWT, so the vendor never sees a ``jti`` twice.
    There is no retry here: a retry is a new call, with a new JWT.

    Raises:
        IdentityError: ``agent_not_in_organization``,
            ``workload_identity_not_configured``,
            ``unknown_identity_source``, ``invalid_target``, or the
            reason of the source or the exchanger.

    """
    try:
        target = exchanger.validate_target(target)
    except InvalidConfiguration:
        raise IdentityError('invalid_target') from None
    found, setting = await asyncio.gather(
        db.execute(
            _AGENT_QUERY, {'id': agent_id, 'org': organization_id}, ['id']
        ),
        secrets.identity_source(organization_id),
    )
    if not found:
        raise IdentityError('agent_not_in_organization')
    if setting is None:
        raise IdentityError('workload_identity_not_configured')
    source = get(setting['type'])
    request = IdentityRequest(
        organization_id=organization_id,
        audience=exchanger.audience,
        tags={'imbi_org': organization_id, 'imbi_agent': agent_id},
        duration_seconds=exchanger.jwt_seconds,
    )
    token = await source.identity_token(setting['config'], request)
    return await exchanger.exchange(target, token)
