# Prompts

The `imbi.common.prompts` package holds the prompt CMS code that
`imbi-api` and the prompt consumers share. A consumer is a service that
reads its system prompt from the CMS, such as `imbi-assistant` and
`imbi-slackbot`. For the operator view of the CMS, see
[Prompts](../../admin/prompts.md).

| Module | What it does |
|---|---|
| `system` | Gives a consumer its system prompt, with a packaged fallback |
| `resolve` | Reads prompts and versions from the graph and resolves references |
| `rendering` | Renders templates in a Jinja2 sandbox with resource limits |
| `pool` | Keeps warm worker processes that render templates |
| `worker` | The worker process (`python -m imbi.common.prompts.worker`) |

## References

A reference names a prompt version:

| Form | Selects |
|---|---|
| `namespace/slug` | The version that has the prompt's default label |
| `namespace/slug@label` | The version that has the label. If the prompt does not have the label, the default label |
| `namespace/slug@n` | Version `n` |

`resolve.resolve(db, ref)` returns the prompt, the version, and the
label. It raises `InvalidRef` for a bad reference and `PromptNotFound`
when the prompt, the version or a usable label does not exist. Both are
subclasses of `PromptError`.

## Load a system prompt

`system.load_system_prompt()` returns a `SystemPrompt`. It tries three
sources in this order:

1. `override`: a template that the operator supplies, for example in an
   environment setting.
2. The CMS version that `ref` names.
3. The `DefaultPrompt` that is packaged with Imbi.

A failure in the CMS path, such as a missing prompt or a render error,
is logged. The function then uses the packaged prompt. A broken prompt
therefore never stops a conversation. `SystemPrompt.source` tells you
which source was used.

```python
from imbi.common.prompts import system

prompt = await system.load_system_prompt(
    db,
    'imbi-assistant/system@stable',
    {'display_name': 'Pat', 'email': 'pat@example.com', ...},
    system.ASSISTANT,
)
```

The function passes only the variables that the version declares. An
editor can therefore remove a variable from a version without a render
error.

When the CMS version names an enabled AI model that an `anthropic`
provider serves, `SystemPrompt.model_id` holds its model ID. In all
other cases it is `None`, and the consumer uses its configured model.

## Render limits

`rendering.render()` renders the system template and each message of a
version. It raises `RenderError` when the variables are not valid, the
template fails, or the template breaks a limit. The sandbox blocks
private attributes and Python internals. A template sees only the
variables and the registered providers.

| Limit | Value |
|---|---|
| Rendered output | 262144 characters (`MAX_OUTPUT`) |
| Work units for one render | 4194304 (`MAX_WORK`) |
| Work units for one loop iteration | 256 (`ITERATION_COST`) |
| `range()` length | 1000 (`MAX_RANGE`) |
| Loop nesting | 2 (`MAX_LOOP_DEPTH`) |
| Wall clock, including provider calls | 2 seconds (`RENDER_TIMEOUT`) |

Macros and recursive loops are not allowed. Only principals with
`prompt:update` can save a template.

## Render workers

Renders run in separate worker processes. A worker has no database
access and no credentials. When a template calls a provider, the worker
asks the parent process to run it. The parent kills a worker that runs
too long, crashes, or sends too much output, and starts a new one.

Add `pool.pool_lifespan` to the service lifespan to start the workers at
startup and stop them at shutdown. `imbi-api`, `imbi-assistant`,
`imbi-slackbot` and `imbi-workflows` do this. If the workers cannot
start, the service still starts, and a render starts a worker when it
needs one.

| Variable | Default | Description |
|---|---|---|
| `IMBI_PROMPT_WORKERS` | `2` | Workers for each service process |
| `IMBI_PROMPT_WORKER_MAX_RENDERS` | `500` | Renders before the pool replaces a worker |
| `IMBI_PROMPT_WORKER_MEMORY_MB` | `256` | Address space that a worker can add after it starts. Linux only |
| `IMBI_PROMPT_RENDER_INPROCESS` | `false` | Render in the service process. For debugging only: it removes the isolation |

## API Reference

### System prompts

::: imbi.common.prompts.system.load_system_prompt

::: imbi.common.prompts.system.load_model_id

::: imbi.common.prompts.system.SystemPrompt

::: imbi.common.prompts.system.DefaultPrompt

### References

::: imbi.common.prompts.resolve.resolve

::: imbi.common.prompts.resolve.parse_ref

::: imbi.common.prompts.resolve.PromptError

::: imbi.common.prompts.resolve.InvalidRef

::: imbi.common.prompts.resolve.PromptNotFound

### Rendering

::: imbi.common.prompts.rendering.render

::: imbi.common.prompts.rendering.render_decision

::: imbi.common.prompts.rendering.check_syntax

::: imbi.common.prompts.rendering.validate_variables

::: imbi.common.prompts.rendering.RenderError

### Worker pool

::: imbi.common.prompts.pool.pool_lifespan

::: imbi.common.prompts.pool.get_pool

::: imbi.common.prompts.pool.RenderPool
