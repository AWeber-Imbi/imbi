# Workflows

The `imbi.common.workflows` package holds the workflow definitions that
`imbi-api` and the workflow engine (`imbi-workflows`) share. See
[ADR 0021](../../api/adr/0021-workflow-contract.md) for the design and
[Workflows](../../admin/workflows.md) for the operator view, including
the table of step types.

| Module | What it holds |
|---|---|
| `graph` | The models of a workflow version: `Graph`, `Node`, `Edge`, `Settings`, and the validation result |
| `step_type` | `StepType`, the declaration of one step type |
| `registry` | One module for each step type, and `STEP_TYPES` |
| `validation` | `validate()`, the checks of a version |
| `walk` | The order of the steps of a run. The engine and the test run use it |
| `runtime` | The `workflow_runtime` Postgres schema helpers, such as `append_event()` |
| `history` | The run log in ClickHouse, published through Iggy |

## Step types

`registry.STEP_TYPES` maps each type name to its `StepType`. Each module
in `registry` declares one `STEP`. A node with a type that is not in
`STEP_TYPES` fails validation.

A `StepType` declares:

| Field | Meaning |
|---|---|
| `type`, `category`, `label`, `description` | The name, the palette group (`trigger`, `logic`, `action`, `agent`) and the text in the editor |
| `params`, `output` | Pydantic models for the parameters and the output. The API serves their JSON schemas |
| `sample_output` | An example output that the editor shows |
| `ports` | The output port names. `('',)` is one port. `None` means one port for each entry in `params.branches` |
| `trigger` | The type starts a run |
| `side_effect`, `idempotent` | The type changes something outside the run, and a second call is safe |
| `timeout_seconds`, `retries` | The defaults. A node can set its own |
| `required_permissions` | A function from the node parameters to the permissions that the activating user must have |

When a call of a step that has `side_effect=True` and `idempotent=False`
stops before its result is recorded, the engine does not call it again.
The step fails with `outcome_unknown`.

To add a step type:

1. Add a module to `libraries/common/src/imbi/common/workflows/registry/`
   that declares `STEP`.
2. Add the module to `STEP_TYPES` in `registry/__init__.py`.
3. Add the executor to `Executors` in
   `apps/workflows/src/imbi/workflows/executors.py`. Add a type to the
   registry only when the engine can run it.

## Validation

`validate(graph, settings)` returns a `ValidationResult` with a list of
issues. A missing required parameter is a `warning`, so a draft can have
steps that are not configured. Every other issue is an `error`. The API
saves a version with its issues, but it activates only a version with no
issues. The API refuses to save a version that breaks one of the size
limits below (`LIMIT_CODES`).

| Limit | Value |
|---|---|
| Steps | 100 (`MAX_NODES`) |
| Connections | 200 (`MAX_EDGES`) |
| Graph size, as JSON | 65536 bytes (`MAX_GRAPH_BYTES`) |

## Run history

The engine and `imbi-api` write each run event to Postgres in the run's
transaction. After the commit, `history` publishes the event to the
`workflow_run_events` Iggy stream and the run state to `workflow_runs`.
A failed publish does not fail the write. The `imbi-api` archive sweep
publishes again the rows that ClickHouse does not have.

## API Reference

### Graph

::: imbi.common.workflows.graph.Graph

::: imbi.common.workflows.graph.Node

::: imbi.common.workflows.graph.Edge

::: imbi.common.workflows.graph.Settings

::: imbi.common.workflows.graph.ValidationIssue

::: imbi.common.workflows.graph.ValidationResult

### Step types

::: imbi.common.workflows.step_type.StepType

::: imbi.common.workflows.registry.STEP_TYPES

### Validation

::: imbi.common.workflows.validation.validate

### Walk

::: imbi.common.workflows.walk.order

::: imbi.common.workflows.walk.advance

### Runtime

::: imbi.common.workflows.runtime.append_event

::: imbi.common.workflows.runtime.pause_bindings
