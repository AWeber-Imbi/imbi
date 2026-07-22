"""Plugin registry — convention + contract discovery, no entry points.

Plugins are discovered three ways, unioned and deduped:

1. **First-party scan** — every subpackage of ``imbi.plugins`` is
   imported and its module-level ``PLUGIN`` attribute (a
   :class:`~imbi.common.plugins.base.Plugin` subclass) is read. Plugin
   code always ships with the ``imbi`` distribution; a plugin whose
   optional dependencies are not installed (see the ``imbi[plugin-*]``
   extras) is recorded as *skipped*, not as an error. Individual
   first-party plugins can be turned off with the
   ``IMBI_PLUGINS_DISABLED`` setting (a list of plugin slugs).
2. **Convention scan** — every installed top-level module named
   ``imbi_plugin_*`` is imported and its module-level ``PLUGIN`` attribute
   is read. This is the third-party packaging convention.
3. **Explicit registration** — the ``IMBI_PLUGINS`` setting (a list of
   dotted import paths, e.g. ``mycorp.imbi.jira:JiraPlugin``) covers
   packages that can't follow the naming convention.

Every discovered plugin is validated against the base-class contracts at
load time (fail-loud): the class must subclass ``Plugin``; its manifest
must be a :class:`PluginManifest` with a supported ``api_version``; every
capability's ``handler`` must subclass the contract for its kind;
``webhook-actions`` / ``tools`` catalogs must enumerate cleanly with
unique names; declared vertex/edge labels must not collide; and plugin
slugs must be unique across packages.
"""

import dataclasses
import importlib
import importlib.metadata
import logging
import pkgutil
import threading
import typing

from imbi.common.plugins.base import (
    CAPABILITY_CONTRACTS,
    ActionDescriptor,
    CapabilityHandler,
    Plugin,
    PluginManifest,
    ToolDescriptor,
    WebhookActionsCapability,
)
from imbi.common.plugins.errors import PluginNotFoundError

LOGGER = logging.getLogger(__name__)

_FIRST_PARTY_PACKAGE = 'imbi.plugins'
_MODULE_PREFIX = 'imbi_plugin_'
_PLUGIN_ATTR = 'PLUGIN'
_SUPPORTED_API_VERSIONS: frozenset[int] = frozenset({2})


@dataclasses.dataclass(frozen=True)
class RegistryEntry:
    plugin_cls: type[Plugin]
    manifest: PluginManifest
    package_name: str
    package_version: str


class LoadResult(typing.NamedTuple):
    loaded: list[str]
    errors: dict[str, str]
    skipped: list[str]


_lock = threading.RLock()
_registry: dict[str, RegistryEntry] = {}


def _package_metadata(module_name: str) -> tuple[str, str]:
    """Map a top-level import name to its distribution name + version."""
    top_level = module_name.split('.', 1)[0]
    try:
        mapping = importlib.metadata.packages_distributions()
    except Exception:  # noqa: BLE001 - defensive; metadata can be flaky
        mapping = {}
    dists = mapping.get(top_level)
    if dists:
        name = dists[0]
        try:
            return name, importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return name, 'unknown'
    return top_level, 'unknown'


def _first_party_version(module_name: str) -> str:
    """Resolve the version for an ``imbi.plugins.*`` module.

    imbi.plugins.<name> ships as the imbi-plugin-<name> dist;
    ``packages_distributions()`` cannot disambiguate the shared imbi
    namespace, so resolve the distribution directly.
    """
    dist_name = 'imbi-plugin-' + module_name.rsplit('.', 1)[-1]
    try:
        return importlib.metadata.version(dist_name)
    except importlib.metadata.PackageNotFoundError:
        return _package_metadata(module_name)[1]


def _discover_first_party() -> dict[str, str]:
    """Return ``{module_name: source_label}`` for ``imbi.plugins.*``."""
    try:
        package = importlib.import_module(_FIRST_PARTY_PACKAGE)
    except ModuleNotFoundError:  # imbi.plugins not importable at all
        return {}
    return {
        f'{_FIRST_PARTY_PACKAGE}.{module.name}': (
            f'{_FIRST_PARTY_PACKAGE}.{module.name}'
        )
        for module in pkgutil.iter_modules(package.__path__)
    }


def _discover_convention() -> dict[str, str]:
    """Return ``{module_name: source_label}`` for ``imbi_plugin_*`` modules."""
    discovered: dict[str, str] = {}
    for module in pkgutil.iter_modules():
        if module.name.startswith(_MODULE_PREFIX):
            discovered[module.name] = module.name
    return discovered


