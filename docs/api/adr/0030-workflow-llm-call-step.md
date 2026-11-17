# ADR 0030: Workflow LLM Call Step

Date: 2026-11-17

## Status

Accepted

Related: [ADR 0018](0018-ai-model-catalog.md) (AI model catalog),
[ADR 0021](0021-workflow-contract.md) (workflows),
[ADR 0027](0027-workflow-script-step.md) (script step).

## Context

Workflows can ask a decision model to pick a branch (`model_decision`)
and give a task to an agent (`agent`). No step sends a prompt to a
generative model and returns its answer. An author who must summarize a
diff, classify a webhook payload, or prepare the brief of a later agent
task, must start an agent. That is slow and costs more than one call.

The AI model catalog holds generative models of five drivers:
`anthropic`, `openai`, `openai_compatible`, `bedrock`, and `vertex`. No
server code sent a prompt to them. The Prompt CMS stored generative
prompt versions (system text, messages, model, params), and rendered
them with Jinja2 in a sandbox, but its run endpoint ran decision
prompts only.

## Decision

### The step type

A new step type, `llm_call` ("LLM Call"), in the `logic` category.

| Parameter | Meaning |
|---|---|
| `prompt_ref` | `workflows/<org>.<workflow>.<node key>`, with no version |
| `prompt_version` | The version of the prompt that the step runs |
| `inputs` | Names to values. Each name becomes a variable of the prompt. A value can be a reference. At most 20 |
| `output_fields` | Optional. The structured answer, in the model of the `agent` step |

Output: `text`, `result` (with `output_fields` only), `model`,
`model_id`, `prompt_version`, `content_sha256`, `usage` (`input_tokens`,
`output_tokens`), `cost_usd`, and `call_id`. Later steps reference the
answer as `{{ <key>.text }}`, or each field as
`{{ <key>.result.<field> }}`. With `output_fields`, `text` is the JSON
of `result`.

An input name follows the key pattern of the graph. Jinja2 reads
`true`, `false`, `none`, `not`, and `self` as something other than a
variable, so these names are refused. Python keywords are accepted:
the prompt is not Python.

The step needs `prompt:run` to activate. Its timeout is 300 seconds,
and it retries 2 times.

### The prompt is in the Prompt CMS

The editor shows the prompt in the step, but the step holds a reference,
not the text.

- Namespace `workflows`, slug `<org>.<workflow slug>.<node key>`. The
  prompt belongs to the organization in the slug. `workflow:write` in
  that organization can create it and add versions, the same as
  `agent:write` for the `agents` namespace.
- The step pins a version. An edit to the prompt does not change a saved
  workflow version, so a workflow version is reproducible.
- On save, the editor creates the prompt when it is missing, adds a
  version when the content changed, then saves the workflow with the
  new version number. The editor writes the `variable_schema` of the
  version from the names of `inputs`, so a renamed input fails at save,
  not at run.
- imbi-api refuses a workflow save when a step names another node's
  prompt, when the pinned version does not exist, or when the step has
  `output_fields` and the model does not support structured output.
- A `workflows` prompt cannot be deleted or renamed through the prompt
  endpoints (`409`), and cannot have tools (`422`).
- A deleted workflow, or a node that a save removes, archives its prompt.
  An archived prompt is not listed. A pinned `ref@n` still resolves, so
  old workflow versions and call records stay readable. A new version of
  an archived `workflows` prompt un-archives it: a node with the same key
  is back. Other archived prompts get no new versions (`409`).
- The engine renders only `inputs`. imbi-api renders the prompt. So
  `{{ }}` in the prompt text has one meaning.

### The model call runs in imbi-api

The engine does not call the provider. It sends
`POST /organizations/{org}/prompts/run` with
`ref: <prompt_ref>@<prompt_version>` and the rendered inputs, as its
service account, and checks that the answer is from the pinned version.

- Workload identity tokens are minted only in imbi-api.
- Bedrock with the runtime IAM role signs each request with SigV4
  (botocore) in imbi-api.
- The CMS render (the Jinja2 sandbox, the `project()` provider) is in
  imbi-api.
- The editor preview and the engine call the same endpoint, so they
  cannot differ.

The run endpoint now runs generative prompts too. It needs
`prompt:update` (any prompt, also a draft), or `prompt:run` (a saved
version of a generative prompt). For a `workflows/<org>.*` prompt,
`workflow:write` in `<org>` is also enough, also for a draft: this is
the editor preview. A run spends provider credit, so readers cannot run
a prompt. The `imbi-workflows` service account gets `prompt:run`.

