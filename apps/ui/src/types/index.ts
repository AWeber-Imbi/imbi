import type { components } from './api-generated'

export type ActivityFeedEntry = OperationsLogEntry | ProjectFeedEntry

// API Response Types
// `ApiStatus` is the UI-facing status envelope (richer than the backend
// `StatusResponse` — includes `started_at` and optional `system` metadata).
export interface ApiStatus {
  started_at: string
  status: 'maintenance' | 'ok'
  system?: {
    language: {
      implementation: string
      name: string
      version: string
    }
    os: {
      name: string
      version: string
    }
  }
  version: string
}

// API Response Wrappers
export interface CollectionResponse<T> {
  data: T[]
}

// `Environment` tracks the full response shape (with relationships).
// Add a UI-only `url` passthrough — it's surfaced in ProjectEnvironmentsCard
// but not part of the Environment schema itself.
export type Environment = Schemas['EnvironmentResponse'] & {
  url?: null | string
}

// `EnvironmentCreate` stays hand-written: the generated `EnvironmentRequest`
// requires updated_at/description/icon/label_color be explicitly set to
// `string|null`, which the UI create form doesn't do.
export interface EnvironmentCreate {
  [key: string]: unknown
  description?: null | string
  icon?: null | string
  label_color?: null | string
  name: string
  slug: string
  sort_order?: null | number
}

export type LinkDefinition = Schemas['LinkDefinitionResponse']

export type LinkDefinitionCreate = Schemas['LinkDefinitionCreate']
// Activity feed projection; distinct from `OperationsLogRecord`.
export interface OperationsLogEntry {
  change_type:
    | 'Configured'
    | 'Decommissioned'
    | 'Deployed'
    | 'Migrated'
    | 'Provisioned'
    | 'Restarted'
    | 'Rolled Back'
    | 'Scaled'
    | 'Upgraded'
  completed_at?: null | string
  description: string
  display_name: string
  email_address: string
  environment: string
  id: number
  link?: null | string
  notes?: null | string
  occurred_at: string
  performed_by?: null | string
  project_id?: null | number
  project_name?: null | string
  recorded_at: string
  recorded_by: string
  ticket_slug?: null | string
  type: 'OperationsLogEntry'
  version?: null | string
}

// `Project` keeps its hand-written shape: it has UI-only convenience fields
// (`project_type`, `[key: string]: unknown` for blueprint-defined extras) and
// a looser `relationships` shape than the generated `ProjectResponse`.
export interface Project {
  [key: string]: unknown
  created_at?: null | string
  description?: null | string
  environments?: Environment[]
  icon?: null | string
  id: string
  identifiers?: Record<string, number | string>
  links?: Record<string, string>
  name: string
  project_type?: {
    name: string
    organization: {
      name: string
      slug: string
    }
    slug: string
  }
  project_types?: {
    icon?: null | string
    name: string
    organization: {
      name: string
      slug: string
    }
    slug: string
  }[]
  relationships?: {
    environments?: RelationshipLink
    href?: string
    inbound_count?: number
    outbound_count?: number
    team?: RelationshipLink
  }
  score?: null | number
  slug: string
  team: {
    name: string
    organization: {
      name: string
      slug: string
    }
    slug: string
  }
  updated_at?: null | string
}

// `ProjectCreate` stays hand-written: the UI sends `environment_slugs` (a
// flat slug list) whereas the generated `ProjectCreate` expects an
// `environments` map of edge-property dicts + a required `project_type_slugs`.
export interface ProjectCreate {
  [key: string]: unknown
  description?: null | string
  environment_slugs?: string[]
  icon?: null | string
  identifiers?: Record<string, number | string>
  links?: Record<string, string>
  name: string
  slug: string
  team_slug: string
}

// Activity feed projection for the dashboard — not a 1:1 backend shape.
export interface ProjectFeedEntry {
  display_name: string
  email_address: string
  namespace: string
  namespace_id: number
  occurred_at?: string
  project_id: number
  project_name: string
  project_type: string
  type: 'ProjectFeedEntry'
  what: 'created' | 'updated' | 'updated facts'
  when?: string
  who: string
}

export type ProjectType = Schemas['ProjectTypeResponse']

