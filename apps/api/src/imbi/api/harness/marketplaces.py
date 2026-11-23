"""Claude Code plugin marketplaces (ADR 0022, plan section 5.2).

An organization registers a marketplace by git URL. :func:`fetch` reads
``.claude-plugin/marketplace.json`` at the head of the default branch
through the organization's GitHub integration: the ``deployment``
capability of the github plugin, with the marketplace URL as the
repository link. :func:`parse` turns the file into the plugin catalog.
:func:`sync` then reads the MCP servers of each plugin.

The format is the marketplace reference of Claude Code
(https://code.claude.com/docs/en/plugins/marketplace-reference).
"""

import asyncio
import collections.abc
import datetime
import functools
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
PLUGIN_MANIFEST = '.claude-plugin/plugin.json'

_CAPABILITY = 'deployment'
_CONCURRENCY = 8
_NAME: pydantic.TypeAdapter[str] = pydantic.TypeAdapter(models.PluginName)
_GITHUB_REPO = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')
_SHA = re.compile(r'[0-9a-f]{40}')
_VARIABLE = re.compile(r'\$\{([^}]+)\}')


class SyncError(Exception):
    """The marketplace could not be read or parsed."""


class CatalogServer(pydantic.BaseModel):
    """One MCP server of a plugin.

    ``headers`` maps each header name to the ``${VAR}`` names that its
    value uses. A plugin author can commit a literal token in a header,
    so no header value is stored.
    """

    name: str
    type: str = 'stdio'
    url: str | None = None
    headers: dict[str, list[str]] = {}


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
    #: The MCP servers that the harness loads for the plugin.
    mcp_servers: list[CatalogServer] = []

    @pydantic.field_validator('mcp_servers', mode='before')
    @classmethod
    def _legacy_names(cls, value: object) -> object:
        """Read a row that the sync wrote before it stored servers."""
        if not isinstance(value, list):
            return value
        return [
            {'name': item} if isinstance(item, str) else item
            for item in typing.cast('list[object]', value)
        ]


class Catalog(pydantic.BaseModel):
    name: str
    description: str | None = None
    plugins: list[CatalogPlugin]
    #: The ``mcpServers`` of each plugin's entry, by plugin name.
    entry_servers: dict[str, object] = {}


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


def _variables(value: object) -> list[str]:
    """The names of the ``${VAR}`` and ``${VAR:-default}`` in a value."""
    if not isinstance(value, str):
        return []
    names = (match.split(':-', 1)[0] for match in _VARIABLE.findall(value))
    return list(dict.fromkeys(names))


def _header_variables(headers: object) -> dict[str, list[str]]:
    if not isinstance(headers, dict):
        return {}
    return {
        str(header): _variables(value)
        for header, value in typing.cast('dict[str, object]', headers).items()
    }


def _server(name: str, config: dict[str, typing.Any]) -> CatalogServer:
    kind = _text(config.get('type')) or 'stdio'
    if kind == 'stdio':
        return CatalogServer(name=name)
    return CatalogServer(
        name=name,
        type=kind,
        url=_text(config.get('url')),
        headers=_header_variables(config.get('headers')),
    )


def servers(sources: collections.abc.Iterable[object]) -> list[CatalogServer]:
    """Return the servers of ``mcpServers`` objects, sorted by name.

    Of two servers with one name, the first is kept. A source that is
    not an object, and a server that is not an object, add nothing.
    """
    found: dict[str, CatalogServer] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for name, config in typing.cast('dict[str, object]', source).items():
            if isinstance(config, dict) and str(name) not in found:
                found[str(name)] = _server(
                    str(name), typing.cast('dict[str, typing.Any]', config)
                )
    return sorted(found.values(), key=lambda server: server.name)


def _document(text: str | None) -> dict[str, typing.Any]:
    try:
        document: typing.Any = json.loads(text) if text else {}
    except ValueError:
        return {}
    return (
        typing.cast('dict[str, typing.Any]', document)
        if isinstance(document, dict)
        else {}
    )


def _plugin_file(directory: str, path: str) -> str | None:
    """Resolve a path of a plugin file, refusing one that leaves it."""
    if path.startswith('/') or '..' in path.split('/'):
        return None
    return posixpath.normpath(posixpath.join(directory, path))


