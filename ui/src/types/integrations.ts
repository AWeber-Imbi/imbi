// Plugin Architecture v3 — Integrations, plugins, and capabilities.
//
// The API-surface types resolve through the generated schemas. The manifest
// side stays hand-authored, mirroring `imbi_common.plugins.base`: plugin
// manifests, capabilities, options, packages, credential fields, and the
// project-service edge are internal plugin models with no OpenAPI schema at
// all, so there is nothing to generate from. Keep those in sync with the
// backend by hand.
//
// `Integration` was hand-written for a different reason until recently: the
// blueprint schema writer emitted the graph node under the name
// `IntegrationResponse`, displacing the endpoint's own response model, so the
// published schema described a shape no endpoint returned. That is fixed --
// blueprint output is namespaced now -- and `Integration` resolves through
// the schema again.
//
// Three nouns:
//   - Plugin       — an installed Python package (read-only from the UI).
//   - Integration  — an org-owned, named, configured instance of a plugin.
//   - Capability   — a toggleable behavior of an Integration.

import type { components } from './api-generated'

// ---------------------------------------------------------------------------
// Capabilities
// ---------------------------------------------------------------------------

// A capability's project-type assignment. Zero assignments for an enabled,
// project-scoped capability means "all project types" (default_all).
//
// `options` / `env_payloads` are restored to required. The API declares both
// with `default_factory=dict`, which Pydantic does not emit as a schema
// `default`, so the generated type calls them optional even though every
// response carries them. Same artifact as `MCPServer.ignored_tools`.
export type CapabilityAssignment = Schemas['CapabilityAssignment'] & {
  env_payloads: Record<string, Record<string, unknown>>
  options: Record<string, unknown>
}

export type CapabilityAssignmentsUpdate = {
  assignments: CapabilityAssignment[]
}

// The platform's fixed capability vocabulary (imbi_common CapabilityKind).
export type CapabilityKind =
  | 'analysis'
  | 'commit-sync'
  | 'configuration'
  | 'deployment'
  | 'identity'
  | 'incidents'
  | 'lifecycle'
  | 'logs'
  | 'pr-sync'
  | 'tools'
  | 'webhook-actions'

export type CapabilitySurface = 'api' | 'tools' | 'ui' | 'webhook'

// Per-capability enabled state + options on an Integration. Keyed by
// CapabilityKind in `Integration.capabilities`.
export type CapabilityToggle = Schemas['CapabilityToggle']

// ---------------------------------------------------------------------------
// Integrations (leads with the plugin credential field they configure)
// ---------------------------------------------------------------------------

// A write-only credential field declared once per plugin (manifest level).
export interface CredentialField {
  description?: null | string
  label: string
  // Whether the value is multi-line (e.g. a PEM private key) → textarea.
  multiline?: boolean
  name: string
  required: boolean
  // Whether the value is sensitive. Non-secret fields (e.g. a GitHub App id)
  // render as plain text instead of a masked password input and their value
  // is echoed back for display. Defaults to secret when the backend omits it.
  secret?: boolean
}

// GET /organizations/{org}/integrations → IntegrationResponse. `id` is null
// only for legacy integrations created before ids were persisted; the identity
// connect flow targets it. `credential_values` holds populated, non-secret
// credential values for display -- secrets never leave the server.
export type Integration = Schemas['IntegrationResponse']

export interface IntegrationCreate {
  capabilities?: Record<string, CapabilityToggle>
  category?: null | string
  credentials?: Record<string, string>
  description?: null | string
  icon?: null | string
  identifiers?: Record<string, number | string>
  links?: Record<string, string>
  name: string
  options?: Record<string, unknown>
  plugin: string
  service_url?: null | string
  slug: string
  status?: IntegrationStatus
  vendor?: null | string
}

export type IntegrationStatus =
  | 'active'
  | 'deprecated'
  | 'evaluating'
  | 'inactive'

export interface IntegrationUpdate {
  capabilities?: null | Record<string, CapabilityToggle>
  category?: null | string
  description?: null | string
  icon?: null | string
  identifiers?: null | Record<string, number | string>
  links?: null | Record<string, string>
  name?: null | string
  options?: null | Record<string, unknown>
  service_url?: null | string
  status?: IntegrationStatus | null
  vendor?: null | string
}

// ---------------------------------------------------------------------------
// Plugin manifest (drives the connection + capability forms)
// ---------------------------------------------------------------------------

// A capability as declared by a plugin manifest.
export interface PluginCapability {
  default_enabled: boolean
  description?: null | string
  hints: Record<string, unknown>
  kind: CapabilityKind
  label: string
  options: PluginOption[]
  project_scoped: boolean
  requires_identity: boolean
  ui_module?: null | string
}

// The full plugin manifest (GET /plugins/{slug}/manifest).
export interface PluginManifest {
  api_version: number
  auth_type: string
  capabilities: PluginCapability[]
  credentials: CredentialField[]
  data_types: Record<string, unknown>[]
  description?: null | string
  edge_labels: Record<string, unknown>[]
  // Brand/display icon in `library-icon-name` form (e.g. `si-github`,
  // `tabler-aws`, or a Lucide name); null falls back to a generic glyph.
  icon?: null | string
  name: string
  options: PluginOption[]
  slug: string
  vertex_labels: Record<string, unknown>[]
}

// An integration-level option OR a capability-level option, declared by the
// plugin manifest.
export interface PluginOption {
  choices?: null | string[]
  default?: boolean | null | number | Record<string, string> | string
  description?: null | string
  label: string
  name: string
  required: boolean
  type: PluginOptionType
}

export type PluginOptionType =
  | 'boolean'
  | 'integer'
  | 'mapping'
  | 'secret'
  | 'string'

// An installed plugin package (GET /admin/plugins → InstalledPluginResponse).
// The manifest plus package identity and the system-wide enabled flag.
// (Named PluginPackage to avoid colliding with the app-wide v2 `InstalledPlugin`
// type still consumed by project/dashboard surfaces outside this feature.)
export interface PluginPackage extends PluginManifest {
  enabled: boolean
  package_name: string
  package_version: string
}

// ---------------------------------------------------------------------------
// Project-level integration assignments (per-capability USES override)
// ---------------------------------------------------------------------------

// `options` / `env_payloads` restored to required for the same reason as on
// CapabilityAssignment.
export type ProjectIntegrationAssignment =
  Schemas['ProjectIntegrationAssignment'] & {
    env_payloads: Record<string, Record<string, unknown>>
    options: Record<string, unknown>
  }

export type ProjectIntegrationsUpdate = {
  assignments: ProjectIntegrationAssignment[]
}

// ---------------------------------------------------------------------------
// Project ↔ integration link (EXISTS_IN edge)
// ---------------------------------------------------------------------------

// A project's EXISTS_IN edge to an Integration (v3). Served by
// GET/POST /organizations/{org}/projects/{project_id}/services/.
export interface ProjectServiceEdge {
  canonical_url?: null | string
  dashboard_url?: null | string
  identifier: string
  integration_name: string
  integration_slug: string
}

export interface ProjectServiceEdgeCreate {
  canonical_url?: null | string
  dashboard_url?: null | string
  identifier: string
  integration_slug: string
}

type Schemas = components['schemas']
