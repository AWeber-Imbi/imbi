"""The ``github_app`` secret provider (ADR 0022, plan section 9.8).

The provider issues a GitHub App installation access token for each
resolution. The token is limited to the repositories of the task and to
the permissions of the purpose, and it lasts one hour at most. Release
revokes it with ``DELETE /installation/token``.

The App private key is not in Imbi: the binding names the ``secret://``
reference of another binding (for example an ``aws_secrets_manager``
binding), and imbi-api reads the key through the broker for each call.
That key binding must be marked as a provider key for the same host and
App id, and must list the requesting binding as a consumer
(:meth:`Broker.check_provider_key` and :meth:`Broker.provider_key`).

The GitHub host comes from an allowlist, never from free tenant input:
``github.com``, a GHEC tenant (``<tenant>.ghe.com``), or a GHES host that
the operator lists in ``IMBI_SECRETS_GITHUB_GHES_HOSTS``. A JWT signed
with an App key goes only to such a host.

The JWT and the token exchange come from the GitHub plugin
(:mod:`imbi.plugins.github._app_auth`). Its process-wide token cache is
not used: each resolution gets its own token, so that release can
revoke it.

The lease id holds the token and the host it came from, because GitHub
revokes a token only with the token itself, and only at that host. The
broker keeps lease ids encrypted.
"""

import collections.abc
import contextlib
import datetime
import ipaddress
import logging
import os
import re
import typing
import uuid

import httpx
import jwt
import orjson
import pydantic

from imbi.api.secret_broker import broker, providers
from imbi.common import graph
from imbi.plugins.github import _app_auth, _hosts
from imbi.plugins.github.deployment import (
    _accept_header,  # pyright: ignore[reportPrivateUsage]
    _auth_headers,  # pyright: ignore[reportPrivateUsage]
)

LOGGER = logging.getLogger(__name__)

#: The token permissions of each purpose. The App's own permissions are
#: the upper limit: GitHub refuses a request for more (422).
PURPOSE_PERMISSIONS: dict[str, dict[str, str]] = {
    'workspace_checkout': {'contents': 'read'},
    'marketplace_fetch': {'contents': 'read'},
    'github_write': {
        'contents': 'write',
        'pull_requests': 'write',
        'issues': 'write',
    },
}

#: The binding test asks for the smallest permission set.
_TEST_PERMISSIONS = {'metadata': 'read'}

_TIMEOUT_SECONDS = 10.0
#: When GitHub gives no expiry, assume less than its one hour.
_DEFAULT_TTL = datetime.timedelta(minutes=55)
_REPOSITORY = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')
_GHEC_TENANT = re.compile(r'[a-z0-9][a-z0-9-]*\.ghe\.com')
_REPOSITORY_ID = re.compile(r'[0-9]{1,20}')
#: The plugin of the Integrations that verify a project's repository.
GITHUB_PLUGIN = 'github'
#: The verified repository ids of a project, one row for each
#: ``EXISTS_IN`` edge to a GitHub Integration.
_VERIFIED_REPOSITORIES: typing.LiteralString = (
    'MATCH (:Project {{id: {project_id}}})-[ei:EXISTS_IN]->'
    '(i:Integration {{plugin: {plugin}}}) '
    'RETURN i.options AS options, '
    'ei.verified_identifier AS repository_id'
)
#: The operator's GHES hosts, comma separated. Never tenant input.
GHES_HOSTS_ENV = 'IMBI_SECRETS_GITHUB_GHES_HOSTS'

#: GitHub status codes, by safe reason code.
_HTTP_REASONS = {
    401: 'app_authentication_failed',
    403: 'access_denied',
    404: 'installation_not_found',
    422: 'permission_or_repository_not_granted',
}


def _internal_address(host: str) -> bool:
    """True for a private, loopback, link-local, or other non-public IP."""
    try:
        address = ipaddress.ip_address(host.strip('[]'))
    except ValueError:
        return False
    return not address.is_global