def _load_convention_plugin(module_name: str) -> type[Plugin]:
    """Import ``module_name`` and return its ``PLUGIN`` attribute."""
    module = importlib.import_module(module_name)
    if not hasattr(module, _PLUGIN_ATTR):
        raise ValueError(
            f'Module {module_name!r} has no module-level '
            f'{_PLUGIN_ATTR!r} attribute'
        )
    return typing.cast(type[Plugin], getattr(module, _PLUGIN_ATTR))


def _load_explicit_plugin(dotted_path: str) -> tuple[str, type[Plugin]]:
    """Resolve ``pkg.module:Attr`` to ``(module_name, plugin_cls)``."""
    if ':' not in dotted_path:
        raise ValueError(
            f'IMBI_PLUGINS entry {dotted_path!r} must be of the form '
            "'package.module:Attr'"
        )
    module_name, _, attr = dotted_path.partition(':')
    module = importlib.import_module(module_name)
    if not hasattr(module, attr):
        raise ValueError(f'Module {module_name!r} has no attribute {attr!r}')
    return module_name, typing.cast(type[Plugin], getattr(module, attr))


def _validate_catalog(
    slug: str,
    label: str,
    names: list[str],
) -> str | None:
    """Return an error message for a bad action/tool catalog, or ``None``.

    Warns (but allows) an empty catalog; rejects duplicate names.
    """
    if not names:
        LOGGER.warning(
            'Plugin %r %s catalog is empty; that surface is inert',
            slug,
            label,
        )
        return None
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        return f'Duplicate {label} names: {duplicates}'
    return None


def _validate_plugin(
    source: str,
    cls: object,
    package_version: str,
) -> tuple[RegistryEntry | None, str | None, bool]:
    """Validate one discovered plugin.

    Returns ``(entry, error, skipped)``. Exactly one of ``entry`` /
    ``error`` is set unless ``skipped`` is True (unsupported api_version).
    """
    if not isinstance(cls, type) or not issubclass(cls, Plugin):
        return None, f'{source}: PLUGIN is not a Plugin subclass', False

    manifest = getattr(cls, 'manifest', None)
    if not isinstance(manifest, PluginManifest):
        return None, f'{source}: missing or invalid manifest', False

    if manifest.api_version not in _SUPPORTED_API_VERSIONS:
        LOGGER.warning(
            'Plugin %r declares api_version=%d not in supported versions '
            '%s; skipping',
            manifest.slug,
            manifest.api_version,
            sorted(_SUPPORTED_API_VERSIONS),
        )
        return None, None, True

    # Re-check every capability handler against its contract so a
    # hand-built manifest that bypassed the Capability validator can't
    # slip through, and enumerate webhook-actions / tools catalogs.
    for capability in manifest.capabilities:
        contract = CAPABILITY_CONTRACTS.get(capability.kind)
        if contract is None:
            return (
                None,
                f'{source}: unknown capability kind {capability.kind!r}',
                False,
            )
        if not (
            isinstance(capability.handler, type)
            and issubclass(capability.handler, contract)
        ):
            return (
                None,
                (
                    f'{source}: capability {capability.kind!r} handler '
                    f'{capability.handler!r} does not subclass '
                    f'{contract.__name__}'
                ),
                False,
            )
        if capability.kind == 'webhook-actions':
            error = _validate_action_names(source, capability.handler)
            if error is not None:
                return None, error, False
        if capability.kind == 'tools':
            error = _validate_tool_names(source, capability.handler)
            if error is not None:
                return None, error, False

    entry = RegistryEntry(
        plugin_cls=cls,
        manifest=manifest,
        package_name=source,
        package_version=package_version,
    )
    return entry, None, False


def _validate_action_names(source: str, handler: type) -> str | None:
    handler = typing.cast(type[WebhookActionsCapability], handler)
    try:
        descriptors = handler.actions()
    except Exception as exc:  # noqa: BLE001 - report as a load error
        return f'{source}: actions() raised: {exc}'
    if not isinstance(descriptors, list) or any(
        not isinstance(d, ActionDescriptor) for d in descriptors
    ):
        return f'{source}: actions() must return list[ActionDescriptor]'
    return _validate_catalog(source, 'action', [d.name for d in descriptors])


def _validate_tool_names(source: str, handler: type) -> str | None:
    try:
        descriptors = handler.tools()  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 - report as a load error
        return f'{source}: tools() raised: {exc}'
    if not isinstance(descriptors, list) or any(
        not isinstance(d, ToolDescriptor) for d in descriptors
    ):
        return f'{source}: tools() must return list[ToolDescriptor]'
    return _validate_catalog(source, 'tool', [d.name for d in descriptors])