`model_decision` does not change. To move it to the same path is a
separate change.

### Every call is recorded

imbi-api writes one row for each generative call to
`ai_runtime.ai_model_calls`, a Postgres schema that imbi-api applies at
startup. Postgres, not ClickHouse: the idempotency key needs a unique
constraint and a consistent read.

- A row holds the caller, the origin (`workflow` or `preview`), the run,
  node, and attempt, the prompt ref, version, and content hash, the
  model, the rendered system text and messages, the output schema, the
  answer, the status (`running`, `succeeded`, `failed`,
  `outcome_unknown`), the error code, the usage, and the cost in USD
  from the catalog prices.
- The engine sends `Idempotency-Key: <run>:<node>:<attempt>`. A repeat
  of a key that succeeded gets the stored answer and makes no call. A
  repeat while the call runs gets `409 call_in_progress`, and the engine
  asks again later with the same key. A `running` row older than the
  call timeout (120 seconds) plus 60 seconds becomes `outcome_unknown`,
  and the step fails. A step retry is a new attempt, so it is a new key
  and a new call.
- The step keeps `side_effect=False`: the record, not the engine, stops
  a second call.
- The `ai-model-calls-prune` maintenance operation deletes rows older
  than 90 days. A scheduler system task runs it daily at 02:30 UTC. 90
  days is much longer than the longest run, so a prune never removes a
  live key.

### Structured output is a property of the model

The catalog records `supports_structured_output` for each model. The
default is `false`, so an unknown model is refused, not tried. An admin
sets it; no discovery fills it in. A step with `output_fields` cannot
use a model without it. The editor disables the output fields, the
workflow save refuses it (`422`), and the run endpoint refuses it
(`422 model_no_structured_output`) when the flag changed after the save.

### Drivers

`imbi.common.llm.generate` has one adapter for each driver:

| Driver | Call | Structured output |
|---|---|---|
| `anthropic` | `messages.create` | One forced tool |
| `openai`, `openai_compatible` | `POST /chat/completions` | Strict `json_schema` response format; each optional field becomes a required field that can be `null` |
| `bedrock` | Converse API | One forced tool |
| `vertex` | Gemini `generateContent` | `responseMimeType: application/json` with `responseJsonSchema` |

- Vertex means Gemini only. Claude on Vertex is not supported.
- Vertex needs a stored key (express mode). Google IAM credentials are
  not supported: imbi-api does not depend on `google-auth`.
- Each structured answer is checked against the schema with
  `jsonschema`, then completed with the empty optional fields. An answer
  that does not parse or match is a retryable `model_answer_invalid`.
- An error has `detail={'error': <code>, 'retry': <bool>}`. The engine
  retries a step only when `retry` is true.

## Consequences

- Authors get one model call per step, without an agent.
- A run spends provider credit. Only people with `prompt:run` can
  activate a workflow with the step. A preview needs `workflow:write` or
  `prompt:update`.
- The call record holds the rendered prompt and the answer for 90 days.
  Anything that the inputs hold is stored there, also secrets that an
  author maps into a prompt.
- The record holds usage and cost, so per-organization spend tracking
  can be built on it later. This ADR does not add limits.
- An admin must set the structured output flag of each model. Until then,
  steps with output fields cannot use the model.
- The preview creates the CMS prompt of a new node before the workflow
  exists, so the editor runs a preview only after the first save of the
  workflow.

## Alternatives Rejected

- **The engine calls the provider.** The engine cannot mint workload
  identity tokens, has no AWS signing, and has no CMS render. The
  preview and the run would use two code paths that can differ.
- **No call record.** A step that times out in the engine, or an engine
  crash, would repeat a call that the provider already billed, and an
  author could not see what the model got. The record makes a repeat of
  an attempt return the first answer.
- **Best-effort structured output.** Try any model, and fail when the
  answer does not parse. Models without structured output give text that
  only sometimes parses, so a workflow would fail at random. A flag on
  the model makes the failure a save error.
- **A workflow-scoped run endpoint.** The idempotency key on
  `/prompts/run` gives the same protection, with one endpoint.
- **The prompt text in the step params.** The prompt would be a workflow
  template, and `{{ }}` would have two meanings. The CMS gives versions,
  labels, and the existing render sandbox.
