"""The agent platform configuration of an organization (ADR 0022).

The organization sets the base Agent SDK configuration and its limits.
An agent can only narrow them (plan section 5.1):

- :func:`widenings` lists what an agent's settings try to widen. A save
  that widens a limit is refused with 422.
- :func:`merge` applies the agent's settings over a pinned
  configuration. It always takes the stricter value, so an agent that
  was valid under an older configuration cannot widen a newer one.
- :func:`pin_plugins` pins each plugin to the marketplace commit that
  the catalog holds now.
"""

import typing

import pydantic

from imbi.api.harness import store as harness_store
from imbi.api.secret_broker import broker, providers
from imbi.common import models


class ModelUpstream(pydantic.BaseModel):
    """Where the runner's model proxy sends model calls."""

    kind: typing.Literal['anthropic', 'litellm'] = 'anthropic'
    #: The upstream base URL. ``None`` is the Anthropic API.
    base_url: pydantic.HttpUrl | None = None
    #: The ``secret://`` reference of the upstream key.
    key_ref: str | None = None

    @pydantic.field_validator('key_ref')
    @classmethod
    def _check_key_ref(cls, value: str | None) -> str | None:
        if value is not None:
            check_reference(value)
        return value


class AgentPlatformConfig(pydantic.BaseModel):
    """The base agent configuration of an organization."""

    model_upstream: ModelUpstream = pydantic.Field(
        default_factory=ModelUpstream
    )
    #: Slugs of registered marketplaces. Agents select plugins from
    #: these only.
    allowed_marketplaces: list[str] = []
    #: Plugins that every agent gets. Imbi pins them on each write.
    default_plugins: list[models.AgentPlugin] = []
    #: Built-in tools (``Bash``, ``Edit``, ...). ``None`` allows all.
    allowed_tools: list[str] | None = None
    denied_tools: list[str] = []
    permission_mode: models.AgentPermissionMode = 'default'
    sandbox: models.AgentSandbox = pydantic.Field(
        default_factory=models.AgentSandbox
    )
    #: Put before the agent's own system prompt.
    system_prompt_prefix: str = ''
    #: Agent SDK hooks (audit, policy). Agents cannot change them.
    hooks: dict[str, typing.Any] = {}
    #: Tools that need approval when the task origin is an automation.
    approval_tools: list[str] = []

    @pydantic.field_validator(
        'allowed_marketplaces', 'denied_tools', 'approval_tools'
    )
    @classmethod
    def _sort(cls, value: list[str]) -> list[str]:
        return sorted(set(value))

    @pydantic.field_validator('allowed_tools')
    @classmethod
    def _sort_allowed(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else sorted(set(value))


class MergedConfig(pydantic.BaseModel):
    """The configuration that a runner applies to one task."""

    model_upstream: ModelUpstream
    plugins: list[models.AgentPlugin]
    allowed_tools: list[str] | None
    denied_tools: list[str]
    permission_mode: models.AgentPermissionMode
    sandbox: models.AgentSandbox
    system_prompt_prefix: str
    hooks: dict[str, typing.Any]
    approval_tools: list[str]
    secrets: list[str]
    github_app_binding: str | None


def check_reference(value: str, *, field: bool = True) -> None:
    """Raise :class:`ValueError` when ``value`` is not a reference.

    With ``field`` false, a ``#field`` suffix is refused too, as for the
    reference of a binding.
    """
    try:
        broker.parse_reference(value, field=field)
    except providers.BrokerError as err:
        raise ValueError(f'Invalid secret reference {value!r}') from err


def _strictness(mode: str) -> int:
    return models.AGENT_PERMISSION_MODES.index(mode)


def widenings(
    config: AgentPlatformConfig, settings: models.AgentSettings
) -> list[str]:
    """Return what ``settings`` try to widen in ``config``."""
    problems: list[str] = []
    if settings.permission_mode is not None and _strictness(
        settings.permission_mode
    ) > _strictness(config.permission_mode):
        problems.append(
            f'permission_mode {settings.permission_mode!r} is less strict '
            f'than the organization mode {config.permission_mode!r}'
        )
    if settings.sandbox is not None:
        if config.sandbox.enabled and not settings.sandbox.enabled:
            problems.append('the organization requires the sandbox')
        if (
            settings.sandbox.allow_unsandboxed_commands
            and not config.sandbox.allow_unsandboxed_commands
        ):
            problems.append(
                'the organization does not allow unsandboxed commands'
            )
    allowed = set(config.allowed_marketplaces)
    for plugin in settings.plugins:
        if plugin.marketplace not in allowed:
            problems.append(
                f'marketplace {plugin.marketplace!r} is not allowed'
            )
    return problems


def merge(
    config: AgentPlatformConfig, settings: models.AgentSettings
) -> MergedConfig:
    """Apply the agent's ``settings`` over ``config``.

    Each value is the stricter of the two. An agent plugin from a
    marketplace that ``config`` does not allow is left out. A default
    plugin wins over an agent plugin with the same name.
    """
    mode = config.permission_mode
    if settings.permission_mode is not None and _strictness(
        settings.permission_mode
    ) < _strictness(mode):
        mode = settings.permission_mode
    sandbox = config.sandbox
    if settings.sandbox is not None:
        sandbox = models.AgentSandbox(
            enabled=sandbox.enabled or settings.sandbox.enabled,
            allow_unsandboxed_commands=(
                sandbox.allow_unsandboxed_commands
                and settings.sandbox.allow_unsandboxed_commands
            ),
        )
    plugins = list(config.default_plugins)
    seen = {(p.marketplace, p.plugin) for p in plugins}
    allowed = set(config.allowed_marketplaces)
    for plugin in settings.plugins:
        key = (plugin.marketplace, plugin.plugin)
        if plugin.marketplace in allowed and key not in seen:
            plugins.append(plugin)
            seen.add(key)
    return MergedConfig(
        model_upstream=config.model_upstream,
        plugins=plugins,
        allowed_tools=config.allowed_tools,
        denied_tools=sorted({*config.denied_tools, *settings.denied_tools}),
        permission_mode=mode,
        sandbox=sandbox,
        system_prompt_prefix=config.system_prompt_prefix,
        hooks=config.hooks,
        approval_tools=sorted(
            {*config.approval_tools, *settings.approval_tools}
        ),
        secrets=settings.secrets,
        github_app_binding=settings.github_app_binding,
    )


def pin_plugins(
    requested: list[models.AgentPlugin],
    current: list[models.AgentPlugin],
    marketplaces: dict[str, dict[str, typing.Any]],
) -> list[models.AgentPlugin]:
    """Pin each requested plugin to a marketplace commit.

    A plugin that ``current`` pins, and that the request gives with the
    same ``sha``, keeps its pin. Any other plugin is pinned to the
    commit of the synced catalog. Omit ``sha`` to pin a plugin again.
    ``marketplaces`` are the marketplace rows of the organization, by
    slug.

    Raises:
        ValueError: A plugin is given two times, or its marketplace or
            catalog entry is missing, or its source is outside the
            marketplace repository.

    """
    pinned = {(p.marketplace, p.plugin): p for p in current}
    out: list[models.AgentPlugin] = []
    seen: set[tuple[str, str]] = set()
    for plugin in requested:
        key = (plugin.marketplace, plugin.plugin)
        if key in seen:
            raise ValueError(
                f'Plugin {plugin.plugin}@{plugin.marketplace} is given '
                'two times'
            )
        seen.add(key)
        existing = pinned.get(key)
        if (
            existing is not None
            and plugin.sha is not None
            and plugin.sha == existing.sha
        ):
            out.append(existing)
            continue
        out.append(_pin(plugin, marketplaces.get(plugin.marketplace)))
    return out


def _pin(
    plugin: models.AgentPlugin, marketplace: dict[str, typing.Any] | None
) -> models.AgentPlugin:
    name = f'{plugin.plugin}@{plugin.marketplace}'
    if marketplace is None:
        raise ValueError(f'Marketplace {plugin.marketplace!r} not found')
    if not marketplace.get('head_sha'):
        raise ValueError(
            f'Marketplace {plugin.marketplace!r} has not synced yet'
        )
    entry = next(
        (p for p in marketplace['plugins'] if p['name'] == plugin.plugin),
        None,
    )
    if entry is None:
        raise ValueError(f'Plugin {name} is not in the marketplace catalog')
    if entry.get('path') is None:
        # ponytail: rev 1 runners clone only the marketplace; support
        # github/url/git-subdir sources when a runner clones them too.
        raise ValueError(
            f'Plugin {name} is outside the marketplace repository; '
            'runners load only plugins inside it'
        )
    return models.AgentPlugin(
        marketplace=plugin.marketplace,
        plugin=plugin.plugin,
        url=marketplace['url'],
        sha=marketplace['head_sha'],
        path=entry['path'],
    )


async def load(
    store: harness_store.HarnessStore,
    organization_id: str,
    version: int | None = None,
) -> tuple[int | None, AgentPlatformConfig]:
    """Return a configuration version and the configuration.

    ``version`` ``None`` is the newest. An organization with no
    configuration gets version ``None`` and the defaults.
    """
    row = await store.platform_config(organization_id, version)
    if row is None:
        return None, AgentPlatformConfig()
    return int(row['version']), AgentPlatformConfig.model_validate(
        row['config']
    )
