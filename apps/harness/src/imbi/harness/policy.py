"""The tool policy of a task (plan section 6.5).

The runner applies it in a ``PreToolUse`` hook, for every tool call,
before the CLI's own permission check (``dontAsk`` with the allowed
tools). :func:`check` is the part that needs no I/O:

1. A built-in tool must be in the allowed tools of the merged
   configuration. An MCP tool ``mcp__<server>__<tool>`` must be in the
   agent's tool map as ``<server>.<tool>``; the harness's own tools of
   the ``imbi`` server are always configured.
2. A tool that declares an ``environment`` argument is refused for an
   environment that its ``environments`` limit does not list. This
   comes before the approval: a person is never asked about a call
   that is refused anyway.
3. A tool needs approval when its ``approval`` is set, or when the
   task origin is not a person and the tool is in ``approval_tools``.
4. A tool with a ``rate_limit`` is counted by imbi-api after the
   approval.
"""

import dataclasses
import typing

#: The tools of the in-process ``imbi`` MCP server.
HARNESS_TOOLS = frozenset(
    {'create_child_task', 'report_outcome', 'request_input', 'run_with_secret'}
)

#: The model must always be able to report the outcome of its task: no
#: deny rule, approval, or rate limit applies to it.
REPORT_OUTCOME = 'mcp__imbi__report_outcome'


@dataclasses.dataclass(frozen=True)
class Check:
    #: The reason slug when the call is refused.
    deny: str | None = None
    approval: bool = False
    #: The tool key that imbi-api counts against its rate limit.
    rate_key: str | None = None


#: CLI server names whose tool map key uses another server name: the
#: Imbi relay is ``imbi_api`` for the CLI (the harness's own server is
#: ``imbi``) and ``imbi`` in the agent tool catalog (plan P7). A task
#: adds its third-party servers whose slug is not a CLI name.
_KEY_SERVER = {'imbi_api': 'imbi'}


def tool_key(name: str, servers: dict[str, str] | None = None) -> str | None:
    """``mcp__<server>__<tool>`` to ``<server>.<tool>``; ``None`` for a
    built-in tool. ``servers`` maps a CLI server name to its key."""
    if not name.startswith('mcp__'):
        return None
    server, _, tool = name.removeprefix('mcp__').partition('__')
    keys = _KEY_SERVER | (servers or {})
    return f'{keys.get(server, server)}.{tool}'


def check(  # noqa: PLR0913 - keyword-only inputs
    name: str,
    arguments: dict[str, typing.Any],
    *,
    allowed: list[str],
    tool_map: dict[str, typing.Any],
    approval_tools: list[str],
    automation: bool,
    servers: dict[str, str] | None = None,
) -> Check:
    if name == REPORT_OUTCOME:
        return Check()
    key = tool_key(name, servers)
    config: dict[str, typing.Any] = {}
    if name.removeprefix('mcp__imbi_api__') in HARNESS_TOOLS:
        # A relayed tool never takes a harness tool's name or config.
        return Check(deny='tool_not_configured')
    if key is None:
        if name not in allowed:
            return Check(deny='tool_not_allowed')
    elif key in tool_map:
        config = tool_map[key] or {}
    elif key.removeprefix('imbi.') not in HARNESS_TOOLS:
        return Check(deny='tool_not_configured')
    environments = config.get('environments')
    if (
        environments is not None
        and 'environment' in arguments
        and arguments['environment'] not in environments
    ):
        return Check(deny='environment_not_allowed')
    return Check(
        approval=bool(config.get('approval'))
        or (automation and bool({name, key} & set(approval_tools))),
        rate_key=key if config.get('rate_limit') else None,
    )