// `ProjectTypeCreate` stays hand-written: no generated counterpart — the API
// mounts project-type creation via the generic org scoped endpoint.
export interface ProjectTypeCreate {
  [key: string]: unknown
  description?: null | string
  icon?: null | string
  name: string
  slug: string
}

export type RelationshipLink = Schemas['RelationshipLink']

export interface ScoringPolicy {
  attribute_name: string
  category: 'attribute'
  description?: null | string
  enabled: boolean
  id: string
  name: string
  priority: number
  range_score_map?: null | Record<string, number>
  slug: string
  targets?: string[]
  value_score_map?: null | Record<string, number>
  weight: number
}

export interface ScoringPolicyCreate {
  attribute_name: string
  description?: null | string
  enabled: boolean
  name: string
  priority: number
  range_score_map?: null | Record<string, number>
  slug: string
  targets: string[]
  value_score_map?: null | Record<string, number>
  weight: number
}

// `User` is the UI-side profile shape used by auth/session consumers.
// It does not map cleanly to the backend `UserResponse` (different key set:
// UI tracks `username`/`user_type`; backend exposes `email`-keyed users).
export interface User {
  display_name: string
  email: string
  email_address?: string
  external_id?: string
  groups?: string[]
  user_type: string
  username: string
}

type Schemas = components['schemas']

export const OPERATIONS_LOG_ENTRY_TYPES = [
  'Configured',
  'Decommissioned',
  'Deployed',
  'Migrated',
  'Provisioned',
  'Restarted',
  'Rolled Back',
  'Scaled',
  'Upgraded',
] as const

export interface AdminPluginsResponse {
  installed: InstalledPlugin[]
}

export type AdminSettings = Schemas['AdminSettings']

// `AdminUser` stays hand-written: no generated counterpart — the UI
// composite flattens group/role/org memberships.
export interface AdminUser {
  avatar_url?: null | string
  created_at: string
  display_name: string
  email: string
  email_notifications: boolean
  is_active: boolean
  is_admin: boolean
  is_service_account: boolean
  last_login?: null | string
  organizations?: OrgMembership[]
  roles: Role[]
}

export type AdminUserCreate = Schemas['UserCreate'] & {
  email_notifications?: boolean
  organizations?: { organization_slug: string; role: string }[]
}

export type AdminUserUpdate = Schemas['UserUpdate']

// API Key types
export type ApiKey = Schemas['APIKeyResponse']

export type ApiKeyCreated = Schemas['APIKeyCreateResponse']

export type AuthProvider = Schemas['AuthProvider']

// Auth Types
export interface AuthState {
  isAuthenticated: boolean
  isLoading: boolean
  user: null | User
}

export type Blueprint = Schemas['Blueprint-Output']

// `BlueprintCreate` stays hand-written: generated `Blueprint-Input` types
// `json_schema` as the full `Schema-Input` AST, but the UI passes a
// `Record<string, unknown>` (parsed JSON) and includes an `id`/timestamps
// on read-round-trip shapes.
export interface BlueprintCreate {
  description?: null | string
  edge?: null | string
  enabled?: boolean
  filter?: BlueprintFilter | null
  json_schema: Record<string, unknown>
  kind?: 'node' | 'relationship'
  name: string
  priority?: number
  slug?: string
  source?: null | string
  target?: null | string
  type?: null | string
  version?: number
}

// Blueprint types
export type BlueprintFilter = Schemas['BlueprintFilter']

export type ClientCredential = Schemas['ClientCredentialResponse']

export type ClientCredentialCreate = Schemas['ClientCredentialCreate']

export type ClientCredentialCreated = Schemas['ClientCredentialCreateResponse']

export interface ConfigKeyResponse {
  data_type: string
  key: string
  last_modified: null | string
  secret: boolean
}

export interface ConfigKeyValueResponse extends ConfigKeyResponse {
  value: unknown
}

export interface CurrentReleaseEnvironment {
  current_status: DeploymentStatus | null
  environment: { name: string; slug: string }
  last_event_at: null | string
  release: null | Release
}

export interface DashboardStats {
  projects_by_namespace: Record<string, number>
  projects_by_type: Record<string, number>
  recent_activity: ActivityFeedEntry[]
  total_projects: number
}

// Releases
export type DeploymentStatus =
  | 'failed'
  | 'in_progress'
  | 'pending'
  | 'rolled_back'
  | 'success'

