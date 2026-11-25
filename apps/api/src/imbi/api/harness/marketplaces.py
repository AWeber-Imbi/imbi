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
    mcp_servers: models.CatalogServers = []


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


def _public_url(value: object) -> str | None:
    """Return a URL without the parts that can carry a credential: the
    user information, the query, and the fragment.

    A value with no host, such as one that starts with a
    ``${VAR:-default}`` reference, returns ``None``: its parts cannot be
    told apart, so a credential in it cannot be removed.
    """
    if not isinstance(value, str):
        return None
    try:
        parts = urllib.parse.urlsplit(value)
    except ValueError:
        return None
    if not parts.hostname:
        return None
    host = parts.netloc.rpartition('@')[2]
    return urllib.parse.urlunsplit((parts.scheme, host, parts.path, '', ''))


def _server(name: str, config: dict[str, typing.Any]) -> models.CatalogServer:
    kind = _text(config.get('type')) or 'stdio'
    if kind == 'stdio':
        return models.CatalogServer(name=name)
    return models.CatalogServer(
        name=name,
        type=kind,
        url=_public_url(config.get('url')),
        headers=_header_variables(config.get('headers')),
    )


def servers(
    sources: collections.abc.Iterable[object],
) -> list[models.CatalogServer]:
    """Return the servers of ``mcpServers`` objects, sorted by name.

    Of two servers with one name, the later replaces the earlier, as in
    the CLI. A source that is not an object, and a server that is not
    an object, add nothing.
    """
    found: dict[str, models.CatalogServer] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for name, config in typing.cast('dict[str, object]', source).items():
            if isinstance(config, dict):
                found[str(name)] = _server(
                    str(name), typing.cast('dict[str, typing.Any]', config)
                )
    return sorted(found.values(), key=lambda server: server.name)


def _document(text: str | None) -> dict[str, typing.Any]:
    try:
        document: typing.Any = json.loads(text) if text else {}
    except ValueError, RecursionError:
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
type EntryServers = collections.abc.Callable[
    [], collections.abc.Awaitable[object]
]


async def _source(
    read: FileReader, directory: str, source: object, label: str
) -> object:
    """Return an ``mcpServers`` object, read from its file when it is a
    path."""
    if not isinstance(source, str):
        return source
    path = _plugin_file(directory, source)
    if path is None:
        LOGGER.warning(
            '%s: the MCP server file %r is outside the plugin, so the '
            'runner fails its tasks',
            label,
            source,
        )
        return None
    document = _document(await read(path))
    return document.get('mcpServers', document)


async def plugin_servers(
    read: FileReader,
    directory: str,
    entry_servers: EntryServers,
    label: str,
) -> list[models.CatalogServer]:
    """Return the MCP servers that the harness loads for a plugin.

    With a ``.claude-plugin/plugin.json``, the servers come from its
    ``mcpServers``, else from the ``mcpServers`` of the plugin's
    marketplace entry. Either is an object, the path of a JSON file in
    the plugin directory, or a list of both. The plugin's ``.mcp.json``
    adds its servers. A missing or invalid file adds no servers.

    Args:
        read: Returns the text of a repository file, or ``None`` when
            the repository has no such file.
        directory: The plugin directory in the repository.
        entry_servers: Returns the ``mcpServers`` of the marketplace
            entry. Awaited only when the plugin has no ``plugin.json``.
        label: Names the plugin in log messages.

    Raises:
        SyncError: ``read`` could not read a file.

    """
    manifest = await read(
        posixpath.normpath(posixpath.join(directory, PLUGIN_MANIFEST))
    )
    declared: object = (
        await entry_servers()
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
            await _source(read, directory, source, label)
            for source in ['.mcp.json', *sources]
        ]
    )


def _entry_servers(document: dict[str, typing.Any], name: str) -> object:
    """Return the ``mcpServers`` of the entry for ``name`` in a
    marketplace document, as the runner picks it: the first entry of
    that name with a ``source``."""
    entries: object = document.get('plugins')
    if not isinstance(entries, list):
        return None
    for entry in typing.cast('list[object]', entries):
        if not isinstance(entry, dict):
            continue
        found = typing.cast('dict[str, typing.Any]', entry)
        if found.get('name') == name and isinstance(
            found.get('source'), (str, dict)
        ):
            return found.get('mcpServers')
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
    except ValueError as error:
        raise SyncError(f'{MARKETPLACE_FILE} is not valid JSON') from error
    if not isinstance(document, dict):
        raise SyncError(f'{MARKETPLACE_FILE} is not a JSON object')
    data = typing.cast('dict[str, typing.Any]', document)
    entries: typing.Any = data.get('plugins')
    try:
        name = _NAME.validate_python(data.get('name'))
    except pydantic.ValidationError as error:
        raise SyncError(f'{MARKETPLACE_FILE} has no valid name') from error
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