def load_plugins() -> LoadResult:
    """Discover, validate, and load all installed imbi plugins."""
    from imbi.common import settings

    plugin_settings = settings.Plugins()
    disabled = set(plugin_settings.imbi_plugins_disabled)

    loaded: list[str] = []
    errors: dict[str, str] = {}
    skipped: list[str] = []
    new_registry: dict[str, RegistryEntry] = {}
    seen_ids: set[int] = set()

    def _register(source: str, cls: object, version: str) -> None:
        if id(cls) in seen_ids:
            return
        entry, error, was_skipped = _validate_plugin(source, cls, version)
        if was_skipped:
            skipped.append(source)
            return
        if error is not None:
            LOGGER.error('Plugin load failed: %s', error)
            errors[source] = error
            return
        if entry is None:  # unreachable: entry set when no error / skip
            return
        if entry.manifest.slug in disabled:
            LOGGER.info(
                'Plugin %r disabled via IMBI_PLUGINS_DISABLED; skipping',
                entry.manifest.slug,
            )
            skipped.append(source)
            return
        seen_ids.add(id(cls))
        if entry.manifest.slug in new_registry:
            msg = f'{source}: duplicate plugin slug {entry.manifest.slug!r}'
            LOGGER.error(msg)
            errors[source] = msg
            return
        new_registry[entry.manifest.slug] = entry
        loaded.append(entry.manifest.slug)
        LOGGER.info(
            'Loaded plugin %r v%s (slug=%r, capabilities=%s)',
            entry.package_name,
            entry.package_version,
            entry.manifest.slug,
            [c.kind for c in entry.manifest.capabilities],
        )

    for module_name, source in _discover_first_party().items():
        try:
            cls = _load_convention_plugin(module_name)
        except ImportError as exc:
            # First-party plugin code is workspace-editable in dev; a
            # missing optional dependency means the plugin's
            # distribution is not installed, which is a normal
            # deployment state.
            LOGGER.debug(
                'Skipping first-party plugin %r: %s (install the matching '
                'imbi-plugin-* distribution to enable it)',
                module_name,
                exc,
            )
            skipped.append(source)
            continue
        except Exception as exc:
            LOGGER.exception('Failed to import plugin %r', module_name)
            errors[source] = str(exc)
            continue
        _register(source, cls, _first_party_version(module_name))

    for module_name, source in _discover_convention().items():
        try:
            cls = _load_convention_plugin(module_name)
        except Exception as exc:
            LOGGER.exception('Failed to import plugin %r', module_name)
            errors[source] = str(exc)
            continue
        _register(source, cls, _package_metadata(module_name)[1])

    for dotted_path in plugin_settings.imbi_plugins:
        try:
            module_name, cls = _load_explicit_plugin(dotted_path)
        except Exception as exc:
            LOGGER.exception('Failed to import IMBI_PLUGINS %r', dotted_path)
            errors[dotted_path] = str(exc)
            continue
        _register(dotted_path, cls, _package_metadata(module_name)[1])

    # Refuse vlabel/edge collisions across loaded plugins or with core
    # schemata.  Imported lazily to avoid a circular import.
    from imbi.common.plugins.schemas import validate_no_collisions

    validate_no_collisions([entry.manifest for entry in new_registry.values()])

    with _lock:
        _registry.clear()
        _registry.update(new_registry)

    return LoadResult(loaded=loaded, errors=errors, skipped=skipped)


def reload_plugins() -> LoadResult:
    """Reload the plugin registry from installed packages."""
    LOGGER.info('Reloading plugin registry')
    return load_plugins()


def get_plugin(slug: str) -> RegistryEntry:
    """Get a registry entry by plugin slug.

    Raises:
        PluginNotFoundError: If the slug is not registered.
    """
    with _lock:
        entry = _registry.get(slug)
    if entry is None:
        raise PluginNotFoundError(slug)
    return entry


def get_capability(slug: str, kind: str) -> type[CapabilityHandler]:
    """Return the handler class for ``kind`` on plugin ``slug``.

    Raises:
        PluginNotFoundError: If the slug is not registered or the plugin
            declares no capability of ``kind``.
    """
    entry = get_plugin(slug)
    capability = entry.manifest.get_capability(kind)
    if capability is None:
        raise PluginNotFoundError(f'{slug}:{kind}')
    return typing.cast(type[CapabilityHandler], capability.handler)


def list_plugins() -> list[RegistryEntry]:
    """Return all registered plugins."""
    with _lock:
        return list(_registry.values())
