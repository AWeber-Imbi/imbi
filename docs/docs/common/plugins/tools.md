# Tools Capability

!!! warning "Reserved / provisional"
    The `tools` capability kind is **reserved**. Its contract
    (`ToolsCapability`) and the `ToolDescriptor` shape are
    **provisional** — they will be finalized with the agents work. Do not
    build against them yet. Declaring the kind now reserves it and its
    surface so adding it later is not a base-model change.

`ToolsCapability` is the contract base for a capability that exposes
agent-consumable tools to `imbi-assistant` / `imbi-mcp`. Bind it with a
`Capability(kind='tools', handler=...)` in the plugin's manifest.

Surfaces: **tools**.

See [Authoring Plugins](index.md) for the manifest, capabilities,
context, credential decryption, and error conventions shared by every
plugin.

## The tool-catalog contract

Like [webhook-actions](webhook-actions.md), a tools capability advertises
a static catalog rather than implementing a dispatch method. It returns a
list of `ToolDescriptor` from the `tools()` classmethod. Each descriptor
carries a `name`, a `description`, an `input_schema` (JSON Schema for the
tool's arguments), and a `callable` (a `pydantic.ImportString`).

```python
from imbi_common.plugins import (
    ToolDescriptor,
    ToolsCapability,
)


class GitHubTools(ToolsCapability):
    @classmethod
    def tools(cls) -> list[ToolDescriptor]:
        return [
            ToolDescriptor(
                name='open_pull_request',
                description='Open a pull request on the project repo.',
                input_schema={'type': 'object', 'properties': {}},
                callable='imbi_plugin_github.tools:open_pull_request',
            ),
        ]
```

The host validates each descriptor's `callable` at registry load and
enforces unique tool names within a plugin.

## Hints

- **`cacheable`** — the host may cache reads from this capability.

## API reference

::: imbi_common.plugins.ToolsCapability

::: imbi_common.plugins.ToolDescriptor