def ghes_hosts() -> frozenset[str]:
    """The GHES hosts of :data:`GHES_HOSTS_ENV`, without IP addresses
    that are not public."""
    hosts: set[str] = set()
    for raw in os.environ.get(GHES_HOSTS_ENV, '').split(','):
        if not raw.strip():
            continue
        try:
            host = _hosts.normalize_host(raw, GHES_HOSTS_ENV).lower()
        except ValueError:
            LOGGER.warning('%s: a value is not a host', GHES_HOSTS_ENV)
            continue
        if _internal_address(host):
            LOGGER.warning(
                '%s: %s is not a public address', GHES_HOSTS_ENV, host
            )
            continue
        hosts.add(host)
    return frozenset(hosts)


def allowed_host(host: str) -> bool:
    """True for github.com, a GHEC tenant, or an operator GHES host."""
    return (
        host == 'github.com'
        or _GHEC_TENANT.fullmatch(host) is not None
        or host in ghes_hosts()
    )


def check_host(value: str) -> str:
    """Return the normalized host, or raise ``ValueError``."""
    host = _hosts.normalize_host(value, 'host').lower()
    if not allowed_host(host):
        raise ValueError(
            'use github.com, a <tenant>.ghe.com host, or a GHES host in '
            + GHES_HOSTS_ENV
        )
    return host


class _Config(pydantic.BaseModel):
    """One provider for each GitHub host: github.com, a GHEC tenant
    (``<tenant>.ghe.com``), or a GHES appliance."""

    model_config = pydantic.ConfigDict(extra='forbid')

    host: str = 'github.com'

    @pydantic.field_validator('host')
    @classmethod
    def _host(cls, value: str) -> str:
        return check_host(value)


class _Locator(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='forbid')

    app_id: str = pydantic.Field(pattern=r'^[0-9]{1,20}$')
    installation_id: str = pydantic.Field(pattern=r'^[0-9]{1,20}$')
    #: The ``secret://`` reference of the App private key (PEM, or
    #: base64 PEM), in a binding that is not ``dynamic``.
    private_key: str
    #: ``owner/name`` repositories for ``marketplace_fetch``. Other
    #: purposes use the repositories of the task's project.
    repositories: list[str] = pydantic.Field(default_factory=list[str])

    @pydantic.field_validator('private_key')
    @classmethod
    def _reference(cls, value: str) -> str:
        try:
            return str(broker.parse_reference(value))
        except providers.BrokerError:
            raise ValueError('not a valid secret:// reference') from None

    @pydantic.field_validator('repositories')
    @classmethod
    def _repositories(cls, value: list[str]) -> list[str]:
        if not all(_REPOSITORY.fullmatch(name) for name in value):
            raise ValueError('use the owner/name form')
        return value


def _host(config: dict[str, typing.Any]) -> str:
    return str(config.get('host', 'github.com'))


def _api_base(host: str) -> str:
    """The API base of an allowed host. The allowlist is checked again
    at each call, because the operator list can change."""
    if not allowed_host(host):
        raise providers.BrokerError('secret_access_denied', 'host_not_allowed')
    return _hosts.host_to_api_base(host)


def _lease(host: str, token: str) -> str:
    return orjson.dumps({'host': host, 'token': token}).decode()


@contextlib.contextmanager
def _github_errors(code: str) -> collections.abc.Generator[None]:
    """Translate a GitHub or key failure into a :class:`BrokerError`.

    Only the status code and the exception type are read. A response
    body, a header, or a key never goes into the error or the log.
    """
    try:
        yield
    except providers.BrokerError:
        raise
    except httpx.HTTPStatusError as err:
        status = err.response.status_code
        LOGGER.warning('GitHub App call failed: HTTP %d', status)
        if status == 429 or status >= 500:
            raise providers.BrokerError(
                'secret_provider_unavailable', 'throttled'
            ) from None
        raise providers.BrokerError(
            code, _HTTP_REASONS.get(status, 'provider_error')
        ) from None
    except httpx.TransportError as err:
        LOGGER.warning('GitHub App call failed: %s', type(err).__name__)
        raise providers.BrokerError(
            'secret_provider_unavailable', 'unreachable'
        ) from None
    except (ValueError, TypeError, jwt.PyJWTError) as err:
        LOGGER.warning('GitHub App key not usable: %s', type(err).__name__)
        raise providers.BrokerError(code, 'invalid_private_key') from None


