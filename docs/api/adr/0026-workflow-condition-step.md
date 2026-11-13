# ADR 0026: Workflow Condition Step

Date: 2026-11-13

## Status

Accepted

Related: [ADR 0021](0021-workflow-contract.md) (workflows: each step type
beyond v1 gets its own decision), [ADR 0024](0024-work-items.md) (proposes
a Branch step).

## Context

A workflow branches today with a model decision, or on the outcome of a
deploy or agent step. To branch on data that a step already returned, such
as the risk that an agent reported, a workflow must ask a model. That costs
a call, can be wrong, and is slow.

References render in two ways (ADR 0021, References). A value that is one
reference, such as `{{ triage.result.count }}`, keeps its type. Any other
template renders as text. So a comparison gets typed values and text, and
it must coerce.

## Decision

Add a `condition` step type in the `logic` category. It compares values and
takes one of two ports, `True` or `False`. It makes no call and has no side
effect. Its default timeout is 10 seconds, with no retries.

### Parameters

- `conditions`: 1 to 10 rows. Each row is `a`, `operator`, and `b`. `a` and
  `b` hold values or templates. `b` is required, except for `is_empty` and
  `is_not_empty`.
- `match`: `all` (every row holds) or `any` (one row holds). Default `all`.
- `ignore_case`: compare text in any case. Default `false`.

`a` and `b` accept a string, a number, a boolean, a list, an object, or
null. Save sees a template string. The engine validates the parameters
again after it renders them, and then a value that is one reference has its
own type.

### Operators and coercion

| Operator | Rule |
|---|---|
| `equals`, `not_equals` | Two numbers compare as numbers. A boolean compares as `true` or `false`, in any case. Other values compare as text |
| `greater_than`, `greater_or_equal`, `less_than`, `less_or_equal` | Both sides are numbers or numeric text. A boolean, NaN, and infinity are not numbers |
| `contains`, `not_contains` | A list `a` contains `b` as an item, with the `equals` rule. A text `a` contains `b` as a substring |
| `starts_with`, `ends_with` | `a` is text |
| `matches` | `a` is text. `b` is an RE2 expression |
| `is_empty`, `is_not_empty` | Null, empty text, an empty list, or an empty object is empty |

Numbers compare as decimals, so `"0.1"` equals `0.1`. A skipped step
renders as empty text in a template and as null in a whole reference, so
`is_empty` holds for both.

`matches` uses RE2 (`google-re2`). Its time is linear in the input, so a
pattern from a trigger payload cannot hang the engine. RE2 has no
backreferences or lookaround.

### Errors

The step evaluates every row. A row that cannot be evaluated fails the step
with `not_a_number`, `not_text`, or `invalid_pattern`, with no retry: the
same values give the same error. The type has no `Failed` port, so the run
fails. A row error is a mistake in the workflow or in the data, and a
`False` port would hide it as a valid answer.

### Type warnings

When `a` or `b` is one reference to an output whose type is known (the
output schema of an earlier step, or an `output_fields` field of an agent
step), and no type of it suits the operator, validation adds the warning
`condition_type_mismatch`. The editor outlines the row in red. An example is
`greater_than` on a string field. A text template, a trigger value, and an
untyped field have no known type, so they get no warning.

One table holds the rule in each language: `FITS` in the registry module of
the step, and its copy in the UI.

### Not decided here

- The Branch step of ADR 0024: one port per case and an `Else` port, over
  facts and work item fields. A condition step has two ports and compares
  references.
- Expressions, such as CEL, in a condition.

## Consequences

- A workflow can branch on step output with no model call.
- A type warning does not stop activation, unlike every other warning
  (ADR 0021, Validation). A string field that holds numbers, such as
  `"5"`, compares correctly at run time, so the warning can be wrong. A
  value that does not fit fails the step, and the run, when it runs.
- `imbi-common` depends on `google-re2` directly. It was already installed
  through `cel-python` in the gateway.
- The rule of which types suit which operator is in Python and in
  TypeScript. A change to one must change the other.