export interface IdentityConnectionPollResponse {
  return_to?: null | string
  status: 'complete' | 'pending'
}

export interface IdentityConnectionResponse {
  connects_users_to: null | string
  expires_at: null | string
  id: string
  last_used_at: null | string
  metadata: Record<string, unknown>
  plugin_id: string
  plugin_label: null | string
  plugin_slug: string
  scopes: string[]
  status: IdentityConnectionStatus
  subject: string
}

export interface IdentityConnectionStartRequest {
  return_to?: null | string
  scopes?: null | string[]
}

export interface IdentityConnectionStartResponse {
  authorization_url: string
  polling: IdentityPollingDescriptor | null
  state: string
}

export type IdentityConnectionStatus = 'active' | 'expired' | 'revoked'

export interface IdentityPollingDescriptor {
  expires_in: number
  interval: number
  user_code: string
  verification_uri: string
  verification_uri_complete: null | string
}

export interface InstalledPlugin {
  api_version: number
  auth_type: 'api_token' | 'aws-iam-ic' | 'oauth2' | 'oidc'
  cacheable: boolean
  credentials: PluginCredentialField[]
  description: string
  docs_url: null | string
  edge_labels?: PluginEdgeLabel[]
  enabled: boolean
  // Brand glyph inherited from the parent ThirdPartyService (an icon
  // registry value or URL).  Null when the plugin isn't attached to
  // any service yet.
  icon?: null | string
  // login_capable / requires_identity ride along on the manifest. The
  // legacy Phase-1 catalog plugins (ssm, logzio) leave them at false;
  // the Phase-2 identity plugins (oidc, github*, aws-iam-ic) set
  // login_capable=true.
  login_capable?: boolean
  name: string
  options: PluginOptionDef[]
  package_name: string
  package_version: string
  plugin_type?: 'identity' | PluginTab
  requires_identity?: boolean
  slug: string
  supported_tabs: PluginTab[]
  vertex_labels?: PluginVertexLabel[]
  // Body copy shown on the dashboard "unconnected integration" widget.
  // Resolved server-side (override > manifest > null).  ``_default`` is
  // the manifest value; ``_override`` is the operator-set value (null
  // means "inherit").
  widget_text?: null | string
  widget_text_default?: null | string
  widget_text_override?: null | string
}

// Admin local-auth (password login) toggle.
// Hand-written: the admin endpoints aren't in the committed openapi.json
// snapshot yet. Mirrors `LocalAuthRead` in
// imbi_api/endpoints/local_auth.py.
export interface LocalAuthConfig {
  enabled: boolean
  updated_at: string
}

export interface LogEntryResponse {
  level: null | string
  message: string
  raw: Record<string, unknown>
  timestamp: string
}

export interface LogHistogramBucket {
  count: number
  levels: Record<string, number>
  timestamp: string
}

export interface LoginProviderCreate {
  allowed_domains?: string[]
  client_id: string
  client_secret: string
  description?: null | string
  issuer_url?: null | string
  // name/slug/org_slug/third_party_service_slug are derived server-side
  // from oauth_app_type when omitted; the auth-providers admin UI
  // doesn't expose them.
  name?: string
  oauth_app_type: OAuthAppType
  org_slug?: string
  scopes?: string[]
  slug?: string
  third_party_service_slug?: string
  usage: 'both' | 'login'
}

export interface LoginProviderRead {
  allowed_domains: string[]
  authorization_endpoint: null | string
  callback_url: string
  client_id: null | string
  description: null | string
  has_secret: boolean
  issuer_url: null | string
  name: string
  oauth_app_type: null | OAuthAppType
  organization_name: null | string
  organization_slug: null | string
  revoke_endpoint: null | string
  scopes: string[]
  slug: string
  status: string
  third_party_service_name: null | string
  third_party_service_slug: null | string
  token_endpoint: null | string
  usage: 'both' | 'login'
}

export interface LoginProviderUpdate {
  allowed_domains?: string[]
  // Empty string preserves existing secret on the server.
  client_id: string
  client_secret?: null | string
  description?: null | string
  issuer_url?: null | string
  name: string
  oauth_app_type: OAuthAppType
  scopes?: string[]
  usage: 'both' | 'login'
}

