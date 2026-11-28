"""The agent platform configuration of an organization (ADR 0022).

The organization sets the base Agent SDK configuration and its limits.
An agent can only narrow them (plan section 5.1):

- :func:`widenings` lists what an agent's settings try to widen, and
  each enforced ``claude_settings`` path that they set. A save with one
  is refused with 422.
- :func:`merge` applies the agent's settings over a pinned
  configuration. It always takes the stricter value, so an agent that
  was valid under an older configuration cannot widen a newer one.
- :func:`pin_plugins` pins each plugin to the marketplace commit that
  the catalog holds now.
"""

import collections.abc
import typing
import urllib.parse

import pydantic

from imbi.api.harness import store as harness_store
from imbi.api.secret_broker import broker, model_key, providers
from imbi.common import models
from imbi.common.llm import drivers


class ModelUpstream(pydantic.BaseModel):
    """Where the runner's model proxy sends model calls. imbi-api derives
    it from the AI provider of the task (ADR 0022 amendment)."""

    kind: typing.Literal['anthropic', 'litellm'] = 'anthropic'
    #: The upstream base URL. ``None`` is the Anthropic API.
    base_url: str | None = None
    #: The ``allow_insecure_http`` of the AI provider: the runner sends
    #: the key to an ``http://`` base URL only with it.
    allow_insecure_http: bool = False
    #: The ``secret://`` reference of the upstream key.
    key_ref: str | None = None


def upstream(provider: models.AIProvider) -> ModelUpstream:
    """Return the model upstream of an AI provider: the Anthropic
    Messages API of an ``anthropic`` provider, or a gateway that speaks
    it (``openai_compatible``, with a bearer key, at the root of its
    URL)."""
    base_url = drivers.resolve_base_url(provider.driver, provider.base_url)
    if provider.driver != 'anthropic' and base_url is not None:
        # An OpenAI style base URL ends in /v1; the proxy adds
        # /v1/messages itself.
        base_url = base_url.removesuffix('/v1')
    return ModelUpstream(
        kind='anthropic' if provider.driver == 'anthropic' else 'litellm',
        base_url=base_url,
        allow_insecure_http=provider.allow_insecure_http,
        key_ref=model_key.REFERENCE,
    )


