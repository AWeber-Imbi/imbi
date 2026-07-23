# ADR 0008: Plugin System Architecture

## Status

Accepted

Implementation in progress. Source design lives in [`imbi/docs/plugin-system-prd.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/plugin-system-prd.md) and [`imbi/docs/plugin-system-implementation-plan.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/plugin-system-implementation-plan.md).

## Context

Imbi needs to surface data from a long tail of external systems — AWS SSM, Vault, Consul, CloudWatch Logs, Logz.io, GitHub, PagerDuty, SonarQube, and more — and different organizations route different project types to different backends. The Project Details screen has unimplemented Configuration and Logs tabs that need to bind to whatever backend each project type uses, not a single global integration.

A few constraints shaped this decision:

1. **Imbi is a SaaS IDP**. Integrations must be authorable, distributable, and configurable by third parties without modifying Imbi core.
2. **Stability matters**. Plugin authors must be able to ship independently of the Imbi release cadence, so the contract has to be versioned.
3. **One vendor, multiple capabilities**. A single package like `imbi-plugin-aws` legitimately exposes SSM (configuration), CloudWatch Logs (logs), Secrets Manager (future), and IAM IC (identity) — all sharing one AWS account's credentials. The model must support this natively rather than forcing one service record per capability.
4. **Operator UX matters**. Installation and configuration of plugins should happen from the admin UI; project-level binding is also operator-driven.

Hardcoding integrations in core (the v1 approach) does not satisfy any of these constraints.

## Decision

### 1. Plugins are standalone Python packages discovered via entry points

Each plugin is a separately-versioned Python distribution that registers handler classes under the `imbi.plugins` entry-point group. At startup, `imbi-api` builds a registry by enumerating that group.

```toml
[project.entry-points."imbi.plugins"]
ssm = "imbi_plugin_ssm:SSMPlugin"
```

A single package may register multiple entry points (e.g. `imbi-plugin-aws` registers `aws-ssm`, `aws-cloudwatch-logs`, `aws-iam-ic`).

### 2. Manifests live on the handler class, not in `pyproject.toml`

Each handler class declares a `PluginManifest` `ClassVar`. Wheels do not ship `pyproject.toml`, so manifests must live in importable Python. The `[tool.imbi.plugin]` table in `pyproject.toml` is build-time documentation only.

### 3. Three graph node types model installed plugins

```
ThirdPartyService                         (e.g. "AWS Production")
  └── ServiceApplication                  (encrypted credentials shared across capabilities)
  └── HAS_PLUGIN → Plugin (slug=aws-ssm,           plugin_type=configuration, options={...})
  └── HAS_PLUGIN → Plugin (slug=aws-cloudwatch-logs, plugin_type=logs,        options={...})

ProjectType -[:USES_PLUGIN {tab, default, search_template, identity_plugin_id?}]→ Plugin
Project     -[:USES_PLUGIN {tab, default, ...}]→ Plugin         (overrides/additions)
```

- **`ThirdPartyService`** carries the vendor identity and per-tenant config (account, region, base URL).
- **`ServiceApplication`** carries the encrypted credentials, shared by every capability on the same service.
- **`Plugin`** is one installed capability — what gets bound to projects and project types. Multiple `Plugin` nodes hang off one `ThirdPartyService` when the package registers multiple entry points.

### 4. Resolution is graph traversal

To handle a request like `GET /orgs/{org}/projects/{id}/configuration`:

1. Merge `USES_PLUGIN` edges from the project and its project type by `(tab, plugin_node_id)`. Project edges win on conflict.
2. Select the target `Plugin` via `?source=<plugin_slug>` or the `default=true` edge.
3. Traverse `HAS_PLUGIN` to the `ThirdPartyService`; fetch credentials from the linked `ServiceApplication`.
4. Look up the handler class from the registry; check `api_version` compatibility.
5. Instantiate the handler with the plugin's `options` plus decrypted credentials and a `PluginContext`.
6. Delegate the request; return the normalized response.

### 5. Plugin types are explicit and grow incrementally

Initial types: `configuration`, `logs`. New types (`identity` — ADR 0010, `deployment`) are added one at a time, each with a documented protocol. The Plugin contract uses `plugin_type` as a discriminator for the handler interface.

### 6. Dynamic reload, not hot patch

Plugin installation triggers a registry rebuild without a full service restart, but in-flight requests finish against the previously loaded handler. There is no attempt at module-level hot-patching.

### 7. First-party reference plugins ship in a curated catalog

`imbi-plugin-ssm`, `imbi-plugin-logzio`, `imbi-plugin-aws`, `imbi-plugin-github`, `imbi-plugin-oidc`. A hosted marketplace is a Phase-2 goal; the initial catalog is curated.

## Consequences

### Positive

- Third parties can author and version integrations independently of Imbi core.
- One AWS account record can back configuration, logs, and identity capabilities without duplication.
- Per-project overrides let a single project flow logs to both CloudWatch and Logz.io.
- The handler contract is small and versioned (`api_version`), so plugin authors can target stable surface area.

### Negative

- Operators have a multi-step install flow: register the `ThirdPartyService`, attach credentials, link `Plugin` rows. ADR 0012 (Plugin Manifest Third-Party Service Template) reduces this to one-click for vendor-known boilerplate.
- Handler-class manifests duplicate metadata that's also useful at install time (read from the wheel before instantiation). The `PluginManifest` is `ClassVar` so a class import is enough; no eager handler construction is required.
- Graph traversal at request time costs more than a static dispatch. Acceptable for tab loads; not used in any hot path.

### Risks Accepted

- A bad plugin can crash the API process. Sandboxing is out of scope; the SaaS deployment model relies on the curated catalog as the trust boundary.
- API-version compatibility is enforced at registry-build time, but plugin authors must respect semver discipline. Breaking changes to the contract are tracked as new `api_version` values; the registry refuses to load plugins outside the supported range.

## References

- [`imbi/docs/plugin-system-prd.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/plugin-system-prd.md) — Full PRD, including manifest schema and handler protocols.
- [`imbi/docs/plugin-system-implementation-plan.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/plugin-system-implementation-plan.md) — Implementation mapping onto the current codebase.
- [`imbi/docs/plugin-entity-abstraction-plan.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/plugin-entity-abstraction-plan.md) — Generic plugin-entity CRUD for declared vertex/edge labels.
- ADR 0010: Identity Plugin Architecture
- ADR 0012: Plugin Manifest Third-Party Service Template
