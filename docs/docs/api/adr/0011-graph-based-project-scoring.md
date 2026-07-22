# ADR 0011: Graph-Based Project Scoring

## Status

Accepted

Attribute-policy scoring is the first implementation; event-based scoring is explicitly deferred. Source design lives in [`imbi/docs/scoring-system-design.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/scoring-system-design.md).

## Context

Imbi v1 scores projects via a fact-based system: each `project_fact_type` has a weight, every fact value maps to a 0–100 score, and a project's score is the weighted average. This measures *how well a project is set up* (modern language version, has tests, follows conventions) but misses *how well a project is operating*. A project can score 100 in v1 while paging on-call nightly.

v2 changes the substrate underneath that scoring system in three ways:

1. **Blueprints replace `project_fact_types`.** Custom project metadata is now a JSON-Schema field on a blueprint, not a separately-modeled fact-type with a hardcoded weight.
2. **Apache AGE replaces the v1 relational schema.** Graph traversal becomes the natural way to express "which policies apply to which projects" via `TARGETS` edges and effective-attribute-set membership.
3. **ClickHouse is the analytics substrate.** Score history and aggregations belong in ClickHouse with materialized views; AGE holds current state.

The v2 scoring system must keep what worked in v1 (weighted attribute scoring) while adding a clean path to operational health signals from integrations (PagerDuty, GitHub, CI, SonarQube), without forcing the integration story before it's settled.

## Decision

### 1. Scoring policies replace fact types

A **`ScoringPolicy`** node defines one scoring rule: what attribute to score, how to map values to scores, what weight to give it, and (optionally) which project types to target.

```
ScoringPolicy:
  slug, name, description, category, weight (0-100), enabled, priority
  attribute_name: str
  value_score_map: dict[str, int] | None       # enum lookup
  range_score_map: dict[str, int] | None       # half-open numeric ranges
```

A policy sets exactly one of `value_score_map` or `range_score_map`. Range maps may have gaps; overlapping keys are rejected at validation.

### 2. Targeting is graph-traversal driven

A policy applies to a project when **both**:

1. The policy's `attribute_name` is in the project's **effective attribute set** — the union of base `Project` model fields and the fields contributed by every blueprint applied to the project's type(s).
2. If the policy has `TARGETS → ProjectType` edges, the project's type is in that list. Policies without `TARGETS` edges are unrestricted.

There is no separate `SCORES_ON → Blueprint` edge. Removing a blueprint from a project type removes its fields from the effective attribute set; policies referencing those fields naturally stop applying — no edge cleanup required.

### 3. Policies are independent and compose by weighted average

Multiple policies may score the same attribute (e.g., one global policy with weight 10 and one team-specific policy with weight 40). Both contribute to the weighted average. `priority` controls UI display order only and does not affect score computation.

### 4. The score lives on the `Project` node

`Project.score: float | null` holds the materialized current score. Null until first computation. This keeps queries like "find projects in Team X with score < 50" to a single Cypher hop without on-the-fly recomputation.

### 5. Recomputation is async and idempotent

Recomputes are enqueued to a Valkey Streams queue (`imbi:score-recompute`) with a per-project debounce key. Triggers:

- Attribute value changes on the project.
- A blueprint is applied to or removed from the project's type.
- A scoring policy is created, modified, or deleted.
- A bulk rescore is requested.

Producers enqueue **after** the originating DB commit completes; otherwise the worker can read stale state during the debounce window. Workers are idempotent — re-delivery is safe — and failure leaves the message un-ACK'd for retry.

### 6. Phase 1 (base score): pure attribute policies

```
base_score = sum(value_to_score(value) * policy.weight) / sum(policy.weight)
```

- A project with no applicable policies scores 100 (no opinion, no penalty).
- A project with an applicable policy but no mapped value scores 0 for that policy (missing data is a signal).
- The breakdown API surfaces every contribution so consumers can show "missing data on X."

### 7. Phase 2 (event modifiers): deferred

The original direction — event policies for operational health from integrations, time-decay vs resolution-event modes, environment-aware penalties — is captured in the source design doc and will be re-derived alongside the integration ingestion design. Until then, `final_score = max(0, base_score)`. The base API response includes `unfloored_total` so the breakdown is honest about the headroom once event modifiers can pull a project below zero.

### 8. History lives in ClickHouse

```sql
CREATE TABLE score_history (
    organization, team, project_type, project, project_slug,
    timestamp DateTime64(3),
    score, previous_score Float32,
    change_reason String
) ENGINE = MergeTree()
ORDER BY (organization, team, project_type, project_slug, timestamp);
```

A `score_latest` `AggregatingMergeTree` materialized view provides pre-computed latest scores and averages for dashboards.

History writes happen **before** the AGE node update. If the AGE write fails after a successful CH insert, the materialized score is stale until the next recompute — never lost. Reversing the order can silently drop history rows.

Scores are per-project, not per-environment (an earlier draft included an `environment` column; it had no consistent meaning at the project level).

## Consequences

### Positive

- v1's weighted-attribute scoring carries forward cleanly with blueprint-defined fields and graph-based targeting.
- Adding a new blueprint with a new attribute automatically lets operators add a policy for it — no code change.
- Rollups (org, team, project type, blueprint coverage) are ClickHouse-native and fast.
- The deferred event-policy work has a clear extension point (`category='event'`, `(ScoringPolicy)-[:USES]->(Integration)` edges, modifier table) without forcing the design now.

### Negative

- Two stores must stay coherent. The "CH first, then AGE" ordering trades AGE freshness for history durability.
- The "no opinion → 100" default can look strange when a project genuinely has no relevant attributes. Documented in the breakdown response.
- v1's `project_fact_history` is not migrated. Historical fact values that produced past scores are not reconstructable in v2; the `score_history` table is the canonical history going forward.

### Risks Accepted

- **Fan-out under high-cardinality changes**: changing a blueprint that touches every project of a popular type enqueues every such project. The Valkey Streams queue with debounce absorbs the spike; no separate batch path is needed at expected scale.
- **Policy explosion**: nothing prevents an operator from defining hundreds of policies. UI ordering via `priority` and the breakdown endpoint help, but governance is administrative.
- **Migration loudness**: if a v1 fact's `attribute_name` is not present in any project type's effective attribute set, migration fails loudly with a manifest of unmatched fact types. We do not silently create blueprints to make migration succeed.

## References

- [`imbi/docs/scoring-system-design.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/scoring-system-design.md) — Full design, including deferred event-policy direction.
- [`imbi/docs/scoring-system-implementation-plan.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/scoring-system-implementation-plan.md) — Implementation plan.
- [`imbi/docs/score-history-data-shape.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/score-history-data-shape.md) — Score history data reference.
- ADR 0007: Relationship Blueprints (blueprint substrate that defines scored attributes)
