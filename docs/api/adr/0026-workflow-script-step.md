# ADR 0026: Workflow Script Step

Date: 2026-11-13

## Status

Accepted

Related: [ADR 0021](0021-workflow-contract.md) (workflows). This ADR is
the decision that ADR 0021 asks for before a script step ships.

## Context

Workflows can wait, ask a model to pick a branch, deploy, roll back,
send email, and give a task to an agent. No step transforms data or
picks a branch by a rule. An author who must count failed runs in a
webhook payload, or route on a numeric threshold, must ask a model or an
agent. That is slow, costs money, and is not deterministic.

A small program does this work best. Running code that people write is a
risk: it must not reach the network, the file system, the database, or
the credentials of the service that runs it.

[pydantic-monty](https://github.com/pydantic/monty) is an interpreter
for a subset of Python, written in Rust. It runs code in worker
subprocesses. It has no ambient authority: no files, no environment, no
network, and no subprocesses unless the host grants them. It enforces
limits on memory, run time, and recursion. A spike on 2026-11-13 ran
versions 1.5.0 and 1.6.0 on macOS arm64, and 1.6.0 on Linux arm64, and
confirmed each of these.

## Decision

### The step type

A new step type, `script`, in the `logic` category.

| Parameter | Meaning |
|---|---|
| `inputs` | Names to values. Each name becomes a global of the script. A value can be a reference; one whole reference keeps its type. At most 20. |
| `code` | Python source, at most 16 KiB. It is never rendered as a template. |
| `output_fields` | The structured result, in the model of the `agent` step. At least one. |
| `branches` | Optional. Port names. When set, the script picks one. |

The value of the last expression of the script is its result. It must be
a mapping that matches the JSON Schema of `output_fields`. Later steps
reference it as `{{ <key>.result.<field> }}`.

When `branches` is set, the result must also hold `branch`, one of the
names. `branch` is a reserved field name. The engine removes it before
the schema check and takes the port of that branch. With no `branches`,
the step has one unnamed port.

Output: `result`, `branch`, and `stdout` (the text of `print()`, at most
8 KiB).

The step has no side effect, is idempotent, needs no permission, and
does not retry by default. Its default timeout is 30 seconds.

### No authority

The script gets no host functions, no modules from the host, and no
mounts. It cannot read a secret, call imbi-api, or make an HTTP request.
A step that needs any of these is a different step type with its own
decision.

When parameters that name Integration secrets ship (ADR 0021,
References), a script input must not take one: a script can copy an
input to its result, its output, or an error.

### One runner

One module of `imbi-common`, `imbi.common.workflows.script_runner`,
holds the pool, the limits, the conversion of the result, the schema
check, and the error codes. It is behind the `script` extra, so
services that do not run scripts do not install pydantic-monty. The
engine and the editor preview both call it, so they have one sandbox
configuration.

- Each call takes one checkout. A worker serves one checkout, then the
  pool replaces it.
- Limits: 64 MiB of memory and 5 seconds per call by default, never
  more than the step timeout. The pool kills a worker that does not
  answer.
- The result is converted to JSON types. A key that is not a string, a
  float that is not finite, and a value with no JSON form fail the step.
  The output is at most 64 KiB of JSON, checked before the schema check.

| Cause | Error | Retry |
|---|---|---|
| Code does not parse | `script_syntax_error` | No |
| Code raises | `script_error` with the type and message | No |
| Time limit | `script_timeout` | No |
| Memory limit | `script_memory` | No |
| Worker died | `script_crashed` | Yes, when the node sets retries |
| Result not a mapping, not JSON, or not the schema | `script_output_invalid` | No |
| Output too large | `script_output_too_large` | No |
| `branch` missing or not a branch | `script_branch_invalid` | No |

### Template rendering

`code` is Python. Python holds `{{` and `{%` (an f-string, a set in a
dict), so `code` must not go through the Jinja rendering of ADR 0021.
A step type declares `raw_params`, the top-level parameters that are
never rendered or checked for references.

### Preview

The workflow editor can run a script with sample inputs before it saves
the workflow. `POST /organizations/{org}/workflows/script-preview` takes
`code`, `inputs`, `output_fields`, and `branches`, and returns the
output of the step or its error. It needs `workflow:write`. It renders
no references and stores nothing. imbi-api keeps its own small pool for
it. A full pool returns `503`.

## Consequences

- Authors get deterministic transforms and branches without a model.
- The risk is a sandbox escape through a bug in the interpreter. The
  worker runs as the same user as its service. In the engine, an escape
  reaches the service-account secret and the database. In imbi-api,
  where the preview runs, it also reaches the JWT secret and the key
  that encrypts Integration credentials. Only members with
  `workflow:write` can send a script. The alternative, a preview that
  imbi-api sends to imbi-workflows, keeps scripts out of imbi-api but
  needs service-to-service auth and a new Helm service. If the risk
  becomes too high, move the preview there, or run the workers in a
  separate pod with no credentials.
- The Python subset surprises people: no class inheritance, no
  generators, a different regular expression engine. The admin docs
  state the subset and link to the vendor's list.
- Each engine process and each imbi-api process keeps a few `monty`
  worker processes. Pod memory limits must allow for them.
- pydantic-monty changed its API shape between 0.0.x and 1.x. It is
  pinned to `~=1.5`, and only the runner imports it.
- Step input holds the code, so each step event copies up to 16 KiB of
  code to ClickHouse.
