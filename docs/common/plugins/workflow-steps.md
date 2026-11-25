# Workflow Steps Capability

`WorkflowStepsCapability` is the contract base for plugins that add
workflow step types: actions, and logic gates that pick an output port.
Bind it with a `Capability(kind='workflow-steps', handler=...)` in the
plugin's manifest. The single required method is the `steps()`
classmethod. See [ADR 0032](../../api/adr/0032-plugin-workflow-steps.md).

Surfaces: **api**.

See [Authoring Plugins](index.md) for the manifest, capabilities,
context, credential decryption, and error conventions shared by every
plugin.

```python
import pydantic

from imbi.common.plugins import (
    Choice,
    PluginContext,
    StepCall,
    StepResult,
    WorkflowStepDescriptor,
    WorkflowStepsCapability,
)


class ThresholdParams(pydantic.BaseModel):
    datasource: str = pydantic.Field(
        json_schema_extra={'x-imbi-choices': True}
    )
    query: str
    below: float


class ThresholdOutput(pydantic.BaseModel):
    value: float


async def metric_threshold(
    ctx: PluginContext,
    credentials: dict[str, str],
    params: ThresholdParams,
    call: StepCall,
) -> StepResult:
    value = ...  # query the remote with the Integration credentials
    if value < params.below:
        return StepResult(output={'value': value}, port='Pass')
    return StepResult(poll=True, state={'last': value})


async def datasources(
    ctx: PluginContext,
    credentials: dict[str, str],
    field: str,
    params: dict[str, object],
) -> list[Choice]:
    return [Choice(value='prom', label='Prometheus')]


class GrafanaSteps(WorkflowStepsCapability):
    @classmethod
    def steps(cls) -> list[WorkflowStepDescriptor]:
        return [
            WorkflowStepDescriptor(
                name='metric_threshold',
                category='logic',
                label='Metric threshold',
                description='Waits until a metric is below a value.',
                params_model='imbi_plugin_grafana.steps:ThresholdParams',
                output_model='imbi_plugin_grafana.steps:ThresholdOutput',
                sample_output={'value': 0.4},
                ports=('Pass', 'Failed'),
                poll_seconds=60,
                timeout_seconds=3600,
                callable='imbi_plugin_grafana.steps:metric_threshold',
                choices='imbi_plugin_grafana.steps:datasources',
            )
        ]
```

## The step type

The workflow type is `<plugin_slug>.<name>`, for example
`grafana.metric_threshold`. The builder shows it as
`<plugin name> · <label>`, with the plugin icon.

The host adds an `integration` param: the slug of the organization
Integration that the step uses. A step with `project_scoped=True` also
gets `project_id`. Do not declare these fields in `params_model`.

## Descriptor rules

The registry refuses the plugin when:

- two descriptors have the same `name`;
- `ports` is empty or has a duplicate;
- `params_model` declares `integration`, or `project_id` on a
  project-scoped step;
- `side_effect=True` and `permissions` is empty. The engine runs steps
  as a service account, so a permission must limit who can activate a
  workflow that acts;
- a field has `x-imbi-choices` and the descriptor has no `choices`;
- `poll_seconds` is less than 30.

The person who activates a workflow needs `integration:read` and every
permission in `permissions`.

## Results

The callable returns a `StepResult`:

| Field | Meaning |
| --- | --- |
| `output` | The step output. It must validate against `output_model`. |
| `port` | The name of the output port. `''` for a step with one port. |
| `poll` | Call the step again after `poll_seconds`. |
| `state` | Given back in `StepCall.state` on the next poll. |

`timeout_seconds` limits all the polls of a step in total. When it ends,
the step fails, and it takes its `Failed` port if it has one.

## How a step runs

The workflows engine does not hold Integration credentials. It sends
each call to imbi-api as the `imbi-workflows` service account:

```text
POST /organizations/{org}/integrations/{integration}/workflow-steps/{name}/run
Idempotency-Key: <run_id>:<node_id>:<attempt>:<poll>
```

imbi-api checks that the Integration is in the organization, is of the
plugin of the step, and has the `workflow-steps` capability on. Then it
decrypts the credentials, validates `params` against `params_model`,
and calls the callable. The rules:

- One call has at most 60 seconds, or less when the step has less time
  left. The request and the result have at most 1 MiB each.
- Each call is recorded in `workflow_runtime.plugin_step_calls` by its
  key. A repeat of the key gets the first result and makes no second
  call. The `plugin-step-calls-prune` maintenance operation deletes the
  records after 90 days.
- Each poll and each retry is a new call with a new key. A step with
  `side_effect=True` and `idempotent=False` sends the key of a call that
  timed out again, so it does not act twice.
- An exception or a timeout of the callable is a `5xx` error: the engine
  retries the step up to `retries` times. A result that is not valid
  (an unknown port, an output that does not validate) fails the step.
- When the plugin of a step type is removed, a run of a workflow that
  uses the type fails with `unknown_type`.

## Form fields

The builder makes the form from the JSON Schema of `params_model`:
strings, numbers, booleans, enums (a select), lists of enums (a
multi-select), and lists. Two `json_schema_extra` keys add live data:

| Key | Meaning |
| --- | --- |
| `x-imbi-choices` | The builder loads the choices of the field from the `choices` callable. |
| `x-imbi-depends-on` | The fields whose values the choices depend on. The builder loads the choices again when they change. |

`choices(ctx, credentials, field, params)` gets the values typed so far.
Do not trust them: take hosts and URLs from the Integration options only.
A field with choices also accepts free text, because its value can be a
template.
