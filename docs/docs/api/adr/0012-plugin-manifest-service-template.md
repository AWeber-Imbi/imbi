# ADR 0012: Plugin Manifest Third-Party Service Template

## Status

Accepted

Source design lives in [`imbi/docs/third-party-service-manifest-plan.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/third-party-service-manifest-plan.md).

## Context

The plugin system (ADR 0008) requires three operator actions to make a plugin usable after installation:

1. Create a `ThirdPartyService` record with the right `vendor`, `category`, `service_url`, `api_endpoint`, `authorization_endpoint`, `token_endpoint`, `revoke_endpoint`, `use_pkce`, and `links`.
2. Attach a `ServiceApplication` carrying credentials.
3. Wire `(:ThirdPartyService)-[:HAS_PLUGIN]->(:Plugin)`.
4. Hunt down a logo asset, host it somewhere, and paste the URL into `ThirdPartyService.icon`.

Steps 1 and 4 are pure boilerplate: every plugin author already knows the vendor and the OAuth endpoints, and ships a brand mark with the package. Re-entering that information for every install is friction and a source of mistakes. Step 2 is genuinely operator-owned (tenant credentials), and step 3 is mechanical once 1 and 2 are done.

We need a way for plugins to declare the vendor-known data once — without ever carrying secrets — and have the host auto-provision the boilerplate.

## Decision

### 1. Plugin manifests declare a `third_party_service` template

`PluginManifest` gains a `third_party_service` block describing the vendor, category, endpoints, PKCE preference, and link metadata for the service this plugin connects to.

### 2. Plugin manifests declare an embedded `icon` asset

`PluginManifest` gains an `icon: PluginIcon` field referencing a file shipped inside the wheel via `importlib.resources`:

```python
class PluginIcon(pydantic.BaseModel):
    package: str            # e.g. 'imbi.plugins.github'
    resource: str           # e.g. 'assets/icon.svg'
    media_type: Literal['image/svg+xml', 'image/png', 'image/webp'] = 'image/svg+xml'
```

The icon must be ≤ 64 KiB after read; SVGs pass a sanitizer that strips `<script>`, `<foreignObject>`, and external references before being stored.

### 3. Install-time auto-provisioning

On plugin install, the host:

1. Reads the manifest's `third_party_service` template.
2. Looks for an existing `ThirdPartyService` matching the template's `vendor` + service identity. If found, attach to it. If not, create one from the template.
3. Copies the icon out of the package, sanitizes it, persists it via `imbi.api.storage`, and sets `ThirdPartyService.icon` to the served URL.
4. Creates the `(:ThirdPartyService)-[:HAS_PLUGIN]->(:Plugin)` edge.

### 4. Multiple entry points share one service record

Plugins that share a template ID share the underlying `ThirdPartyService`. `imbi-plugin-aws`'s `aws-ssm`, `aws-cloudwatch-logs`, and `aws-iam-ic` all declare the same template and end up linked to one `ThirdPartyService` (one set of credentials, three capabilities).

### 5. Manifests carry no secrets

Manifest validation rejects any field that looks like a secret (client IDs, client secrets, API tokens, signing keys, anything in a credential-shaped dict). The `ServiceApplication` is **not** auto-created. Operators continue to attach credentials manually (per ADR 0009 for OAuth providers; per ADR 0008 for other capabilities).

### 6. Re-install does not overwrite operator edits

By default, re-installing or upgrading a plugin never overwrites operator-edited fields on the existing `ThirdPartyService`. Operators can opt a service into "managed by manifest" if they want manifest changes to flow through on upgrade.

## Consequences

### Positive

- One-click install replaces a multi-step setup for the common path.
- Icons live with the plugin author; no per-tenant logo hosting.
- Capabilities from the same vendor naturally consolidate on one service record, matching ADR 0008's "one credential set, many capabilities" model.

### Negative

- Manifest validation needs a real secret-shape detector — string-pattern heuristics are fine for shipping, but the long-tail (`signing_key`, `pem`, etc.) needs explicit denylist maintenance.
- "Managed by manifest" is a per-service opt-in. Operators who want manifest changes to flow through have to remember to toggle it; default-safe wins over default-auto.
- Icon sanitization is a hard problem in SVG. A strict SVG profile (denylist `<script>`, `<foreignObject>`, external `href`, JS event handlers) is enforced; that rules out some legitimate SVGs but it's the boundary required for an admin-shown logo.

### Risks Accepted

- **Vendor identity collision**: two plugins from different packages might describe overlapping vendor templates. First-install wins; subsequent installs attach to the existing record. Operators can split records by hand if the templates genuinely should not collapse.
- **Cross-tenant template sharing**: explicitly out of scope. The template is read at install time per Imbi instance; no marketplace-side template registry.
- **Marketplace UX**: the existing Admin → Plugin Catalog flow grows a "preview & install" step but the page layout doesn't change. A bigger redesign is a separate, later decision.

## References

- [`imbi/docs/third-party-service-manifest-plan.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/third-party-service-manifest-plan.md) — Full plan, including manifest schema additions and install flow.
- [`imbi/docs/plugin-service-application-link-plan.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/plugin-service-application-link-plan.md) — Linking plugin instances to a `ServiceApplication`.
- ADR 0008: Plugin System Architecture
- ADR 0009: Database-Driven OAuth Provider Configuration
