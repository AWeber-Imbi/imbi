"""Plugin registry — discovery, loading, and reload."""

import dataclasses
import importlib.metadata
import logging
import threading
import typing

from imbi_common.plugins.base import (
    ActionDescriptor,
    ConfigurationPlugin,
    DeploymentPlugin,
    IdentityPlugin,
    LifecyclePlugin,
    LogsPlugin,
    PluginManifest,
    WebhookActionPlugin,
)
from imbi_common.plugins.errors import PluginNotFoundError

LOGGER = logging.getLogger(__name__)

_ENTRY_POINT_GROUP = 'imbi.plugins'
_SUPPORTED_API_VERSIONS: frozenset[int] = frozenset({1})

PluginHandler = (
    ConfigurationPlugin
    | LogsPlugin
    | IdentityPlugin
    | DeploymentPlugin
    | LifecyclePlugin
    | WebhookActionPlugin
)


@dataclasses.dataclass(frozen=True)
class RegistryEntry:
    handler_cls: (
        type[ConfigurationPlugin]
        | type[LogsPlugin]
        | type[IdentityPlugin]
        | type[DeploymentPlugin]
        | type[LifecyclePlugin]
        | type[WebhookActionPlugin]
    )
    manifest: PluginManifest
    package_name: str
    package_version: str


class LoadResult(typing.NamedTuple):
    loaded: list[str]
    errors: dict[str, str]
    skipped: list[str]


_lock = threading.RLock()
_registry: dict[str, RegistryEntry] = {}


_PLUGIN_TYPE_BASES: dict[
    str,
    type[ConfigurationPlugin]
    | type[LogsPlugin]
    | type[IdentityPlugin]
    | type[DeploymentPlugin]
    | type[LifecyclePlugin]
    | type[WebhookActionPlugin],
] = {
    'configuration': ConfigurationPlugin,
    'logs': LogsPlugin,
    'identity': IdentityPlugin,
    'deployment': DeploymentPlugin,
    'lifecycle': LifecyclePlugin,
    'webhook': WebhookActionPlugin,
}


def _validate_action_catalog(
    ep_name: str, descriptors: list[ActionDescriptor]
) -> str | None:
    """Return an error message describing a bad action catalog, or ``None``.

    Logs a warning for plugins that advertise no actions (the plugin is
    inert but still loadable). Rejects plugins with duplicate action
    names within a single catalog.
    """
    if not descriptors:
        LOGGER.warning(
            'Webhook plugin %r exposes no actions; the plugin is inert',
            ep_name,
        )
        return None
    seen: set[str] = set()
    duplicates: list[str] = []
    for descriptor in descriptors:
        if descriptor.name in seen:
            duplicates.append(descriptor.name)
        else:
            seen.add(descriptor.name)
    if duplicates:
        return (
            f'Duplicate action names within plugin: {sorted(set(duplicates))}'
        )
    return None