async def private_key(
    organization_id: str,
    locator: dict[str, typing.Any],
    *,
    host: str,
    consumer: uuid.UUID | None,
    task_id: uuid.UUID | None,
) -> str:
    """Read the App private key through the broker, for one consumer
    binding, host, and App id."""
    from imbi.api import secret_broker

    material = await secret_broker.get_broker().provider_key(
        organization_id,
        locator['private_key'],
        consumer=consumer,
        host=host,
        app_id=locator['app_id'],
        task_id=task_id,
    )
    return material.value.decode()


async def project_repository_ids(
    host: str, project_id: str | None
) -> list[int]:
    """Return the verified GitHub repository ids of a project on ``host``.

    Only the ``verified_identifier`` of an ``EXISTS_IN`` edge to a GitHub
    Integration for ``host`` counts. The GitHub plugin writes it from the
    GitHub API (the lifecycle plugin and the doctor repair). A project
    link, or an edge identifier that a user edits, gives no access.

    Raises:
        BrokerError: ``project_repository_unverified`` when the project
            has no verified repository on ``host``.

    """
    if project_id is None:
        return []
    from imbi.api import lifespans
    from imbi.api.plugins import parse_options

    db = lifespans._graph  # pyright: ignore[reportPrivateUsage]
    if db is None:
        raise providers.BrokerError(
            'secret_provider_unavailable', 'graph_unavailable'
        )
    records = await db.execute(
        _VERIFIED_REPOSITORIES,
        {'project_id': project_id, 'plugin': GITHUB_PLUGIN},
        ['options', 'repository_id'],
    )
    found: set[int] = set()
    for record in records:
        value = str(graph.parse_agtype(record.get('repository_id')) or '')
        if _REPOSITORY_ID.fullmatch(value) is None:
            continue
        try:
            integration_host = _hosts.flavor_host(
                parse_options(record.get('options')), 'github_app'
            )
        except ValueError:
            continue
        if integration_host.lower() == host:
            found.add(int(value))
    if not found:
        raise providers.BrokerError(
            'secret_access_denied', 'project_repository_unverified'
        )
    return sorted(found)


def _expiry(value: object) -> datetime.datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.datetime.fromisoformat(value)
        except ValueError:
            pass
        else:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=datetime.UTC)
            return parsed
    return datetime.datetime.now(datetime.UTC) + _DEFAULT_TTL