export interface LoginRequest {
  email: string
  password: string
}

export interface LogResultResponse {
  entries: LogEntryResponse[]
  next_cursor: null | string
  total: null | number
}

export interface Note {
  content: string
  created_at: string
  created_by: string
  id: string
  is_pinned: boolean
  project_id: string
  tags: TagRef[]
  title: string
  updated_at?: null | string
  updated_by?: null | string
}

export interface NoteCreate {
  content: string
  tags?: string[]
  title: string
}

export type NoteListResponse = CollectionResponse<Note>

// Note Templates. Inlined for the same reason as Note/Tag — the committed
// openapi.json snapshot predates these endpoints. Switch to
// `Schemas['NoteTemplateResponse']` etc. once the snapshot is refreshed.
export interface NoteTemplate {
  content: string
  created_at: string
  description?: null | string
  icon?: null | string
  id: string
  name: string
  organization: { name: string; slug: string }
  project_type_slugs: string[]
  slug: string
  sort_order: number
  tags: TagRef[]
  title?: null | string
  updated_at?: null | string
}

export interface NoteTemplateCreate {
  content?: string
  description?: null | string
  icon?: null | string
  name: string
  project_type_slugs?: string[]
  slug: string
  sort_order?: number
  tags?: string[]
  title?: null | string
}

// Auth provider types — mirror the consolidated `ServiceApplication`-backed
// shape in imbi_api/endpoints/auth_providers.py.
export type OAuthAppType = 'github' | 'google' | 'oidc'

export type OperationsLogEntryType = (typeof OPERATIONS_LOG_ENTRY_TYPES)[number]

export interface OperationsLogFilters {
  entry_type?: OperationsLogEntryType
  environment_slug?: string
  performed_by?: string
  project_slug?: string
  since?: string
  ticket_slug?: string
  until?: string
}

// Raw record returned by the /operations-log/ API (distinct from the
// activity-feed projection defined above in `OperationsLogEntry`).
export type OperationsLogRecord = Schemas['OperationLogResponse']

// Organization types
export type Organization = Schemas['OrganizationResponse']

// `OrganizationCreate` stays hand-written: the generated
// `OrganizationRequest` requires `updated_at`/`description`/`icon` be
// present (nullable), which the UI create form doesn't send.
export interface OrganizationCreate {
  description?: null | string
  icon?: null | string
  name: string
  slug: string
}

export type OrgMembership = Schemas['OrgMembership']

// JSON Patch operation (RFC 6902)
export type PatchOperation = Schemas['PatchOperation']

// Admin User Management Types (matching API schema)
export type Permission = Schemas['Permission']

export interface PluginAssignmentCreate {
  default: boolean
  identity_plugin_id?: null | string
  options?: Record<string, unknown>
  plugin_id: string
  tab: PluginTab
}
export interface PluginAssignmentInput {
  default: boolean
  identity_plugin_id?: null | string
  options: Record<string, unknown>
  project_type_slug: string
  tab: PluginTab
}
export interface PluginAssignmentResponse {
  default: boolean
  identity_plugin_id?: null | string
  label: string
  options: Record<string, unknown>
  plugin_id: string
  plugin_slug: string
  source: 'merged' | 'project' | 'project_type'
  supports_histogram?: boolean
  tab: PluginTab
}

export interface PluginAssignmentRow {
  default: boolean
  identity_plugin_id?: null | string
  options: Record<string, unknown>
  project_type_name: string
  project_type_slug: string
  tab: PluginTab
}

export interface PluginConfigurationResponse {
  auth_type: 'api_token' | 'oauth2'
  fields: PluginCredentialField[]
  plugin_slug: string
  populated: string[]
}
export interface PluginCreate {
  label: string
  options?: Record<string, unknown>
  plugin_slug: string
  service_application_slug?: null | string
}
export interface PluginCredentialField {
  description: null | string
  label: string
  name: string
  required: boolean
}

// A materialized edge from /edges/{rel_type}.
export interface PluginEdge {
  properties: Record<string, unknown>
  rel_type: string
  target: PluginEntity
  target_label: string
}
export interface PluginEdgeLabel {
  from_labels: string[]
  name: string
  properties?: Record<string, string>
  to_labels: string[]
}

export interface PluginEdgePut {
  properties?: Record<string, unknown>
  target_id: string
  target_label: string
}