class _Integration(typing.NamedTuple):
    slug: str
    handler: base.DeploymentCapability
    context: base.PluginContext
    credentials: dict[str, str]


class Readers(typing.NamedTuple):
    """The repository readers of an organization, looked up once."""

    integrations: list[_Integration]
    #: The deployment handlers of the enabled plugins, by plugin slug,
    #: that can offer a credential-free reader for a URL.
    public: list[tuple[str, type[base.DeploymentCapability]]]


async def organization_readers(db: graph.Graph, org_slug: str) -> Readers:
    """Look up what can read a repository for the organization: each
    integration whose plugin has a ``deployment`` capability, and each
    enabled plugin that can read a public repository."""
    integrations: list[_Integration] = []
    for integration in (
        await assignments.org_integrations(db, org_slug)
    ).values():
        handler = await _handler(db, integration)
        if handler is None:
            continue
        slug = str(integration.get('slug') or '')
        integrations.append(
            _Integration(
                slug=slug,
                handler=handler,
                context=base.PluginContext(
                    project_id='',
                    project_slug='',
                    org_slug=org_slug,
                    integration_slug=slug,
                    integration_options=integration.get('options') or {},
                    capability_options=assignments.capability_state(
                        integration, _CAPABILITY
                    ).get('options')
                    or {},
                ),
                credentials=decrypt_integration_credentials(
                    integration.get('encrypted_credentials') or {}
                ),
            )
        )
    return Readers(integrations, await _public_handlers(db))


async def fetch(readers: Readers, url: str) -> Head:
    """Read the marketplace file at the head of the default branch.

    Raises:
        SyncError: No reader could read the file.

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

    return await _read(readers, url, read, f'{MARKETPLACE_FILE} not found')


async def resolve_commit(readers: Readers, plugin: CatalogPlugin) -> str:
    """Return the commit of an external plugin's repository.

    The ``sha`` of the source wins, then its ``ref``, then the head of
    the default branch.

    Raises:
        SyncError: No reader could resolve the commit.

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
        readers, str(plugin.repository_url), read, 'commit not found'
    )
    if sha is not None and found != sha:
        raise SyncError(f'sha {sha} is not in the repository')
    return found


class NotFoundError(SyncError):
    """No reader could read it, and at least one found that the
    repository does not have it."""


type _Attempt = tuple[
    str, base.RepositoryReader, base.PluginContext, dict[str, str]
]


def _attempts(
    readers: Readers, url: str
) -> collections.abc.Iterator[_Attempt]:
    for integration in readers.integrations:
        yield (
            integration.slug,
            integration.handler,
            integration.context.model_copy(
                update={'project_links': {'github-repository': url}}
            ),
            integration.credentials,
        )
    # As the runner does: a public repository needs no credentials, so
    # read it anonymously.
    for reader in _public_readers(readers.public, url):
        yield 'anonymous', reader, typing.cast('base.PluginContext', None), {}


async def _read[T](
    readers: Readers,
    url: str,
    read: collections.abc.Callable[
        [base.RepositoryReader, base.PluginContext, dict[str, str]],
        collections.abc.Awaitable[T | None],
    ],
    missing: str,
) -> T:
    """Read from a repository through the organization's readers.

    Each integration is tried in turn, then each credential-free reader
    that a plugin offers for ``url``. An integration for another host
    cannot resolve the URL and is skipped. ``read`` returns ``None``
    when the reader cannot find what it reads; then the next reader is
    tried.

    Raises:
        NotFoundError: No reader could read it, and one found nothing.
        SyncError: Every reader failed.

    """
    errors: list[str] = []
    not_found = False
    for label, handler, ctx, credentials in _attempts(readers, url):
        try:
            result = await read(handler, ctx, credentials)
        except NotImplementedError:
            continue
        except Exception as error:  # noqa: BLE001 - try the next one
            LOGGER.info('%s cannot read %s: %s', label, url, error)
            errors.append(f'{label}: {error}')
            continue
        if result is None:
            # Another reader can have access to the repository.
            not_found = True
            errors.append(f'{label}: {missing}')
            continue
        return result
    if not errors:
        raise SyncError(
            'The organization has no integration that can read '
            'repositories (the github plugin)'
        )
    raise (NotFoundError if not_found else SyncError)('; '.join(errors))