class GitHubApp(providers.Provider):
    """GitHub App installation access tokens, one for each resolution."""

    type = 'github_app'
    label = 'GitHub App'
    capabilities = frozenset[providers.Capability](
        {'dynamic_issuance', 'lease_revocation', 'health_check'}
    )

    def validate_config(
        self, config: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        return providers._validate(  # pyright: ignore[reportPrivateUsage]
            _Config, config
        )

    def validate_locator(
        self,
        locator: dict[str, typing.Any],
        credential_class: providers.CredentialClass,
    ) -> dict[str, typing.Any]:
        if credential_class != 'dynamic':
            raise providers.InvalidConfiguration(
                'A github_app binding is dynamic'
            )
        return providers._validate(  # pyright: ignore[reportPrivateUsage]
            _Locator, locator
        )

    async def check_locator(
        self,
        config: dict[str, typing.Any],
        locator: dict[str, typing.Any],
        organization_id: str,
    ) -> None:
        """The key binding must be a provider key for this host and App."""
        from imbi.api import secret_broker

        try:
            await secret_broker.get_broker().check_provider_key(
                organization_id,
                locator['private_key'],
                host=_host(config),
                app_id=locator['app_id'],
            )
        except providers.BrokerError as err:
            raise providers.InvalidConfiguration(
                'private_key must name a provider key binding for host '
                f'{_host(config)} and App {locator["app_id"]}',
                code=err.reason,
            ) from None

    @contextlib.asynccontextmanager
    async def _app_client(
        self,
        config: dict[str, typing.Any],
        locator: dict[str, typing.Any],
        organization_id: str,
        *,
        consumer: uuid.UUID | None,
        task_id: uuid.UUID | None,
    ) -> collections.abc.AsyncGenerator[httpx.AsyncClient]:
        """A client that authenticates as the App (a JWT)."""
        host = _host(config)
        base = _api_base(host)
        key = await private_key(
            organization_id,
            locator,
            host=host,
            consumer=consumer,
            task_id=task_id,
        )
        app_jwt = _app_auth._app_jwt(  # pyright: ignore[reportPrivateUsage]
            locator['app_id'], key
        )
        async with httpx.AsyncClient(
            base_url=base,
            headers=_auth_headers(app_jwt),
            timeout=_TIMEOUT_SECONDS,
        ) as client:
            yield client

    async def _installation(
        self, client: httpx.AsyncClient, installation_id: str
    ) -> dict[str, typing.Any]:
        response = await client.get(f'/app/installations/{installation_id}')
        response.raise_for_status()
        return typing.cast(dict[str, typing.Any], response.json())

    async def _mint(
        self,
        client: httpx.AsyncClient,
        installation_id: str,
        permissions: dict[str, str],
        repositories: list[str] | None = None,
        repository_ids: list[int] | None = None,
    ) -> tuple[str, datetime.datetime]:
        token, expires_at = await _app_auth._mint(  # pyright: ignore[reportPrivateUsage]
            client,
            installation_id,
            _app_auth.freeze_scope(permissions),
            repositories,
            repository_ids,
        )
        return token, _expiry(expires_at)

    async def health(
        self, config: dict[str, typing.Any], organization_id: str
    ) -> providers.Health:
        """Check that the GitHub API answers. No credentials are used."""
        try:
            async with httpx.AsyncClient(
                base_url=_api_base(_host(config)),
                headers=_accept_header(),
                timeout=_TIMEOUT_SECONDS,
            ) as client:
                response = await client.get('/meta')
        except providers.BrokerError as err:
            return providers.Health('unhealthy', err.reason)
        except httpx.TransportError:
            return providers.Health('unhealthy', 'unreachable')
        if response.status_code != 200:
            return providers.Health('unhealthy', 'provider_error')
        return providers.Health('healthy', identity={'host': _host(config)})

    async def validate_binding(
        self,
        config: dict[str, typing.Any],
        locator: dict[str, typing.Any],
        organization_id: str,
        binding_id: uuid.UUID | None = None,
    ) -> dict[str, typing.Any]:
        """Mint a token and return its metadata only, never the token.

        The token has only ``metadata: read`` and is revoked before this
        returns.
        """
        with _github_errors('secret_materialization_failed'):
            async with self._app_client(
                config,
                locator,
                organization_id,
                consumer=binding_id,
                task_id=None,
            ) as client:
                installation = await self._installation(
                    client, locator['installation_id']
                )
                token, expires_at = await self._mint(
                    client, locator['installation_id'], _TEST_PERMISSIONS
                )
            try:
                async with httpx.AsyncClient(
                    base_url=_api_base(_host(config)),
                    headers=_auth_headers(token),
                    timeout=_TIMEOUT_SECONDS,
                ) as client:
                    response = await client.get(
                        '/installation/repositories',
                        params={'per_page': 100},
                    )
                    response.raise_for_status()
                    listed = typing.cast(
                        dict[str, typing.Any], response.json()
                    )
            finally:
                await _revoke_token(_host(config), token)
        return {
            'app_slug': installation.get('app_slug'),
            'installation_id': locator['installation_id'],
            'account': _account(installation),
            'permissions': installation.get('permissions') or {},
            'repository_selection': installation.get('repository_selection'),
            'repository_count': listed.get('total_count'),
            'repositories': [
                repo['full_name'] for repo in listed.get('repositories', [])
            ],
            'token_expires_at': expires_at.isoformat(),
        }

    async def resolve(
        self,
        config: dict[str, typing.Any],
        locator: dict[str, typing.Any],
        field: str | None,
        context: providers.ResolveContext,
    ) -> providers.Material:
        """Mint a token for the task's repositories and the purpose.

        ``marketplace_fetch`` uses the ``repositories`` of the binding.
        The other purposes use the verified repository ids of the task's
        project (:func:`project_repository_ids`).

        Raises:
            BrokerError: The purpose is unknown, the task has no
                verified repository, a repository is outside the
                installation, or GitHub refused the request.

        """
        if field is not None:
            raise providers.BrokerError('secret_field_not_allowed')
        permissions = PURPOSE_PERMISSIONS.get(context.purpose)
        if permissions is None:
            raise providers.BrokerError(
                'secret_access_denied', 'purpose_not_supported'
            )
        repositories: list[str] = []
        repository_ids: list[int] | None = None
        if context.purpose == 'marketplace_fetch':
            repositories = list(locator.get('repositories', []))
        else:
            repository_ids = await project_repository_ids(
                _host(config), context.project_id
            )
        # An empty list never reaches GitHub: no repositories would give
        # a token for every repository of the installation.
        if not repositories and not repository_ids:
            raise providers.BrokerError(
                'secret_access_denied', 'no_repositories'
            )
        with _github_errors('secret_materialization_failed'):
            async with self._app_client(
                config,
                locator,
                context.organization_id,
                consumer=context.binding_id,
                task_id=context.task_id,
            ) as client:
                names = None
                if repositories:
                    installation = await self._installation(
                        client, locator['installation_id']
                    )
                    names = _names(installation, repositories)
                token, expires_at = await self._mint(
                    client,
                    locator['installation_id'],
                    permissions,
                    names,
                    repository_ids,
                )
        return providers.Material(
            token.encode(),
            credential_expires_at=expires_at,
            lease_id=_lease(_host(config), token),
            revocable=True,
        )

    async def revoke(
        self, config: dict[str, typing.Any], lease_id: str
    ) -> None:
        """Revoke a token at the host that issued it, from the lease.

        The provider configuration is not used: its host can change
        after the token was minted.
        """
        try:
            lease = typing.cast(dict[str, str], orjson.loads(lease_id))
            host, token = lease['host'], lease['token']
        except (orjson.JSONDecodeError, KeyError, TypeError):
            raise providers.BrokerError(
                'provider_revocation_failed', 'invalid_lease'
            ) from None
        await _revoke_token(host, token)


async def _revoke_token(host: str, token: str) -> None:
    """Revoke a token. A 401 means it no longer works: success."""
    base = _api_base(host)
    try:
        async with httpx.AsyncClient(
            base_url=base,
            headers=_auth_headers(token),
            timeout=_TIMEOUT_SECONDS,
        ) as client:
            response = await client.delete('/installation/token')
    except httpx.TransportError as err:
        LOGGER.warning('GitHub token revocation: %s', type(err).__name__)
        raise providers.BrokerError(
            'provider_revocation_failed', 'unreachable'
        ) from None
    if response.status_code not in (204, 401):
        LOGGER.warning(
            'GitHub token revocation: HTTP %d', response.status_code
        )
        raise providers.BrokerError(
            'provider_revocation_failed', 'provider_error'
        )


def _names(
    installation: dict[str, typing.Any], repositories: list[str]
) -> list[str]:
    """Return the repository names for the token request.

    GitHub takes names without the owner, inside the installation's
    account. A repository of another owner is refused here, because its
    name could match a different repository of that account.
    """
    account = _account(installation)
    names: list[str] = []
    for repository in repositories:
        owner, _, name = repository.partition('/')
        if not account or owner.lower() != account.lower():
            raise providers.BrokerError(
                'secret_access_denied', 'repository_outside_installation'
            )
        names.append(name)
    return names


def _account(installation: dict[str, typing.Any]) -> str:
    """The login of the account that the App is installed on."""
    account = typing.cast(
        dict[str, typing.Any], installation.get('account') or {}
    )
    return str(account.get('login') or '')
