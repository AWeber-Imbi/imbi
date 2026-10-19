"""Claude Code plugin marketplaces (ADR 0022, plan section 5.2).

An organization registers a marketplace by git URL. :func:`fetch` reads
``.claude-plugin/marketplace.json`` at the head of the default branch
through the organization's GitHub integration: the ``deployment``
capability of the github plugin, with the marketplace URL as the
repository link. :func:`parse` turns the file into the plugin catalog.

The format is the marketplace reference of Claude Code
(https://code.claude.com/docs/en/plugins/marketplace-reference).
"""

import collections.abc
import datetime
import json
import logging
import posixpath
import re
import typing
import urllib.parse

import pydantic

from imbi.api.harness import store as harness_store
from imbi.api.plugins import assignments
from imbi.common import graph, models
from imbi.common.plugins import base, decrypt_integration_credentials
from imbi.common.plugins import errors as plugin_errors
from imbi.common.plugins import registry as plugin_registry

LOGGER = logging.getLogger(__name__)

MARKETPLACE_FILE = '.claude-plugin/marketplace.json'

_CAPABILITY = 'deployment'
_NAME: pydantic.TypeAdapter[str] = pydantic.TypeAdapter(models.PluginName)
_GITHUB_REPO = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')
_SHA = re.compile(r'[0-9a-f]{40}')


class SyncError(Exception):
    """The marketplace could not be read or parsed."""


class CatalogPlugin(pydantic.BaseModel):
    """One plugin entry of a marketplace."""

    name: str
    description: str | None = None
    version: str | None = None
    category: str | None = None
    #: The ``source`` of the entry, as the file gives it.
    source: str | dict[str, typing.Any]
    #: The plugin directory relative to the marketplace root, when the
    #: plugin is inside the marketplace repository. ``None`` for a
    #: plugin from another source (``github``, ``url``, ``npm``, ...).
    path: str | None = None
    #: The git URL of a ``url`` or ``github`` source.
    repository_url: str | None = None
    #: The commit of ``repository_url`` that the last sync resolved.
    #: ``None`` when the sync could not resolve it.
    repository_sha: str | None = None


class Catalog(pydantic.BaseModel):
    name: str
    description: str | None = None
    plugins: list[CatalogPlugin]


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _relative_path(source: str, plugin_root: str | None) -> str | None:
    """Resolve a relative-path source from the marketplace root.

    A bare name (no ``/``) resolves under ``metadata.pluginRoot``. A
    path that leaves the root, or that has a backslash, is refused.
    """
    if source != '.' and not source.startswith('./'):
        if '/' in source or plugin_root is None:
            return None
        source = posixpath.join(plugin_root, source)
    if '\\' in source or '..' in source.split('/'):
        return None
    return posixpath.normpath(source)


def _repository_url(source: dict[str, typing.Any]) -> str | None:
    """Return the https git URL of a ``url`` or ``github`` source."""
    kind, url, repo = (
        source.get('source'),
        source.get('url'),
        source.get('repo'),
    )
    if kind == 'url' and isinstance(url, str) and url.startswith('https://'):
        return url
    if kind == 'github' and isinstance(repo, str):
        if _GITHUB_REPO.fullmatch(repo):
            return f'https://github.com/{repo}.git'
    return None


def _host(url: str) -> str | None:
    try:
        return urllib.parse.urlsplit(url).hostname
    except ValueError:
        return None


