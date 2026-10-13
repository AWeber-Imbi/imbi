"""The ``github_app`` secret provider (ADR 0022, plan section 9.8).

The provider issues a GitHub App installation access token for each
resolution. The token is limited to the repositories of the task and to
the permissions of the purpose, and it lasts one hour at most. Release
revokes it with ``DELETE /installation/token``.

The App private key is not in Imbi: the binding names the ``secret://``
reference of another binding (for example an ``aws_secrets_manager``
binding), and imbi-api reads the key through the broker for each call.

The JWT and the token exchange come from the GitHub plugin
(:mod:`imbi.plugins.github._app_auth`). Its process-wide token cache is
not used: each resolution gets its own token, so that release can
revoke it.

The token is the lease id, because GitHub revokes a token only with the
token itself. The broker keeps lease ids encrypted.
"""

import collections.abc
import contextlib
import datetime
import logging
import re
import typing
import uuid

import httpx
import jwt
import pydantic

from imbi.api.secret_broker import broker, providers
from imbi.plugins.github import _app_auth, _hosts, _repos
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

#: GitHub status codes, by safe reason code.
_HTTP_REASONS = {
    401: 'app_authentication_failed',
    403: 'access_denied',
    404: 'installation_not_found',
    422: 'permission_or_repository_not_granted',
}


class _Config(pydantic.BaseModel):
    """One provider for each GitHub host: github.com, a GHEC tenant
    (``<tenant>.ghe.com``), or a GHES appliance."""

    model_config = pydantic.ConfigDict(extra='forbid')

    host: str = 'github.com'

    @pydantic.field_validator('host')
    @classmethod
    def _host(cls, value: str) -> str:
        return _hosts.normalize_host(value, 'host').lower()


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


def _api_base(config: dict[str, typing.Any]) -> str:
    return _hosts.host_to_api_base(config.get('host', 'github.com'))


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
    organization_id: str, reference: str, task_id: uuid.UUID | None
) -> str:
    """Read the App private key through the broker."""
    from imbi.api import secret_broker

    material = await secret_broker.get_broker().provider_key(
        organization_id, reference, task_id
    )
    return material.value.decode()


async def project_repositories(host: str, project_id: str | None) -> list[str]:
    """Return the ``owner/name`` repositories of a project on ``host``.

    Only a project link counts (the ``github-repository`` link first).
    The project-type slug fallback of the GitHub plugin is a naming
    convention, not a fact, so it does not give access.
    """
    if project_id is None:
        return []
    from imbi.api import lifespans
    from imbi.api.endpoints import _helpers

    db = lifespans._graph  # pyright: ignore[reportPrivateUsage]
    if db is None:
        raise providers.BrokerError(
            'secret_provider_unavailable', 'graph_unavailable'
        )
    found = _repos.derive_owner_repo_from_links(
        await _helpers.lookup_project_links(db, project_id), host
    )
    return [] if found is None else [f'{found[0]}/{found[1]}']


def _expiry(value: object) -> datetime.datetime:
    if isinstance(value, str):
        try:
            return datetime.datetime.fromisoformat(value)
        except ValueError:
            pass
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

    @contextlib.asynccontextmanager
    async def _app_client(
        self,
        config: dict[str, typing.Any],
        locator: dict[str, typing.Any],
        organization_id: str,
        task_id: uuid.UUID | None,
    ) -> collections.abc.AsyncGenerator[httpx.AsyncClient]:
        """A client that authenticates as the App (a JWT)."""
        key = await private_key(
            organization_id, locator['private_key'], task_id
        )
        app_jwt = _app_auth._app_jwt(  # pyright: ignore[reportPrivateUsage]
            locator['app_id'], key
        )
        async with httpx.AsyncClient(
            base_url=_api_base(config),
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
    ) -> tuple[str, datetime.datetime]:
        token, expires_at = await _app_auth._mint(  # pyright: ignore[reportPrivateUsage]
            client,
            installation_id,
            _app_auth.freeze_scope(permissions),
            repositories,
        )
        return token, _expiry(expires_at)

    async def health(
        self, config: dict[str, typing.Any], organization_id: str
    ) -> providers.Health:
        """Check that the GitHub API answers. No credentials are used."""
        try:
            async with httpx.AsyncClient(
                base_url=_api_base(config),
                headers=_accept_header(),
                timeout=_TIMEOUT_SECONDS,
            ) as client:
                response = await client.get('/meta')
        except httpx.TransportError:
            return providers.Health('unhealthy', 'unreachable')
        if response.status_code != 200:
            return providers.Health('unhealthy', 'provider_error')
        return providers.Health(
            'healthy', identity={'host': config.get('host', 'github.com')}
        )

    async def validate_binding(
        self,
        config: dict[str, typing.Any],
        locator: dict[str, typing.Any],
        organization_id: str,
    ) -> dict[str, typing.Any]:
        """Mint a token and return its metadata only, never the token.

        The token has only ``metadata: read`` and is revoked before this
        returns.
        """
        with _github_errors('secret_materialization_failed'):
            async with self._app_client(
                config, locator, organization_id, None
            ) as client:
                installation = await self._installation(
                    client, locator['installation_id']
                )
                token, expires_at = await self._mint(
                    client, locator['installation_id'], _TEST_PERMISSIONS
                )
            try:
                async with httpx.AsyncClient(
                    base_url=_api_base(config),
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
                await self.revoke(config, token)
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

        Raises:
            BrokerError: The purpose is unknown, the task has no
                repository, a repository is outside the installation,
                or GitHub refused the request.

        """
        if field is not None:
            raise providers.BrokerError('secret_field_not_allowed')
        permissions = PURPOSE_PERMISSIONS.get(context.purpose)
        if permissions is None:
            raise providers.BrokerError(
                'secret_access_denied', 'purpose_not_supported'
            )
        if context.purpose == 'marketplace_fetch':
            repositories = list(locator.get('repositories', []))
        else:
            repositories = await project_repositories(
                config.get('host', 'github.com'), context.project_id
            )
        # An empty list never reaches GitHub: no repositories would give
        # a token for every repository of the installation.
        if not repositories:
            raise providers.BrokerError(
                'secret_access_denied', 'no_repositories'
            )
        with _github_errors('secret_materialization_failed'):
            async with self._app_client(
                config, locator, context.organization_id, context.task_id
            ) as client:
                installation = await self._installation(
                    client, locator['installation_id']
                )
                token, expires_at = await self._mint(
                    client,
                    locator['installation_id'],
                    permissions,
                    _names(installation, repositories),
                )
        return providers.Material(
            token.encode(),
            credential_expires_at=expires_at,
            lease_id=token,
            revocable=True,
        )

    async def revoke(
        self, config: dict[str, typing.Any], lease_id: str
    ) -> None:
        """Revoke a token. A 401 means it no longer works: success."""
        try:
            async with httpx.AsyncClient(
                base_url=_api_base(config),
                headers=_auth_headers(lease_id),
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
