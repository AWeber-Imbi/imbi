"""HTTP client for talking to the Imbi API."""

import http
import importlib.metadata
import logging
import typing
from collections import abc

import httpx

LOGGER = logging.getLogger(__name__)


def _default_user_agent() -> str:
    version = importlib.metadata.version('imbi-common')
    return f'imbi-common/{version}'


class Imbi(httpx.AsyncClient):
    """Async HTTP client for the Imbi API.

    Wraps `httpx.AsyncClient` with the `Authorization` and
    `User-Agent` headers wired up and adds high-level methods for the
    bookkeeping endpoints that integrating services call.

    Args:
        base_url: Root URL of the Imbi API (e.g. `http://imbi-api:8000`).
        token: Bearer token sent on every request.
        user_agent: Optional `User-Agent` header value. Defaults to
            `imbi-common/{version}` when not supplied.
        timeout: Optional request timeout in seconds. When omitted,
            `httpx`'s default applies.
    """

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        user_agent: str | None = None,
        timeout: float | None = None,
    ) -> None:
        headers = {
            'authorization': f'Bearer {token}',
            'user-agent': user_agent or _default_user_agent(),
        }
        kwargs: dict[str, typing.Any] = {
            'base_url': base_url,
            'headers': headers,
        }
        if timeout is not None:
            kwargs['timeout'] = timeout
        super().__init__(**kwargs)

    async def patch_project(
        self,
        org_slug: str,
        project_id: str,
        patch: abc.Iterable[abc.Mapping[str, object]],
    ) -> httpx.Response:
        """Send a JSON Patch to a project.

        Args:
            org_slug: Organization slug.
            project_id: Project identifier.
            patch: JSON Patch operations.

        Returns:
            The raw `httpx.Response`. Non-2xx responses are logged at
            warning level and returned to the caller.
        """
        url = f'/organizations/{org_slug}/projects/{project_id}'
        LOGGER.debug('Patching project %s', url)
        response = await self.patch(url, json=list(patch))
        if response.is_error:
            try:
                detail: object = response.json()
            except ValueError:
                detail = response.content
            LOGGER.warning('Failed to patch project %r: %r', url, detail)
        return response

    async def find_user_by_identity(
        self, plugin_slug: str, subject: str
    ) -> str | None:
        """Look up an Imbi user by external identity subject.

        Args:
            plugin_slug: Slug of the identity plugin (e.g. `github`).
            subject: The plugin-specific subject identifier.

        Returns:
            The user's email — the principal identity used by the
            Release `created_by` field — or `None` when no active
            identity connection matches or the lookup fails. Transport
            errors and malformed JSON responses are also coerced to
            `None` with a warning log.
        """
        try:
            response = await self.get(
                '/users/by-identity',
                params={'plugin_slug': plugin_slug, 'subject': subject},
            )
        except httpx.RequestError as exc:
            LOGGER.warning(
                'Failed to look up user for plugin=%r subject=%r: %s',
                plugin_slug,
                subject,
                exc,
            )
            return None
        if response.status_code == http.HTTPStatus.NOT_FOUND:
            return None
        if response.is_error:
            LOGGER.warning(
                'Failed to look up user for plugin=%r subject=%r: %s',
                plugin_slug,
                subject,
                response.text,
            )
            return None
        try:
            data = response.json()
        except ValueError:
            LOGGER.warning(
                'Failed to decode user lookup response for '
                'plugin=%r subject=%r',
                plugin_slug,
                subject,
            )
            return None
        email = data.get('email') if isinstance(data, dict) else None
        return str(email) if email else None

    async def create_release(
        self,
        org_slug: str,
        project_id: str,
        body: abc.Mapping[str, object],
    ) -> httpx.Response:
        """POST a new release to the project's releases collection.

        Args:
            org_slug: Organization slug.
            project_id: Project identifier.
            body: Release payload (`version`, `title`, optional
                `created_by`, etc.).

        Returns:
            The raw `httpx.Response`. `409 Conflict` is treated as
            an idempotent success and is not logged; other non-2xx
            responses are logged at warning level.
        """
        url = f'/organizations/{org_slug}/projects/{project_id}/releases/'
        LOGGER.debug('Creating release %s', url)
        response = await self.post(url, json=dict(body))
        if response.is_error and (
            response.status_code != http.HTTPStatus.CONFLICT
        ):
            LOGGER.warning(
                'Failed to create release %r: %s', url, response.text
            )
        return response

    async def record_deployment(
        self,
        org_slug: str,
        project_id: str,
        version: str,
        env_slug: str,
        body: abc.Mapping[str, object],
    ) -> httpx.Response:
        """POST a deployment event onto a release's environment edge.

        Args:
            org_slug: Organization slug.
            project_id: Project identifier.
            version: Release version string.
            env_slug: Target environment slug.
            body: Deployment event payload (`status`, optional
                `note`, etc.).

        Returns:
            The raw `httpx.Response`. `404 Not Found` is treated
            as a non-fatal "release missing" condition and is not
            logged; other non-2xx responses are logged at warning
            level.
        """
        url = (
            f'/organizations/{org_slug}/projects/{project_id}'
            f'/releases/{version}/environments/{env_slug}'
        )
        LOGGER.debug('Recording deployment %s', url)
        response = await self.post(url, json=dict(body))
        if response.is_error and (
            response.status_code != http.HTTPStatus.NOT_FOUND
        ):
            LOGGER.warning(
                'Failed to record deployment %r: %s', url, response.text
            )
        return response