// Generic plugin entity (a graph node declared by a plugin's
// vertex_labels manifest entry).  Shape varies per plugin model_ref;
// the host returns whatever Pydantic.model_dump() produced.
export type PluginEntity = Record<string, unknown> & { id: string }

export interface PluginEntityCreate {
  [key: string]: unknown
}

export interface PluginEntitySchema {
  description?: string
  properties: Record<string, Record<string, unknown>>
  required?: string[]
  title?: string
  type: 'object'
}
export interface PluginOptionDef {
  choices?: null | string[]
  default?: boolean | null | number | string
  description: null | string
  label: string
  name: string
  required: boolean
  type: 'boolean' | 'integer' | 'secret' | 'string'
}

// Plugin types (hand-written until api-generated.ts snapshot is refreshed)
export interface PluginResponse {
  api_version: number
  application_name?: null | string
  application_slug?: null | string
  connects_users_to?: null | string
  id: string
  identity_plugin_id?: null | string
  label: string
  login_capable?: boolean
  options: Record<string, unknown>
  plugin_slug: string
  service_slug: null | string
  status: 'active' | 'unavailable'
  used_as_login?: boolean
}
export type PluginTab = 'configuration' | 'logs'
export interface PluginUpdate {
  // Pass an explicit empty string to clear; omitting the field leaves
  // the existing value untouched on the backend.
  identity_plugin_id?: null | string
  label: string
  options?: Record<string, unknown>
  // Tri-state: omit to leave the link alone, ``null`` to clear, a slug
  // to set/replace the linked ServiceApplication.
  service_application_slug?: null | string
}
export interface PluginVertexLabel {
  // Resolved (override-or-manifest) operator-facing display fields.
  description?: null | string
  display_name?: null | string
  indexes?: { fields: string[]; unique: boolean }[]
  model_ref: string
  name: string
  nav_label?: null | string
  // Operator-set values for the override fields (null/missing = inherit
  // from the manifest default).
  overrides?: {
    description?: null | string
    display_name?: null | string
    nav_label?: null | string
  }
}
export type ProjectRelationship = Schemas['ProjectRelationship']

export type ProjectRelationshipsResponse =
  Schemas['ProjectRelationshipsResponse']
// Project Relationships (DEPENDS_ON edges)
export type ProjectRelationshipSummary = Schemas['ProjectRelationshipSummary']
// Project EXISTS_IN types
export type ProjectService = Schemas['ExistsInResponse']

export type ProjectServiceCreate = Schemas['ExistsInCreate']
export interface Release {
  created_at: string
  created_by: string
  description?: null | string
  id: string
  links: ReleaseLink[]
  project_id: string
  title: string
  updated_at?: null | string
  version: string
}

export interface ReleaseLink {
  label?: null | string
  type: string
  url: string
}

// `Role`/`RoleDetail`/`RoleCreate` stay hand-written: the generated
// `Role-Output` is a single flat shape, while the UI separates a summary
// (`Role`) from the detailed (`RoleDetail`) and create (`RoleCreate`) forms.
export interface Role {
  description?: null | string
  name: string
  slug: string
  updated_at?: null | string
}
export interface RoleCreate {
  description?: null | string
  name: string
  priority?: number
  slug: string
}
export interface RoleDetail extends Role {
  is_system: boolean
  parent_role?: null | Role
  permissions: Permission[]
  priority: number
}

// `RoleUser` stays hand-written: no generated counterpart (the
// /roles/{slug}/users endpoint returns a flattened user projection).
export interface RoleUser {
  avatar_url?: null | string
  created_at: string
  display_name: string
  email: string
  is_active: boolean
  is_admin: boolean
  is_service_account: boolean
  last_login?: null | string
}

// `SchemaProperty` is UI-only — a form-builder projection derived from a
// JSON Schema property descriptor.
export interface SchemaProperty {
  colorAge?: Record<string, string>
  colorMap?: Record<string, string>
  colorRange?: Record<string, string>
  defaultValue?: string
  description?: string
  editable?: boolean
  enumValues?: string[]
  format?: string
  iconAge?: Record<string, string>
  iconMap?: Record<string, string>
  iconRange?: Record<string, string>
  id: string
  maximum?: number
  maxLength?: number
  minimum?: number
  minLength?: number
  name: string
  required: boolean
  type: 'array' | 'boolean' | 'integer' | 'number' | 'object' | 'string'
}