def parse(text: str) -> Catalog:
    """Parse a ``marketplace.json`` document.

    Each plugin entry is checked on its own, as Claude Code does: an
    entry without a valid ``name`` or a ``source`` is skipped, and of
    two entries with one name the first is kept.

    Raises:
        SyncError: The document is not JSON, or has no valid ``name``
            or ``plugins`` list.

    """
    try:
        document: typing.Any = json.loads(text)
    except ValueError as err:
        raise SyncError(f'{MARKETPLACE_FILE} is not valid JSON') from err
    if not isinstance(document, dict):
        raise SyncError(f'{MARKETPLACE_FILE} is not a JSON object')
    data = typing.cast('dict[str, typing.Any]', document)
    entries: typing.Any = data.get('plugins')
    try:
        name = _NAME.validate_python(data.get('name'))
    except pydantic.ValidationError as err:
        raise SyncError(f'{MARKETPLACE_FILE} has no valid name') from err
    if not isinstance(entries, list):
        raise SyncError(f'{MARKETPLACE_FILE} has no plugins list')
    metadata: typing.Any = data.get('metadata')
    metadata = (
        typing.cast('dict[str, typing.Any]', metadata)
        if isinstance(metadata, dict)
        else {}
    )
    plugin_root = _text(metadata.get('pluginRoot'))
    if plugin_root is not None:
        plugin_root = _relative_path(plugin_root, None)
    plugins: list[CatalogPlugin] = []
    seen: set[str] = set()
    for raw in typing.cast('list[object]', entries):
        if not isinstance(raw, dict):
            continue
        entry = typing.cast('dict[str, typing.Any]', raw)
        source: typing.Any = entry.get('source')
        try:
            plugin_name = _NAME.validate_python(entry.get('name'))
        except pydantic.ValidationError:
            continue
        if plugin_name in seen or not isinstance(source, (str, dict)):
            continue
        seen.add(plugin_name)
        plugins.append(
            CatalogPlugin(
                name=plugin_name,
                description=_text(entry.get('description')),
                version=_text(entry.get('version')),
                category=_text(entry.get('category')),
                source=typing.cast('str | dict[str, typing.Any]', source),
                path=(
                    _relative_path(source, plugin_root)
                    if isinstance(source, str)
                    else None
                ),
                repository_url=(
                    _repository_url(
                        typing.cast('dict[str, typing.Any]', source)
                    )
                    if isinstance(source, dict)
                    else None
                ),
            )
        )
    return Catalog(
        name=name,
        description=_text(data.get('description'))
        or _text(metadata.get('description')),
        plugins=plugins,
    )


class Head(typing.NamedTuple):
    """The default branch head of a marketplace and its file."""

    default_branch: str
    sha: str
    text: str


async def fetch(db: graph.Graph, org_slug: str, url: str) -> Head:
    """Read the marketplace file at the head of the default branch.

    Raises:
        SyncError: No integration could read the file.

    """

    async def read(
        handler: base.DeploymentCapability,
        ctx: base.PluginContext,
        credentials: dict[str, str],
    ) -> Head | None:
        refs = await handler.list_refs(ctx, credentials, kind='default')
        if not refs or not refs[0].sha:
            raise SyncError('the default branch has no commit')
        text = await handler.get_file(
            ctx, credentials, MARKETPLACE_FILE, refs[0].sha
        )
        return None if text is None else Head(refs[0].name, refs[0].sha, text)

    return await _read(
        db, org_slug, url, read, f'{MARKETPLACE_FILE} not found'
    )


async def resolve_commit(
    db: graph.Graph, org_slug: str, plugin: CatalogPlugin
) -> str:
    """Return the commit of an external plugin's repository.

    The ``sha`` of the source wins, then its ``ref``, then the head of
    the default branch.

    Raises:
        SyncError: No integration could resolve the commit.

    """
    source = plugin.source if isinstance(plugin.source, dict) else {}
    sha, ref = source.get('sha'), source.get('ref')
    if sha is not None:
        # Never pin another commit in place of the one the source gives.
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            raise SyncError(f'invalid sha {sha!r}')
        return sha

    async def read(
        handler: base.DeploymentCapability,
        ctx: base.PluginContext,
        credentials: dict[str, str],
    ) -> str | None:
        if isinstance(ref, str) and ref:
            return (
                await handler.resolve_committish(ctx, credentials, ref)
            ).sha
        refs = await handler.list_refs(ctx, credentials, kind='default')
        return refs[0].sha if refs else None

    return await _read(
        db, org_slug, str(plugin.repository_url), read, 'commit not found'
    )


