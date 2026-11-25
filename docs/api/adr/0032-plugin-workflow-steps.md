# ADR 0032: Plugin Workflow Steps

Date: 2026-11-25

## Status

Accepted

Related: [ADR 0021](0021-workflow-contract.md) (workflows),
[ADR 0026](0026-workflow-condition-step.md) (condition step),
[ADR 0030](0030-workflow-llm-call-step.md) (LLM call step).

## Context

Each workflow step type is a module in
`imbi.common.workflows.registry`, and the engine runs it with a `match`
on the type. A step that reads or changes a remote system, for example
"get the metrics of a Grafana dashboard", needs a platform change, even
when a plugin already holds the credentials of that system.

The plugin architecture has a fixed set of capability kinds. A kind tells
the platform how to host the capability. `webhook-actions` already gives
a static catalog of actions, each with a pydantic config model, and
`search_logs` already shows how a workflow step reaches a plugin: the
engine calls imbi-api, and imbi-api runs the handler with the
decrypted credentials of the Integration.

The builder makes the form of a step from the JSON Schema of its params.
Live pickers exist only for some param names (`project_id`, `agent_id`,
and others).

## Decision

### A new capability kind: `workflow-steps`

A plugin gives workflow step types through a `workflow-steps`
capability. Its handler subclasses `WorkflowStepsCapability` and returns
a static list of `WorkflowStepDescriptor`s from `steps()`. A descriptor
holds:

- a name, a category (`action` or `logic`), a label, and a description;
- a pydantic params model and output model (as `ImportString`s);
- the output ports. A logic gate names one port per result, for example
  `('Pass', 'Fail')`;
- `side_effect`, `idempotent`, `timeout_seconds`, `retries`;
- `poll_seconds`, when the step can ask to be called again;
- `project_scoped`, when the step needs a project;
- `permissions`, which the person who activates the workflow must have;
- the run callable, and an optional choices callable.

The registry validates the catalog when it loads the plugin. A step that
has a side effect must declare at least one permission.

### The step type

The type of a plugin step is `<plugin_slug>.<name>`. Built-in types have
no `.`, so the names cannot collide. `registry.get()` and
`registry.all_types()` give the built-in types and those of the loaded
plugins. Each read of a step type uses them.

The host adds an `integration` param to each plugin step: the slug of an
organization Integration of that plugin. A project-scoped step also gets
`project_id`. The params model of the plugin must not declare these
fields. To activate a workflow, a person needs `integration:read` plus the
permissions of the descriptor.

### imbi-api runs the step

The engine calls one imbi-api endpoint for each call of a plugin step.
imbi-api checks the Integration, decrypts its credentials, validates the
params, and calls the callable. The engine does not decrypt Integration
credentials. The engine loads the plugins only to read the catalog.

A call returns an output and a port, or asks to be called again
(`poll`), with a state that the next call gets. The step timeout limits
all the calls of a step in total. imbi-api records each call with an
idempotency key, as it does for model calls, so that a repeated request
does not act twice.

### Forms

The builder makes the form from the JSON Schema of the params, as it
does for built-in types. Two schema keys add live data:

- `x-imbi-source: integration` on the `integration` param: a picker of
  the organization Integrations of the plugin that have
  `workflow-steps` on.
- `x-imbi-choices: true` on a params field: the builder asks imbi-api for
  the choices of the field, and imbi-api calls the choices callable.
  `x-imbi-depends-on` names the fields that the choices depend on.

The values that the editor sends to a choices callable are untrusted.
A choices callable takes hosts and URLs from the Integration options
only.

## Consequences

- A plugin adds step types without a platform change, and its steps use
  the credentials and options of the Integration that the node selects.
- A plugin step costs one HTTP call to imbi-api for each call of the
  step.
- A workflow that uses a step of a plugin that is not loaded fails
  validation. A run that reaches such a step fails it.
- imbi-api and the engine must run the same plugin versions. Both come
  from one image.
- Each plugin step has a call record in Postgres.

## Alternatives Rejected

- **The engine runs the plugin code.** The gateway does this, but then a
  second service holds Integration secrets, and the bounds and call
  records of imbi-api do not apply.
- **The project selects the Integration**, as `search_logs` does. Every
  step would need a project, and organization-level systems such as
  Grafana would need project bindings that have no other use.
- **Forms from a plugin UI module.** `ui_module` stays reserved. JSON
  Schema plus the two keys covers the known steps, with no plugin code in
  the browser.
- **Polling with a loop of a gate and a `wait` step.** Each workflow
  author would build the same loop, and the run history would show one
  step per poll.
