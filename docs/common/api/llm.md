# LLM

The `imbi.common.llm` package holds the code that Imbi services use to
call language models and to manage the AI model catalog. For the
operator view of providers and models, see
[AI models](../../admin/ai-models.md).

| Module | What it does |
|---|---|
| `imbi.common.llm` | `AnthropicClient`, a small wrapper for JSON completions |
| `drivers` | The static catalog of provider drivers |
| `discovery` | Reads the model list from a provider's list-models API |
| `typesafe` | Calls a TypeSafe System One decision model |

`AnthropicClient` and `discovery` need the `llm` extra, which installs
the `anthropic` package.

## JSON completions

`AnthropicClient.complete_json()` sends one prompt and validates the
first JSON object in the response against a Pydantic model. It never
raises for a model failure. When the API key is not set, the SDK is not
installed, the call fails, or the response does not validate, it returns
your `fallback` with `degraded=True`. An endpoint can pass `degraded` to
the UI to say that AI is not available.

```python
import pydantic

from imbi.common import llm


class Summary(pydantic.BaseModel):
    title: str
    body: str


client = llm.AnthropicClient()
result = await client.complete_json(
    'Summarize these commits as JSON with title and body: ...',
    schema=Summary,
    fallback=Summary(title='', body=''),
)
if result.degraded:
    ...
```

Make one client at startup and use it for all requests. Call
`aclose()` at shutdown. Set `cache_system_prompt=True` with a `system`
prompt to send the system prompt with prompt caching.

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | none | The API key. Without it, every call returns the fallback |
| `IMBI_ANTHROPIC_DEFAULT_MODEL` | `DEFAULT_MODEL` | The model to use when the call does not give one |
| `IMBI_ANTHROPIC_TIMEOUT` | `30.0` | Request timeout, in seconds |
| `IMBI_ANTHROPIC_MAX_RETRIES` | `2` | SDK retries |

## Drivers

A driver is the code that talks to one kind of provider. Drivers are in
code, not in the graph. An `AIProvider` node exists only when an admin
configures a provider. `DRIVERS` is the catalog. Each `DriverInfo` says
if the driver has a default endpoint, needs a `base_url`, can use cloud
IAM credentials, supports model discovery, and serves `generative` or
`decision` models.

`resolve_base_url(driver, base_url)` returns the provider's own
`base_url`, or else the driver default.

## Model discovery

`discovery.list_models(driver, api_key, base_url)` returns the models
that a provider reports. Only the `anthropic`, `openai` and
`openai_compatible` drivers support it. The admin UI uses it to make
`AIModel` nodes and to test a stored credential. Every failure raises
`DiscoveryError`. Its message contains no API key and no response body,
so the caller can show it to an admin.

## Decision models

`typesafe.decide()` sends a state and a set of questions to a TypeSafe
System One model (the `typesafe` driver) and returns typed answers. Every
failure raises `DecisionError`, with a message that is safe to show.

## API Reference

### Anthropic client

::: imbi.common.llm.AnthropicClient

::: imbi.common.llm.CompletionResult

::: imbi.common.llm.AnthropicSettings

::: imbi.common.llm.DEFAULT_MODEL

### Drivers

::: imbi.common.llm.drivers.DriverInfo

::: imbi.common.llm.drivers.DRIVERS

::: imbi.common.llm.drivers.get_driver

::: imbi.common.llm.drivers.resolve_base_url

### Discovery

::: imbi.common.llm.discovery.list_models

::: imbi.common.llm.discovery.DiscoveredModel

::: imbi.common.llm.discovery.DiscoveryError

### TypeSafe

::: imbi.common.llm.typesafe.decide

::: imbi.common.llm.typesafe.DecisionResult

::: imbi.common.llm.typesafe.DecisionError
