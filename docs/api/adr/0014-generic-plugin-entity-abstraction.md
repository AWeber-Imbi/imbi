# ADR 0014: Generic Plugin-Entity CRUD Abstraction

## Status

Accepted

Source design lives in [`imbi/docs/plugin-entity-abstraction-plan.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/plugin-entity-abstraction-plan.md).

## Context

When wiring per-environment AWS credentials (ADR 0010), we added AWS-specific code into the host:

| File | What it does |
|---|---|
| `imbi-api/src/imbi.api/endpoints/aws_accounts.py` | Hand-coded CRUD for one plugin's entity type |
| `imbi-api/src/imbi.api/endpoints/environments.py` (tail) | Three endpoints handling one specific edge type to one specific target type |
| `imbi-ui/src/components/admin/AwsAccountsManagement.tsx` | Plugin-specific admin page |
| `imbi-ui/src/components/admin/environments/EnvironmentAwsAccountCard.tsx` | Plugin-specific anchor-detail card |
| `imbi-ui/src/api/endpoints.ts` | Hand-coded API client functions for the AWS routes |
| `imbi-ui/src/types/index.ts` | Hand-coded TS types mirroring `AwsAccount` |

Each new plugin entity type repeats this pattern: a hand-rolled router, hand-rolled UI, hand-rolled API client, hand-rolled types. The plugin's manifest already declares everything we need to drive this generically — `vertex_labels` (entity types the plugin owns) and `edge_labels` (relationships it owns) — but the host is not using those declarations.

ADR 0008 set up the plugin system as the extensibility surface. Continuing to hand-code per-plugin entities in core defeats the point.

## Decision

Three layers, ordered by leverage and effort.

### 1. Generic plugin-entity CRUD (API)

One router mounted once by the host. Replaces `aws_accounts.py` and any future analog.

```
GET    /admin/plugins/{slug}/entities/{label}
POST   /admin/plugins/{slug}/entities/{label}
GET    /admin/plugins/{slug}/entities/{label}/{id}
PATCH  /admin/plugins/{slug}/entities/{label}/{id}
DELETE /admin/plugins/{slug}/entities/{label}/{id}
```

The router validates that `{label}` is declared in the plugin's `vertex_labels`, looks up the JSON Schema for that label from the manifest, and validates request bodies against it before persisting to AGE. Permissions are derived: `plugins:{slug}:entities:{label}:{read|write}`.

### 2. Generic plugin-edge endpoints

Same pattern for `edge_labels`. The plugin declares `(source_label, edge_label, target_label)` tuples in its manifest; the host exposes:

```
GET    /admin/plugins/{slug}/edges/{label}
POST   /admin/plugins/{slug}/edges/{label}
DELETE /admin/plugins/{slug}/edges/{label}/{source_id}/{target_id}
```

Plus endpoints anchored on a target node (e.g. `GET /admin/environments/{slug}/plugin-edges/{plugin}/{label}`) for the "show me the AWS account linked to this environment" view.

### 3. Manifest-driven admin UI

`imbi-ui` consumes the plugin manifest and renders generic admin surfaces:

- A list page per `(plugin, label)` pair, fed by the generic CRUD endpoints.
- A detail card per `(target_label, edge_label, plugin_label)` triple, mounted on the target node's detail page.

Form fields derive from the JSON Schema; no hand-coded TS types. The sidebar in `Admin.tsx` enumerates entity labels from the active plugin set.

### 4. Existing hand-coded surfaces are migrated, not preserved in parallel

`aws_accounts.py`, `AwsAccountsManagement.tsx`, and the AWS-specific tail of `environments.py` are removed once the generic surface is in place. There is no shim; the URLs change from `/admin/aws-accounts/*` to `/admin/plugins/aws-iam-ic/entities/AwsAccount/*`. v2 is alpha; we don't owe backward compatibility on admin URLs.

## Consequences

### Positive

- Adding a new plugin entity type is a manifest change plus a JSON Schema, not a new router and a new UI page.
- The host stops accumulating plugin-specific files. The "plugin abstraction" stops leaking back into core.
- The permission model is uniform across plugins: `plugins:{slug}:entities:{label}:write` rather than ad-hoc per-entity permissions.

### Negative

- The generic surface is necessarily less polished than a hand-built one for any single entity. Fancy widgets (custom maps, charts, special validators) need to be earned with extension hooks; the default is "render the JSON Schema."
- Bug fixes in the generic surface affect every plugin that uses it. That's good in aggregate, bad in the rare case where a plugin needs different behavior. Plugin-specific overrides are a Phase-2 escape hatch, not a v1 feature.
- JSON Schema does not cover everything a relational schema would (joins, computed columns). The generic CRUD layer is for plugin-owned entities only — first-class domain entities (`Project`, `Environment`, etc.) stay in their bespoke routers.

### Risks Accepted

- **Auth granularity**: derived permissions can balloon if plugins declare many vertex labels. We accept that and rely on role grouping in the seed.
- **UI escape hatches**: a plugin author who needs a custom widget today has no path. The right time to design extension points is when the second plugin asks for one; until then, ship the generic surface and resist premature configurability.

## References

- [`imbi/docs/plugin-entity-abstraction-plan.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/plugin-entity-abstraction-plan.md) — Full plan, including the layered refactor and the audit of host-side AWS-specific code.
- [`imbi/docs/plugin-abstraction-followups.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/plugin-abstraction-followups.md) — Deferred follow-ups from the simplify review.
- ADR 0008: Plugin System Architecture
- ADR 0010: Identity Plugin Architecture