type FileReader = collections.abc.Callable[
    [str], collections.abc.Awaitable[str | None]
]


async def _source(read: FileReader, directory: str, source: object) -> object:
    """Return an ``mcpServers`` object, read from its file when it is a
    path."""
    if not isinstance(source, str):
        return source
    path = _plugin_file(directory, source)
    document = _document(None if path is None else await read(path))
    return document.get('mcpServers', document)


async def plugin_servers(
    read: FileReader, directory: str, entry_servers: object
) -> list[CatalogServer]:
    """Return the MCP servers that the harness loads for a plugin.

    With a ``.claude-plugin/plugin.json``, the servers come from its
    ``mcpServers``, else from ``entry_servers``, the ``mcpServers`` of
    the marketplace entry. Either is an object, the path of a JSON file
    in the plugin directory, or a list of both. The plugin's
    ``.mcp.json`` adds its servers.

    Args:
        read: Returns the text of a repository file, or ``None``.
        directory: The plugin directory in the repository.
        entry_servers: The ``mcpServers`` of the marketplace entry.

    """
    manifest = await read(
        posixpath.normpath(posixpath.join(directory, PLUGIN_MANIFEST))
    )
    declared: object = (
        entry_servers
        if manifest is None
        else _document(manifest).get('mcpServers')
    )
    sources: list[object] = (
        list(typing.cast('list[object]', declared))
        if isinstance(declared, list)
        else [declared]
    )
    return servers(
        [
            await _source(read, directory, source)
            for source in [*sources, '.mcp.json']
        ]
    )


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
    entry_servers: dict[str, object] = {}
    for raw in typing.cast('list[object]', entries):
        if not isinstance(raw, dict):
            continue
        entry = typing.cast('dict[str, typing.Any]', raw)
        source: typing.Any = entry.get('source')
        try:
            plugin_name = _NAME.validate_python(entry.get('name'))
        except pydantic.ValidationError:
            continue
        if plugin_name in entry_servers or not isinstance(source, (str, dict)):
            continue
        plugin = CatalogPlugin(
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
                _repository_url(typing.cast('dict[str, typing.Any]', source))
                if isinstance(source, dict)
                else None
            ),
        )
        plugins.append(plugin)
        entry_servers[plugin_name] = entry.get('mcpServers')
    return Catalog(
        name=name,
        description=_text(data.get('description'))
        or _text(metadata.get('description')),
        plugins=plugins,
        entry_servers=entry_servers,
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
        handler: base.RepositoryReader,
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
        ref = sha
    elif ref is not None and (not isinstance(ref, str) or not ref):
        raise SyncError(f'invalid ref {ref!r}')

    async def read(
        handler: base.RepositoryReader,
        ctx: base.PluginContext,
        credentials: dict[str, str],
    ) -> str | None:
        if ref is not None:
            # A sha resolves to itself only when the repository has it.
            return (
                await handler.resolve_committish(ctx, credentials, ref)
            ).sha
        refs = await handler.list_refs(ctx, credentials, kind='default')
        return refs[0].sha if refs else None

    found = await _read(
        db, org_slug, str(plugin.repository_url), read, 'commit not found'
    )
    if sha is not None and found != sha:
        raise SyncError(f'sha {sha} is not in the repository')
    return found


async def _read[T](
    db: graph.Graph,
    org_slug: str,
    url: str,
    read: collections.abc.Callable[
        [base.RepositoryReader, base.PluginContext, dict[str, str]],
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
    for public in await _public_readers(db, url):
        # As the runner does: a public repository needs no credentials,
        # so read it anonymously.
        try:
            result = await read(
                public, typing.cast('base.PluginContext', None), {}
            )
        except Exception as err:  # noqa: BLE001 - report with the rest
            errors.append(f'anonymous: {err}')
        else:
            if result is not None:
                return result
            errors.append(f'anonymous: {missing}')
    if not errors:
        raise SyncError(
            'The organization has no integration that can read '
            'repositories (the github plugin)'
        )
    raise SyncError('; '.join(errors))


async def _public_readers(
    db: graph.Graph, url: str
) -> list[base.RepositoryReader]:
    """Return the credential-free readers that enabled plugins offer for
    ``url``."""
    from imbi.api.plugins import lifecycle

    readers: list[base.RepositoryReader] = []
    for entry in plugin_registry.list_plugins():
        capability = entry.manifest.get_capability(_CAPABILITY)
        if capability is None or not await lifecycle.is_plugin_enabled(
            db, entry.manifest.slug
        ):
            continue
        handler = typing.cast(
            'type[base.DeploymentCapability]', capability.handler
        )
        try:
            reader = handler.public_reader(url)
        except Exception as err:  # noqa: BLE001 - skip this plugin
            # Do not log credentials in the userinfo or query.
            parts = urllib.parse.urlsplit(url)
            safe_url = urllib.parse.urlunsplit(
                parts._replace(
                    netloc=parts.netloc.rsplit('@', 1)[-1],
                    query='',
                    fragment='',
                )
            )
            LOGGER.info(
                'Plugin %s cannot offer a public reader for %s: %s',
                entry.manifest.slug,
                safe_url,
                err,
            )
            continue
        if reader is not None:
            readers.append(reader)
    return readers


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


async def read_file(
    db: graph.Graph, org_slug: str, url: str, ref: str, path: str
) -> str | None:
    """Return a repository file at ``ref``, or ``None`` when no reader
    of the organization can read it."""

    async def read(
        handler: base.RepositoryReader,
        ctx: base.PluginContext,
        credentials: dict[str, str],
    ) -> str | None:
        return await handler.get_file(ctx, credentials, path, ref)

    try:
        return await _read(db, org_slug, url, read, f'{path} not found')
    except SyncError:
        return None


async def _resolve(
    db: graph.Graph,
    org_slug: str,
    marketplace: dict[str, typing.Any],
    plugin: CatalogPlugin,
) -> None:
    """Resolve the commit of an external plugin."""
    if plugin.repository_url is None:
        return
    # The runner sends its marketplace_fetch token to the plugin host,
    # and the token is for the marketplace host. So a plugin can only
    # live on the marketplace host.
    host = _host(str(marketplace['url']))
    if host is None or _host(plugin.repository_url) != host:
        LOGGER.info(
            'Marketplace %s: plugin %s is on another host',
            marketplace['slug'],
            plugin.name,
        )
        plugin.repository_url = None
        return
    try:
        plugin.repository_sha = await resolve_commit(db, org_slug, plugin)
    except SyncError as err:
        LOGGER.info(
            'Marketplace %s: cannot resolve plugin %s: %s',
            marketplace['slug'],
            plugin.name,
            err,
        )


def _location(
    plugin: CatalogPlugin, url: str, head_sha: str
) -> tuple[str, str, str] | None:
    """Return the repository URL, commit, and directory of a plugin, or
    ``None`` when no runner can load it."""
    if plugin.path is not None:
        return url, head_sha, plugin.path
    if plugin.repository_url and plugin.repository_sha:
        return plugin.repository_url, plugin.repository_sha, '.'
    return None


async def _sync_plugin(
    db: graph.Graph,
    org_slug: str,
    marketplace: dict[str, typing.Any],
    head_sha: str,
    plugin: CatalogPlugin,
    entry_servers: object,
) -> None:
    """Resolve the commit of a plugin and read its MCP servers.

    The runner reads the entry of an external plugin from the plugin's
    own repository, so only a plugin in the marketplace repository
    falls back to ``entry_servers``.
    """
    await _resolve(db, org_slug, marketplace, plugin)
    location = _location(plugin, str(marketplace['url']), head_sha)
    if location is None:
        return
    url, ref, directory = location
    plugin.mcp_servers = await plugin_servers(
        functools.partial(read_file, db, org_slug, url, ref),
        directory,
        entry_servers if plugin.path is not None else None,
    )


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
        limit = asyncio.Semaphore(_CONCURRENCY)

        async def sync_plugin(plugin: CatalogPlugin) -> None:
            async with limit:
                await _sync_plugin(
                    db,
                    org_slug,
                    marketplace,
                    head.sha,
                    plugin,
                    catalog.entry_servers.get(plugin.name),
                )

        await asyncio.gather(*map(sync_plugin, catalog.plugins))
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
