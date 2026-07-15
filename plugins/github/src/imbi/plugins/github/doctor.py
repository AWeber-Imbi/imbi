"""GitHub-native analysis plugin (Project Doctor) for the GitHub plugin family.

Performs richer, GitHub-aware validation than the generic exists-in doctor:
identifier is an integer, canonical URL follows the /repositories/{id} shape
that the lifecycle plugin writes, dashboard link matches the API html_url, and
the legacy github-repository link matches as well.

A single analysis capability covers github.com, GHEC tenants, and GHES
appliances: the GitHub host is resolved from the Integration's ``flavor`` +
``host`` options, mirroring every other capability on the GitHub plugin. The
shared App/PAT credentials arrive through ``credentials`` (with the acting
user's identity token preferred); the capability declares no credential of
its own.
"""

from __future__ import annotations

import re
import typing

import httpx
from imbi_common.plugins.base import (
    AnalysisCapability,
    AnalysisResultItem,
    AnalysisResultStatus,
    LinkWriteback,
    PluginContext,
    RemediationOffer,
    RemediationResult,
    ServiceConnection,
    ServiceWriteback,
)
from imbi_common.plugins.errors import PluginAuthenticationFailed

from imbi_plugin_github._hosts import (
    flavor_host,
    host_to_api_base,
)
from imbi_plugin_github._repos import derive_owner_repo_from_links

_TIMEOUT = 15.0
# Matches the canonical URL shape written by the lifecycle plugin:
# https://api.{host}/repositories/{integer_id}
_REPO_ID_RE = re.compile(r'.*/repositories/(\d+)$')

# Remediation ids round-tripped through ``RemediationOffer.id``.  Every
# edge-shaped discrepancy (identifier, canonical URL shape, dashboard
# link) is repaired by one ``ServiceWriteback`` so they share an id; the
# legacy ``github-repository`` link is a separate ``LinkWriteback``.
_REPAIR_EDGE = 'repair-edge'
_REPAIR_GITHUB_LINK = 'repair-github-link'


async def _raise_on_401(response: httpx.Response) -> None:
    """Convert a 401 from GitHub into :class:`PluginAuthenticationFailed`.

    Mirrors the deployment / lifecycle plugins' hook so the host's retry
    layer can refresh the actor's identity once and retry remediation.
    Only installed on the ``remediate`` client; ``analyze`` deliberately
    treats 401 softly (warn) because diagnosis must not hard-fail.
    """
    if response.status_code != 401:
        return
    await response.aread()
    raise PluginAuthenticationFailed(
        f'GitHub 401 from {response.request.url}: {response.text}'
    )


def _json_object(resp: httpx.Response) -> dict[str, typing.Any] | None:
    """Return the response body when it is a JSON object, else ``None``.

    A 2xx response with a malformed or non-object payload should not
    raise from ``resp.json()`` / ``.get()``; callers turn ``None`` into a
    clear diagnostic (analyze) or remediation failure.
    """
    try:
        payload = resp.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    return typing.cast(dict[str, typing.Any], payload)


def _item(
    slug: str,
    title: str,
    status: AnalysisResultStatus,
    description: str,
    remediation: RemediationOffer | None = None,
) -> AnalysisResultItem:
    return AnalysisResultItem(
        slug=slug,
        title=title,
        status=status,
        description=description,
        remediation=remediation,
    )


def _repo_fetch_url(
    connection: ServiceConnection | None,
    ctx: PluginContext,
    host: str,
    api_base: str,
) -> str | None:
    """Resolve the GitHub API URL for the project's repository.

    Prefer the rename-stable canonical URL on the ``EXISTS_IN`` edge;
    otherwise derive ``(owner, repo)`` from the project links. Returns
    ``None`` when neither is available. ``connection`` is ``None`` when
    no ``EXISTS_IN`` edge exists yet (the create-edge remediation), in
    which case the URL is derived from the project links alone.

    The stored canonical URL is never fetched verbatim: only the numeric
    repository id is trusted from it, and the request URL is rebuilt
    through the resolved ``api_base`` (the routing single source of
    truth). This keeps the Bearer token from ever being sent to an
    arbitrary host smuggled onto the ``EXISTS_IN`` edge.
    """
    if connection is not None and connection.canonical_url:
        match = _REPO_ID_RE.fullmatch(connection.canonical_url)
        if match is not None:
            return f'{api_base}/repositories/{match.group(1)}'
    derived = derive_owner_repo_from_links(
        ctx.project_links,
        host,
        preferred_key=ctx.integration_slug,
    )
    if derived is not None:
        owner, repo = derived
        return f'{api_base}/repos/{owner}/{repo}'
    return None