async def _read[T](
    db: graph.Graph,
    org_slug: str,
    url: str,
    read: collections.abc.Callable[
        [base.DeploymentCapability, base.PluginContext, dict[str, str]],
        collections.abc.Awaitable[T | None],
    ],
    missing: str,
) -> T:
    """Read from a repository through the organization's integrations.

    Each integration whose plugin has a ``deployment`` capability is
    tried in turn. An integration for another host cannot resolve the
    URL and is skipped. ``read`` returns ``None`` when the integration
    cannot find what it reads; then the next integration is tried.

    Raises:
        SyncError: No integration could read it.

    """
    errors: list[str] = []
    for integration in (
        await assignments.org_integrations(db, org_slug)
    ).values():
        handler = await _handler(db, integration)
        if handler is None:
            continue
        ctx = base.PluginContext(
            project_id='',
            project_slug='',
            org_slug=org_slug,
            integration_slug=str(integration.get('slug') or ''),
            integration_options=integration.get('options') or {},
            capability_options=assignments.capability_state(
                integration, _CAPABILITY
            ).get('options')
            or {},
            project_links={'github-repository': url},
        )
        credentials = decrypt_integration_credentials(
            integration.get('encrypted_credentials') or {}
        )
        try:
            result = await read(handler, ctx, credentials)
        except NotImplementedError:
            continue
        except Exception as err:  # noqa: BLE001 - try the next one
            LOGGER.info(
                'Integration %s cannot read %s: %s',
                integration.get('slug'),
                url,
                err,
            )
            errors.append(f'{integration.get("slug")}: {err}')
            continue
        if result is None:
            # Another integration can have access to the repository.
            errors.append(f'{integration.get("slug")}: {missing}')
            continue
        return result
    if not errors:
        raise SyncError(
            'The organization has no integration that can read '
            'repositories (the github plugin)'
        )
    raise SyncError('; '.join(errors))


async def _handler(
    db: graph.Graph, integration: dict[str, typing.Any]
) -> base.DeploymentCapability | None:
    """Return the deployment handler of an integration's plugin."""
    # Imported here, as in imbi.api.plugins.resolution: the lifecycle
    # module imports the plugin modules.
    from imbi.api.plugins import lifecycle

    slug = str(integration.get('plugin') or '')
    try:
        entry = plugin_registry.get_plugin(slug)
    except plugin_errors.PluginNotFoundError:
        return None
    capability = entry.manifest.get_capability(_CAPABILITY)
    if capability is None or not await lifecycle.is_plugin_enabled(db, slug):
        return None
    return typing.cast('base.DeploymentCapability', capability.handler())


async def sync(
    db: graph.Graph,
    store: harness_store.HarnessStore,
    org_slug: str,
    marketplace: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    """Sync a marketplace row and return it.

    A failure keeps the last catalog and sets ``sync_error``.
    """
    try:
        head = await fetch(db, org_slug, str(marketplace['url']))
        catalog = parse(head.text)
    except SyncError as err:
        changes: dict[str, typing.Any] = {'sync_error': str(err)[:2000]}
    else:
        # The runner sends its marketplace_fetch token to the plugin
        # host, and the token is for the marketplace host. So a plugin
        # can only live on the marketplace host.
        host = _host(str(marketplace['url']))
        for plugin in catalog.plugins:
            if plugin.repository_url is None:
                continue
            if host is None or _host(plugin.repository_url) != host:
                LOGGER.info(
                    'Marketplace %s: plugin %s is on another host',
                    marketplace['slug'],
                    plugin.name,
                )
                plugin.repository_url = None
                continue
            try:
                plugin.repository_sha = await resolve_commit(
                    db, org_slug, plugin
                )
            except SyncError as err:
                LOGGER.info(
                    'Marketplace %s: cannot resolve plugin %s: %s',
                    marketplace['slug'],
                    plugin.name,
                    err,
                )
        changes = {
            'name': catalog.name,
            'description': catalog.description,
            'default_branch': head.default_branch,
            'head_sha': head.sha,
            'plugins': [p.model_dump(mode='json') for p in catalog.plugins],
            'synced_at': datetime.datetime.now(datetime.UTC),
            'sync_error': None,
        }
    row = await store.set_marketplace_sync(marketplace['id'], changes)
    return row or marketplace