async def _public_handlers(
    db: graph.Graph,
) -> list[tuple[str, type[base.DeploymentCapability]]]:
    """Return the deployment handlers of the enabled plugins, by slug."""
    from imbi.api.plugins import lifecycle

    handlers: list[tuple[str, type[base.DeploymentCapability]]] = []
    for entry in plugin_registry.list_plugins():
        capability = entry.manifest.get_capability(_CAPABILITY)
        if capability is None or not await lifecycle.is_plugin_enabled(
            db, entry.manifest.slug
        ):
            continue
        handlers.append(
            (
                entry.manifest.slug,
                typing.cast(
                    'type[base.DeploymentCapability]', capability.handler
                ),
            )
        )
    return handlers


def _public_readers(
    handlers: list[tuple[str, type[base.DeploymentCapability]]], url: str
) -> list[base.RepositoryReader]:
    """Return the credential-free readers that the handlers offer for
    ``url``."""
    readers: list[base.RepositoryReader] = []
    for slug, handler in handlers:
        try:
            reader = handler.public_reader(url)
        except Exception as error:  # noqa: BLE001 - skip this plugin
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
                slug,
                safe_url,
                error,
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


def file_reader(readers: Readers, url: str, ref: str) -> FileReader:
    """Return a reader of the repository files at ``ref``.

    The reader returns ``None`` when a reader of the organization finds
    no such file, and raises :class:`SyncError` when every reader fails.
    """

    async def read(path: str) -> str | None:
        async def get_file(
            handler: base.RepositoryReader,
            ctx: base.PluginContext,
            credentials: dict[str, str],
        ) -> str | None:
            return await handler.get_file(ctx, credentials, path, ref)

        try:
            return await _read(readers, url, get_file, f'{path} not found')
        except NotFoundError:
            return None
        except SyncError as error:
            raise SyncError(f'cannot read {path}: {error}') from error

    return read


async def _resolve(
    readers: Readers, marketplace: dict[str, typing.Any], plugin: CatalogPlugin
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
        plugin.repository_sha = await resolve_commit(readers, plugin)
    except SyncError as error:
        LOGGER.info(
            'Marketplace %s: cannot resolve plugin %s: %s',
            marketplace['slug'],
            plugin.name,
            error,
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
    readers: Readers,
    marketplace: dict[str, typing.Any],
    head_sha: str,
    plugin: CatalogPlugin,
    entry_servers: object,
) -> None:
    """Resolve the commit of a plugin and read its MCP servers.

    As the runner does, an external plugin takes the entry for it from
    the marketplace file of its own repository, never ``entry_servers``.
    """
    await _resolve(readers, marketplace, plugin)
    location = _location(plugin, str(marketplace['url']), head_sha)
    if location is None:
        return
    url, ref, directory = location
    read = file_reader(readers, url, ref)

    async def entry() -> object:
        if plugin.path is not None:
            return entry_servers
        document = _document(await read(MARKETPLACE_FILE))
        return _entry_servers(document, plugin.name)

    plugin.mcp_servers = await plugin_servers(
        read,
        directory,
        entry,
        f'Marketplace {marketplace["slug"]}, plugin {plugin.name}',
    )


async def _sync_plugins(
    readers: Readers,
    marketplace: dict[str, typing.Any],
    head_sha: str,
    catalog: Catalog,
) -> None:
    """Resolve and read each plugin of a catalog, a few at a time.

    Raises:
        SyncError: A file of a plugin could not be read.

    """
    limit = asyncio.Semaphore(_CONCURRENCY)

    async def sync_plugin(plugin: CatalogPlugin) -> None:
        async with limit:
            await _sync_plugin(
                readers,
                marketplace,
                head_sha,
                plugin,
                catalog.entry_servers.get(plugin.name),
            )

    try:
        async with asyncio.TaskGroup() as group:
            for plugin in catalog.plugins:
                group.create_task(sync_plugin(plugin))
    except* SyncError as errors:
        raise errors.exceptions[0] from None


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
        readers = await organization_readers(db, org_slug)
        head = await fetch(readers, str(marketplace['url']))
        catalog = parse(head.text)
        await _sync_plugins(readers, marketplace, head.sha, catalog)
    except SyncError as error:
        changes: dict[str, typing.Any] = {'sync_error': str(error)[:2000]}
    else:
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