def load_plugins() -> LoadResult:
    """Discover and load all installed imbi plugins."""
    loaded: list[str] = []
    errors: dict[str, str] = {}
    skipped: list[str] = []
    new_registry: dict[str, RegistryEntry] = {}

    for ep in importlib.metadata.entry_points(group=_ENTRY_POINT_GROUP):
        try:
            cls = ep.load()
        except Exception as exc:
            LOGGER.exception('Failed to load plugin %r: %s', ep.name, exc)
            errors[ep.name] = str(exc)
            continue

        if not hasattr(cls, 'manifest') or not isinstance(
            cls.manifest, PluginManifest
        ):
            LOGGER.error(
                'Plugin %r has no valid manifest attribute; skipping',
                ep.name,
            )
            errors[ep.name] = 'Missing or invalid manifest attribute'
            continue

        manifest: PluginManifest = cls.manifest

        if not isinstance(cls, type) or not issubclass(
            cls,
            (
                ConfigurationPlugin,
                LogsPlugin,
                IdentityPlugin,
                DeploymentPlugin,
                LifecyclePlugin,
                WebhookActionPlugin,
            ),
        ):
            LOGGER.error(
                'Plugin %r does not implement ConfigurationPlugin, '
                'LogsPlugin, IdentityPlugin, DeploymentPlugin, '
                'LifecyclePlugin, or WebhookActionPlugin; skipping',
                ep.name,
            )
            errors[ep.name] = (
                'Plugin must subclass ConfigurationPlugin, LogsPlugin, '
                'IdentityPlugin, DeploymentPlugin, LifecyclePlugin, or '
                'WebhookActionPlugin'
            )
            continue

        expected_base = _PLUGIN_TYPE_BASES[manifest.plugin_type]
        if not issubclass(cls, expected_base):  # pyright: ignore[reportUnnecessaryIsInstance]
            LOGGER.error(
                'Plugin %r manifest plugin_type=%r does not match class '
                'hierarchy; skipping',
                ep.name,
                manifest.plugin_type,
            )
            errors[ep.name] = (
                f'Class does not implement {expected_base.__name__} '
                f'for plugin_type={manifest.plugin_type!r}'
            )
            continue

        if manifest.api_version not in _SUPPORTED_API_VERSIONS:
            LOGGER.warning(
                'Plugin %r declares api_version=%d not in supported '
                'versions %s; skipping',
                ep.name,
                manifest.api_version,
                sorted(_SUPPORTED_API_VERSIONS),
            )
            skipped.append(ep.name)
            continue

        if issubclass(cls, WebhookActionPlugin):
            try:
                descriptors = cls.actions()
            except Exception as exc:
                LOGGER.exception(
                    'Plugin %r failed to enumerate actions: %s',
                    ep.name,
                    exc,
                )
                errors[ep.name] = f'actions() raised: {exc}'
                continue
            if not isinstance(descriptors, list) or any(
                not isinstance(descriptor, ActionDescriptor)
                for descriptor in descriptors
            ):
                LOGGER.error(
                    'Plugin %r actions() did not return '
                    'list[ActionDescriptor]; skipping',
                    ep.name,
                )
                errors[ep.name] = (
                    'actions() must return list[ActionDescriptor]'
                )
                continue
            action_error = _validate_action_catalog(ep.name, descriptors)
            if action_error is not None:
                errors[ep.name] = action_error
                continue

        dist = ep.dist
        pkg_name = dist.name if dist else 'unknown'
        pkg_version = dist.version if dist else 'unknown'

        entry = RegistryEntry(
            handler_cls=cls,
            manifest=manifest,
            package_name=pkg_name,
            package_version=pkg_version,
        )
        if manifest.slug in new_registry:
            LOGGER.error(
                'Duplicate plugin slug %r from entry point %r; skipping',
                manifest.slug,
                ep.name,
            )
            errors[ep.name] = f'Duplicate plugin slug: {manifest.slug}'
            continue
        new_registry[manifest.slug] = entry
        LOGGER.info(
            'Loaded plugin %r v%s (slug=%r, api_version=%d)',
            pkg_name,
            pkg_version,
            manifest.slug,
            manifest.api_version,
        )
        loaded.append(manifest.slug)

    # Refuse vlabel/edge collisions across loaded plugins or with core
    # schemata.  Imported lazily to avoid a circular import.
    from imbi_common.plugins.schemas import validate_no_collisions

    validate_no_collisions([entry.manifest for entry in new_registry.values()])

    with _lock:
        _registry.clear()
        _registry.update(new_registry)

    return LoadResult(loaded=loaded, errors=errors, skipped=skipped)


def reload_plugins() -> LoadResult:
    """Reload the plugin registry from installed entry points."""
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


def list_plugins() -> list[RegistryEntry]:
    """Return all registered plugins."""
    with _lock:
        return list(_registry.values())