// Service Account types
export type ServiceAccount = Schemas['ServiceAccountResponse']

export type ServiceAccountCreate = Schemas['ServiceAccountCreate']

export type ServiceAccountUpdate = Schemas['ServiceAccountUpdate']

// Service Application types
// The committed openapi.json snapshot predates the OAuth-consolidation
// fields (`usage`, `oauth_app_type`, `issuer_url`, `allowed_domains`,
// `is_global`). Augment the generated types until the snapshot is
// refreshed via `npm run codegen:fetch`.
export type ServiceApplication = Schemas['ServiceApplicationResponse'] & {
  allowed_domains?: string[]
  is_global?: boolean
  issuer_url?: null | string
  oauth_app_type?: null | OAuthAppType
  usage?: ServiceApplicationUsage
}

export type ServiceApplicationCreate = Schemas['ServiceApplicationCreate'] & {
  allowed_domains?: string[]
  issuer_url?: null | string
  oauth_app_type?: null | OAuthAppType
  usage?: ServiceApplicationUsage
}

export type ServiceApplicationSecrets = Schemas['ServiceApplicationSecrets']

export type ServiceApplicationSecretsUpdate =
  Schemas['ServiceApplicationSecretsUpdate']

export type ServiceApplicationUpdate = Schemas['ServiceApplicationUpdate'] & {
  allowed_domains?: string[]
  issuer_url?: null | string
  oauth_app_type?: null | OAuthAppType
  usage?: ServiceApplicationUsage
}

export type ServiceApplicationUsage = 'both' | 'integration' | 'login'

export interface Tag {
  created_at?: null | string
  description?: null | string
  id: string
  name: string
  organization: { name: string; slug: string }
  slug: string
  updated_at?: null | string
}

// Notes & tags. Inlined here (not from api-generated.ts) because the
// committed openapi.json snapshot predates the notes endpoints.
// Regenerate with `npm run codegen:fetch` once the snapshot is refreshed
// and switch these to `Schemas['NoteResponse']` etc.
export interface TagRef {
  name: string
  slug: string
}

// Team types
export type Team = Schemas['TeamResponse']

// `TeamCreate` stays hand-written (same reason as `OrganizationCreate`).
export interface TeamCreate {
  [key: string]: unknown
  description?: null | string
  icon?: null | string
  name: string
  slug: string
}

// `TeamMember` has no generated counterpart.
export interface TeamMember {
  avatar_url?: null | string
  created_at: string
  display_name: string
  email: string
  is_active: boolean
  is_admin: boolean
  is_service_account: boolean
  last_login?: null | string
}

// Third-Party Service types
export type ThirdPartyService = Schemas['ThirdPartyServiceResponse']

export type ThirdPartyServiceCreate = Schemas['ThirdPartyServiceCreate']

export type TokenResponse = Schemas['TokenResponse']

// Upload types
export type Upload = Schemas['UploadResponse']

export interface UseAuthReturn {
  error: Error | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (credentials: LoginRequest) => Promise<void>
  loginWithOAuth: (providerId: string) => void
  logout: () => Promise<void>
  refreshToken: () => Promise<void>
  user: null | UserResponse
}

// `UserResponse` stays hand-written: it's a UI-side extension of `User`
// (inherits `username`, `user_type`, etc.) which the backend `UserResponse`
// doesn't expose.
export interface UserResponse extends User {
  avatar_url?: null | string
  created_at?: string
  groups?: string[]
  is_active?: boolean
  is_admin?: boolean
  is_service_account?: boolean
  last_login?: null | string
  permissions?: string[]
  roles?: string[]
  updated_at?: string
}

// View Types
export type View =
  | 'dashboard'
  | 'deployment-dashboard'
  | 'operations'
  | 'project-detail'
  | 'projects'
  | 'reports'
  | 'settings'
  | 'user-profile'

export interface ViewChangeConfig {
  filter?: Record<string, unknown>
  view: string
}

export type Webhook = Schemas['WebhookResponse']

export type WebhookCreate = Schemas['WebhookCreate']

// Webhook types
export type WebhookRule = Schemas['WebhookRuleResponse']