class AgentPlatformConfig(pydantic.BaseModel):
    """The base agent configuration of an organization."""

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
    #: Tools that need approval when the task origin is an automation.
    approval_tools: list[str] = []
    #: Claude Code settings for every agent. An agent can replace each
    #: path that is not in ``enforced``.
    claude_settings: models.ClaudeSettings = pydantic.Field(
        default_factory=models.ClaudeSettings
    )
    #: The ``claude_settings`` paths that an agent cannot set.
    enforced: list[models.ClaudeSettingsPath] = []
    #: Let agents set ``claude_settings.hooks``. A command hook runs a
    #: shell command outside the tool map, the sandbox, the approvals,
    #: and plan mode, so it is off unless the organization opts in.
    allow_agent_hooks: bool = False

    @pydantic.model_validator(mode='before')
    @classmethod
    def _move_hooks(cls, data: object) -> object:
        """Read the ``hooks`` field of an older version as enforced
        ``claude_settings.hooks``: the UI said that agents cannot
        change them."""
        if not isinstance(data, dict):
            return data
        moved = dict(typing.cast('dict[str, typing.Any]', data))
        if 'hooks' not in moved:
            return moved
        hooks = moved.pop('hooks')
        if hooks and not moved.get('claude_settings'):
            moved['claude_settings'] = {'hooks': hooks}
            moved['enforced'] = sorted({*moved.get('enforced', []), 'hooks'})
        return moved

    @pydantic.field_validator(
        'allowed_marketplaces', 'denied_tools', 'approval_tools', 'enforced'
    )
    @classmethod
    def _sort(cls, value: list[str]) -> list[str]:
        return sorted(set(value))

    @pydantic.field_validator('allowed_tools')
    @classmethod
    def _sort_allowed(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else sorted(set(value))


class SecretReference(pydantic.BaseModel):
    """A secret reference that the agent may request, with the hints of
    its binding and the purposes of its grants for the model. Names
    only, never a value."""

    reference: str
    description: str = ''
    allowed_fields: list[str] = []
    purposes: list[str] = []


class MergedConfig(pydantic.BaseModel):
    """The configuration that a runner applies to one task."""

    #: ``None`` only from :func:`merge`: the claim sets it.
    model_upstream: ModelUpstream | None = None
    plugins: list[models.AgentPlugin]
    #: The organization's built-in tools, less the opt-in tools that
    #: the agent did not turn on.
    #: ``None`` allows all of the runner's default built-in tools.
    allowed_tools: list[str] | None
    denied_tools: list[str]
    #: The opt-in built-in tools (``Skill``, ``Agent``) that the agent
    #: turned on in its tool map, inside ``allowed_tools`` and not in
    #: ``denied_tools``.
    builtin_tools: list[str] = []
    permission_mode: models.AgentPermissionMode
    sandbox: models.AgentSandbox
    system_prompt_prefix: str
    #: ``claude_settings.hooks``, for runners that do not read
    #: ``claude_settings`` (2.45 and older).
    hooks: dict[str, typing.Any]
    approval_tools: list[str]
    secrets: list[SecretReference]
    github_app_binding: str | None
    #: The organization settings with the agent's paths over them.
    claude_settings: dict[str, typing.Any] = {}
    #: The agent paths that the organization enforces: left out.
    claude_settings_dropped: list[str] = []


def check_reference(value: str, *, field: bool = True) -> None:
    """Raise :class:`ValueError` when ``value`` is not a reference.

    With ``field`` false, a ``#field`` suffix is refused too, as for the
    reference of a binding.
    """
    try:
        broker.parse_reference(value, field=field)
    except providers.BrokerError as err:
        raise ValueError(f'Invalid secret reference {value!r}') from err


def _is_origin(value: str) -> bool:
    """Return true when ``value`` is an ``https`` origin, written as
    ``https://host[:port]`` in lower case and with nothing else."""
    parts = urllib.parse.urlsplit(value)
    try:
        port = parts.port
    except ValueError:
        return False
    host = parts.hostname
    if parts.scheme != 'https' or not host:
        return False
    netloc = f'[{host}]' if ':' in host else host
    if port is not None:
        netloc = f'{netloc}:{port}'
    return value == f'https://{netloc}'


def check_server_secrets(plugin: models.AgentPlugin) -> None:
    """Raise :class:`ValueError` when ``plugin`` maps a header variable
    of an MCP server that the runner cannot relay.

    Each reference must parse, the setting must have an ``https``
    origin, and the pinned server must be an ``http`` or ``sse`` server
    with a URL and a header that uses the variable. The origin can
    differ from the origin of the server URL: the runner refuses to
    relay that server, and the UI asks for the secrets again.
    """
    servers = {server.name: server for server in plugin.mcp_servers}
    owner = f'{plugin.plugin}@{plugin.marketplace}'
    for name, setting in plugin.server_settings.items():
        if setting.secrets:
            _check_server(
                f'MCP server {name!r} of {owner}', setting, servers.get(name)
            )


def _check_server(
    label: str,
    setting: models.ServerSetting,
    server: models.CatalogServer | None,
) -> None:
    for reference in setting.secrets.values():
        check_reference(reference)
    if setting.origin is None or not _is_origin(setting.origin):
        raise ValueError(
            f'The {label} needs an origin such as https://host[:port]'
        )
    if server is None or server.type not in {'http', 'sse'} or not server.url:
        raise ValueError(
            f'The {label} is not an http or sse server with a URL in the '
            'pinned plugin'
        )
    unknown = sorted(set(setting.secrets) - _variables(server))
    if unknown:
        raise ValueError(
            f'The {label} has no header variables {", ".join(unknown)}'
        )


def _variables(server: models.CatalogServer) -> set[str]:
    return {name for names in server.headers.values() for name in names}


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
    problems.extend(
        f'the organization enforces claude_settings {path!r}'
        if path in config.enforced
        else 'the organization does not allow agent claude_settings hooks'
        for path in _enforced(config, settings)
    )
    return problems


def _enforced(
    config: AgentPlatformConfig, settings: models.AgentSettings
) -> list[str]:
    """The paths that the agent sets and cannot: the organization
    enforces them, or they are hooks and the organization does not
    allow agent hooks."""
    enforced = set(config.enforced)
    if not config.allow_agent_hooks:
        enforced.add('hooks')
    return sorted(set(settings.claude_settings.paths()) & enforced)


def merge(
    config: AgentPlatformConfig,
    settings: models.AgentSettings,
    tools: collections.abc.Collection[str] = (),
) -> MergedConfig:
    """Apply the agent's ``settings`` and tool map keys ``tools`` over
    ``config``.

    Each value is the stricter of the two. An agent plugin from a
    marketplace that ``config`` does not allow is left out. A default
    plugin wins over an agent plugin with the same name, and takes the
    agent plugin's ``server_settings``, less those that its pin does
    not list (:func:`pin_plugins`). The agent's model key replaces
    the key of the organization's model upstream.

    ``claude_settings`` is the exception: each path that the agent sets
    replaces the organization's value, a list too, unless the
    organization enforces the path (settings plan 4.4).

    An opt-in built-in tool is on only when ``tools`` has its key: the
    organization's ``allowed_tools`` is its ceiling, not its switch.
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
    overrides = {
        (p.marketplace, p.plugin): p.server_settings for p in settings.plugins
    }
    plugins = [
        plugin.model_copy(
            update={
                'server_settings': _for_pin(
                    overrides.get((plugin.marketplace, plugin.plugin), {}),
                    plugin,
                )
            }
        )
        for plugin in config.default_plugins
    ]
    seen = {(p.marketplace, p.plugin) for p in plugins}
    allowed = set(config.allowed_marketplaces)
    for plugin in settings.plugins:
        key = (plugin.marketplace, plugin.plugin)
        if plugin.marketplace in allowed and key not in seen:
            plugins.append(plugin)
            seen.add(key)
    dropped = _enforced(config, settings)
    agent = settings.claude_settings.paths()
    for path in dropped:
        del agent[path]
    paths = config.claude_settings.paths() | agent
    claude = models.ClaudeSettings.document(paths)
    denied = sorted({*config.denied_tools, *settings.denied_tools})
    builtin = models.opt_in_builtin_tools(tools, config.allowed_tools, denied)
    # allowed_tools keeps the opt-in tools that the agent turned on, so a
    # runner that does not read builtin_tools still gets them.
    off = {
        name
        for tool in models.OPT_IN_BUILTIN_TOOLS.values()
        if tool.name not in builtin
        for name in tool.names
    }
    return MergedConfig(
        plugins=plugins,
        allowed_tools=(
            None
            if config.allowed_tools is None
            else [t for t in config.allowed_tools if t not in off]
        ),
        denied_tools=denied,
        builtin_tools=builtin,
        permission_mode=mode,
        sandbox=sandbox,
        system_prompt_prefix=config.system_prompt_prefix,
        hooks=claude.get('hooks', {}),
        approval_tools=sorted(
            {*config.approval_tools, *settings.approval_tools}
        ),
        secrets=[SecretReference(reference=r) for r in settings.secrets],
        github_app_binding=settings.github_app_binding,
        claude_settings=claude,
        claude_settings_dropped=dropped,
    )


def pin_plugins(
    requested: list[models.AgentPlugin],
    current: list[models.AgentPlugin],
    marketplaces: dict[str, dict[str, typing.Any]],
    defaults: list[models.AgentPlugin] | None = None,
) -> list[models.AgentPlugin]:
    """Pin each requested plugin to a marketplace commit.

    A plugin of ``defaults``, the organization's default plugins, gets
    the default's pin. A plugin that ``current`` pins, and that the
    request gives with the same ``sha``, keeps its pin. Any other
    plugin is pinned to the commit of the synced catalog. Omit ``sha``
    to pin a plugin again. ``marketplaces`` are the marketplace rows of
    the organization, by slug.

    Each plugin keeps the requested ``server_settings``. A new pin, and
    a default's pin that lists its servers, drop the settings of the
    servers that the pin does not list, and the secrets of the header
    variables that it does not list.

    Raises:
        ValueError: A plugin is given two times, or its marketplace or
            catalog entry is missing, or its source cannot be loaded.

    """
    pinned = {(p.marketplace, p.plugin): p for p in current}
    default_pins = {(p.marketplace, p.plugin): p for p in defaults or []}
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
        default = default_pins.get(key)
        existing = pinned.get(key)
        if default is not None:
            pin = default
            settings = _for_pin(plugin.server_settings, default)
        elif (
            existing is not None
            and plugin.sha is not None
            and plugin.sha == existing.sha
        ):
            pin = existing
            settings = plugin.server_settings
        else:
            pin = _pin(plugin, marketplaces.get(plugin.marketplace))
            settings = _listed(plugin.server_settings, pin.mcp_servers)
        out.append(pin.model_copy(update={'server_settings': settings}))
    return out


def _for_pin(
    settings: dict[str, models.ServerSetting], pin: models.AgentPlugin
) -> dict[str, models.ServerSetting]:
    """The ``settings`` that a default ``pin`` can take: all of them
    when the pin saved no servers."""
    return _listed(settings, pin.mcp_servers) if pin.mcp_servers else settings


def _listed(
    settings: dict[str, models.ServerSetting],
    servers: list[models.CatalogServer],
) -> dict[str, models.ServerSetting]:
    """The ``settings`` of the servers that ``servers`` lists, with the
    secrets of the header variables that each server uses."""
    variables = {server.name: _variables(server) for server in servers}
    listed = {
        name: value.model_copy(
            update={
                'secrets': {
                    variable: reference
                    for variable, reference in value.secrets.items()
                    if variable in variables[name]
                }
            }
        )
        for name, value in settings.items()
        if name in variables
    }
    return {
        name: value for name, value in listed.items() if not value.is_default()
    }


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
        # A url or github source: pin the plugin's own repository.
        if not entry.get('repository_url') or not entry.get('repository_sha'):
            raise ValueError(
                f'Plugin {name} has a source that runners cannot load, or '
                'its commit was not resolved at the last sync'
            )
        return models.AgentPlugin(
            marketplace=plugin.marketplace,
            plugin=plugin.plugin,
            url=entry['repository_url'],
            sha=entry['repository_sha'],
            path='.',
            mcp_servers=entry.get('mcp_servers') or [],
        )
    return models.AgentPlugin(
        marketplace=plugin.marketplace,
        plugin=plugin.plugin,
        url=marketplace['url'],
        sha=marketplace['head_sha'],
        path=entry['path'],
        mcp_servers=entry.get('mcp_servers') or [],
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