def _find_connection(
    connections: list[ServiceConnection],
    slug: str,
) -> ServiceConnection | None:
    """Return the ``EXISTS_IN`` connection matching ``slug``, else ``None``.

    Shared by ``analyze`` and ``remediate`` so the lookup over
    ``ctx.service_connections`` lives in one place.
    """
    return next(
        (c for c in connections if c.integration_slug == slug),
        None,
    )


class GitHubDoctor(AnalysisCapability):
    """GitHub project-doctor analysis capability.

    Resolves the GitHub host from the Integration's ``flavor`` + ``host``
    options (github.com / GHEC tenant / GHES appliance) and validates the
    ``EXISTS_IN`` edge against the live GitHub API.
    """

    async def analyze(  # noqa: C901 — flat sequence of independent checks
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> list[AnalysisResultItem]:
        results: list[AnalysisResultItem] = []

        try:
            host = flavor_host(ctx.integration_options, 'github doctor')
        except ValueError as exc:
            return [_item('connection', 'GitHub connection', 'warn', str(exc))]
        api_base = host_to_api_base(host)

        # Step 1: locate the EXISTS_IN connection for this integration.
        slug = ctx.integration_slug
        if not slug:
            return [
                _item(
                    'exists-in',
                    'Service binding',
                    'warn',
                    'This plugin is not bound to a third-party service — '
                    'no EXISTS_IN edge can be inspected.',
                )
            ]

        connection = _find_connection(ctx.service_connections, slug)
        if connection is None:
            return [
                _item(
                    'exists-in',
                    'EXISTS_IN edge',
                    'warn',
                    f'No EXISTS_IN edge found for service {slug!r}. '
                    'Use the Fix action to create the repository link '
                    'from GitHub, or run the lifecycle plugin to '
                    're-index this project.',
                    RemediationOffer(
                        id=_REPAIR_EDGE,
                        label='Create the EXISTS_IN edge from GitHub',
                    ),
                )
            ]

        results.append(
            _item(
                'exists-in',
                'EXISTS_IN edge',
                'pass',
                f'EXISTS_IN edge for {slug!r} is present '
                f'(identifier={connection.identifier!r}).',
            )
        )

        # Step 2: build the Bearer token (optional).
        token = credentials.get('access_token') or credentials.get('token')
        headers: dict[str, str] = {}
        if token:
            headers['Authorization'] = f'Bearer {token}'

        # Step 3: determine the URL to fetch.
        fetch_url = _repo_fetch_url(connection, ctx, host, api_base)
        if fetch_url is None:
            results.append(
                _item(
                    'canonical-url',
                    'Canonical URL',
                    'warn',
                    'No canonical URL on the EXISTS_IN edge and no '
                    'resolvable project link — cannot fetch the '
                    'GitHub repository.',
                )
            )
            # Without a URL we cannot run any body-dependent checks.
            results.extend(_body_unavailable_items())
            return results

        # Step 4: fetch the repo.
        try:
            async with httpx.AsyncClient(
                headers=headers,
                timeout=_TIMEOUT,
            ) as client:
                resp = await client.get(fetch_url)
        except httpx.TransportError as exc:
            results.append(
                _item(
                    'canonical-url',
                    'Canonical URL',
                    'fail',
                    f'Transport error fetching {fetch_url!r}: {exc}',
                )
            )
            results.extend(_body_unavailable_items())
            return results

        if resp.status_code in (401, 403):
            if token:
                status: AnalysisResultStatus = 'fail'
                hint = (
                    'Token was present but rejected — check that the '
                    'access token has at minimum repo scope.'
                )
            else:
                status = 'warn'
                hint = (
                    'No access token configured; the repository may be '
                    'private.  Configure an access_token credential to '
                    'inspect private repositories.'
                )
            results.append(
                _item(
                    'canonical-url',
                    'Canonical URL',
                    status,
                    f'HTTP {resp.status_code} from {fetch_url!r}. {hint}',
                )
            )
            results.extend(_body_unavailable_items())
            return results

        if resp.status_code == 404:
            results.append(
                _item(
                    'canonical-url',
                    'Canonical URL',
                    'fail',
                    f'Repository not found at {fetch_url!r} (HTTP 404). '
                    'The repository may have been deleted or moved.',
                )
            )
            results.extend(_body_unavailable_items())
            return results

        if not resp.is_success:
            results.append(
                _item(
                    'canonical-url',
                    'Canonical URL',
                    'fail',
                    f'Unexpected HTTP {resp.status_code} from {fetch_url!r}.',
                )
            )
            results.extend(_body_unavailable_items())
            return results

        body = _json_object(resp)
        if body is None:
            results.append(
                _item(
                    'canonical-url',
                    'Canonical URL',
                    'fail',
                    f'GitHub returned an unexpected (non-object) body '
                    f'from {fetch_url!r}.',
                )
            )
            results.extend(_body_unavailable_items())
            return results

        results.append(
            _item(
                'canonical-url',
                'Canonical URL',
                'pass',
                f'Fetched {fetch_url!r} — HTTP {resp.status_code}.',
            )
        )

        # Step 5: body-dependent checks.

        # identifier-type
        try:
            int(connection.identifier)
        except (ValueError, TypeError):
            results.append(
                _item(
                    'identifier-type',
                    'Identifier type',
                    'fail',
                    f'EXISTS_IN identifier {connection.identifier!r} cannot '
                    'be parsed as an integer. GitHub repository IDs are '
                    'always integers; the stored value is corrupt.',
                    RemediationOffer(
                        id=_REPAIR_EDGE,
                        label='Repair the EXISTS_IN edge from GitHub',
                    ),
                )
            )
        else:
            results.append(
                _item(
                    'identifier-type',
                    'Identifier type',
                    'pass',
                    f'EXISTS_IN identifier {connection.identifier!r} parses '
                    'as an integer.',
                )
            )

        # identifier-match
        api_id = str(body.get('id', ''))
        if api_id == connection.identifier:
            results.append(
                _item(
                    'identifier-match',
                    'Identifier match',
                    'pass',
                    f'EXISTS_IN identifier {connection.identifier!r} matches '
                    f'the GitHub API id {api_id!r}.',
                )
            )
        else:
            results.append(
                _item(
                    'identifier-match',
                    'Identifier match',
                    'fail',
                    f'EXISTS_IN identifier {connection.identifier!r} does not '
                    f'match the GitHub API id {api_id!r}. '
                    'Use the Fix action to repair the edge from GitHub.',
                    RemediationOffer(
                        id=_REPAIR_EDGE,
                        label='Repair the EXISTS_IN edge from GitHub',
                    ),
                )
            )

        # canonical-url-shape
        if connection.canonical_url:
            expected_prefix = f'{api_base}/repositories/'
            match = _REPO_ID_RE.fullmatch(connection.canonical_url)
            if match and connection.canonical_url.startswith(expected_prefix):
                results.append(
                    _item(
                        'canonical-url-shape',
                        'Canonical URL shape',
                        'pass',
                        f'Canonical URL {connection.canonical_url!r} follows '
                        f'the https://api.{{host}}/repositories/{{id}} shape.',
                    )
                )
            else:
                results.append(
                    _item(
                        'canonical-url-shape',
                        'Canonical URL shape',
                        'fail',
                        f'Canonical URL {connection.canonical_url!r} does not '
                        f'follow the expected '
                        f'{api_base}/repositories/{{id}} shape. '
                        'Use the Fix action to repair the edge from GitHub.',
                        RemediationOffer(
                            id=_REPAIR_EDGE,
                            label='Repair the EXISTS_IN edge from GitHub',
                        ),
                    )
                )
        else:
            results.append(
                _item(
                    'canonical-url-shape',
                    'Canonical URL shape',
                    'warn',
                    'No canonical URL stored on the EXISTS_IN edge — '
                    'shape cannot be verified.',
                )
            )

        # dashboard-url-match
        html_url = str(body.get('html_url', ''))
        tps_link = ctx.project_links.get(slug)
        if tps_link is None:
            results.append(
                _item(
                    'dashboard-url-match',
                    'Dashboard URL match',
                    'warn',
                    f'No dashboard link stored for service {slug!r}. '
                    'Use the Fix action to set it from GitHub.',
                    RemediationOffer(
                        id=_REPAIR_EDGE,
                        label='Set the dashboard link from GitHub',
                    ),
                )
            )
        elif tps_link == html_url:
            results.append(
                _item(
                    'dashboard-url-match',
                    'Dashboard URL match',
                    'pass',
                    f'Dashboard link {tps_link!r} matches the GitHub '
                    f'html_url {html_url!r}.',
                )
            )
        else:
            results.append(
                _item(
                    'dashboard-url-match',
                    'Dashboard URL match',
                    'fail',
                    f'Dashboard link {tps_link!r} does not match the GitHub '
                    f'html_url {html_url!r}. '
                    'Use the Fix action to update it from GitHub.',
                    RemediationOffer(
                        id=_REPAIR_EDGE,
                        label='Set the dashboard link from GitHub',
                    ),
                )
            )

        # github-repository-link-match
        gh_link = ctx.project_links.get('github-repository')
        if gh_link is None:
            results.append(
                _item(
                    'github-repository-link-match',
                    'github-repository link match',
                    'warn',
                    'No github-repository link stored on the project. '
                    'Use the Fix action to set it from GitHub.',
                    RemediationOffer(
                        id=_REPAIR_GITHUB_LINK,
                        label='Set the github-repository link from GitHub',
                    ),
                )
            )
        elif gh_link == html_url:
            results.append(
                _item(
                    'github-repository-link-match',
                    'github-repository link match',
                    'pass',
                    f'github-repository link {gh_link!r} matches the '
                    f'GitHub html_url {html_url!r}.',
                )
            )
        else:
            results.append(
                _item(
                    'github-repository-link-match',
                    'github-repository link match',
                    'fail',
                    f'github-repository link {gh_link!r} does not match '
                    f'the GitHub html_url {html_url!r}. '
                    'Use the Fix action to update it from GitHub.',
                    RemediationOffer(
                        id=_REPAIR_GITHUB_LINK,
                        label='Set the github-repository link from GitHub',
                    ),
                )
            )

        return results

    async def remediate(  # noqa: C901 — flat sequence of guard clauses
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        remediation_id: str,
    ) -> RemediationResult:
        """Create or repair the EXISTS_IN edge / github-repository link.

        Re-fetches the repository (the live source of truth) and emits a
        ``ServiceWriteback`` / ``LinkWriteback`` on ``ctx`` for the host
        to persist.  ``_REPAIR_EDGE`` also creates the edge when none
        exists yet (the host's writeback is an upsert), deriving the repo
        from the project links.  Idempotent: returns ``noop`` when Imbi
        already matches GitHub.  A 401 propagates as
        ``PluginAuthenticationFailed`` so the host can refresh the actor's
        identity and retry once.
        """
        if remediation_id not in (_REPAIR_EDGE, _REPAIR_GITHUB_LINK):
            return await super().remediate(ctx, credentials, remediation_id)

        try:
            host = flavor_host(ctx.integration_options, 'github doctor')
        except ValueError as exc:
            return RemediationResult(status='failed', message=str(exc))
        api_base = host_to_api_base(host)
        slug = ctx.integration_slug
        if slug is None:
            return RemediationResult(
                status='failed',
                message=(
                    'This plugin is not bound to a service — no EXISTS_IN '
                    'edge to create or repair.'
                ),
            )
        connection = _find_connection(ctx.service_connections, slug)
        # ``_REPAIR_EDGE`` creates a missing edge from GitHub, so a
        # missing connection is only fatal for the github-repository
        # link repair (which never needs the edge but is only ever
        # offered once the edge is present).
        if connection is None and remediation_id == _REPAIR_GITHUB_LINK:
            return RemediationResult(
                status='failed',
                message=(
                    'No EXISTS_IN edge for this service — nothing to '
                    'repair. Run the lifecycle plugin to create it.'
                ),
            )

        fetch_url = _repo_fetch_url(connection, ctx, host, api_base)
        if fetch_url is None:
            return RemediationResult(
                status='failed',
                message=(
                    'Cannot resolve the GitHub repository URL from the '
                    'EXISTS_IN edge or project links.'
                ),
            )

        token = credentials.get('access_token') or credentials.get('token')
        headers: dict[str, str] = {}
        if token:
            headers['Authorization'] = f'Bearer {token}'

        # The 401 hook raises PluginAuthenticationFailed so the host's
        # identity-retry layer can refresh and retry once.
        try:
            async with httpx.AsyncClient(
                headers=headers,
                timeout=_TIMEOUT,
                event_hooks={'response': [_raise_on_401]},
            ) as client:
                resp = await client.get(fetch_url)
        except httpx.TransportError as exc:
            return RemediationResult(
                status='failed',
                message=f'Transport error fetching {fetch_url!r}: {exc}',
            )
        if not resp.is_success:
            return RemediationResult(
                status='failed',
                message=f'HTTP {resp.status_code} fetching {fetch_url!r}.',
            )

        body = _json_object(resp)
        if body is None:
            return RemediationResult(
                status='failed',
                message=(
                    f'GitHub returned an unexpected (non-object) body '
                    f'from {fetch_url!r}.'
                ),
            )
        api_id = body.get('id')
        html_url = body.get('html_url')
        if not isinstance(api_id, int):
            return RemediationResult(
                status='failed',
                message='GitHub response did not include an integer id.',
            )
        if not isinstance(html_url, str) or not html_url:
            return RemediationResult(
                status='failed',
                message='GitHub response did not include an html_url.',
            )

        if remediation_id == _REPAIR_GITHUB_LINK:
            if ctx.project_links.get('github-repository') == html_url:
                return RemediationResult(
                    status='noop',
                    message='github-repository link already matches GitHub.',
                )
            ctx.link_writeback = LinkWriteback(
                link_key='github-repository',
                new_url=html_url,
            )
            return RemediationResult(
                status='fixed',
                message=f'Set github-repository link to {html_url}.',
            )

        # _REPAIR_EDGE: create or rewrite identifier + canonical URL +
        # dashboard link in one ServiceWriteback.
        desired_canonical = f'{api_base}/repositories/{api_id}'
        if connection is not None:
            already_correct = (
                connection.identifier == str(api_id)
                and connection.canonical_url == desired_canonical
                and ctx.project_links.get(slug) == html_url
            )
            if already_correct:
                return RemediationResult(
                    status='noop',
                    message='EXISTS_IN edge already matches GitHub.',
                )
        ctx.service_writeback = ServiceWriteback(
            identifier=str(api_id),
            canonical_url=desired_canonical,
            dashboard_links={slug: html_url},
        )
        verb = 'Repaired' if connection is not None else 'Created'
        return RemediationResult(
            status='fixed',
            message=(
                f'{verb} the EXISTS_IN edge for {slug!r} '
                f'(identifier={api_id}).'
            ),
        )


def _body_unavailable_items() -> list[AnalysisResultItem]:
    """Return warn items for body-dependent checks when the fetch fails."""
    return [
        _item(
            'identifier-type',
            'Identifier type',
            'warn',
            'Cannot verify identifier type: repository fetch failed.',
        ),
        _item(
            'identifier-match',
            'Identifier match',
            'warn',
            'Cannot verify identifier: repository fetch failed.',
        ),
        _item(
            'canonical-url-shape',
            'Canonical URL shape',
            'warn',
            'Cannot verify canonical URL shape: repository fetch failed.',
        ),
        _item(
            'dashboard-url-match',
            'Dashboard URL match',
            'warn',
            'Cannot verify dashboard URL: repository fetch failed.',
        ),
        _item(
            'github-repository-link-match',
            'github-repository link match',
            'warn',
            'Cannot verify github-repository link: repository fetch failed.',
        ),
    ]
