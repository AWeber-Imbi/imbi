import type { components } from './api-generated'

type Schemas = components['schemas']

// API Response Wrappers
export interface CollectionResponse<T> {
  data: T[]
}

// API Response Types
// `ApiStatus` is the UI-facing status envelope (richer than the backend
// `StatusResponse` — includes `started_at` and optional `system` metadata).
export interface ApiStatus {
  started_at: string
  status: 'ok' | 'maintenance'
  version: string
  system?: {
    language: {
      name: string
      implementation: string
      version: string
    }
    os: {
      name: string
      version: string
    }
  }
}

// `User` is the UI-side profile shape used by auth/session consumers.
// It does not map cleanly to the backend `UserResponse` (different key set:
// UI tracks `username`/`user_type`; backend exposes `email`-keyed users).
export interface User {
  username: string
  display_name: string
  email: string
  email_address?: string
  user_type: string
  external_id?: string
  groups?: string[]
}

// `Project` keeps its hand-written shape: it has UI-only convenience fields
// (`project_type`, `[key: string]: unknown` for blueprint-defined extras) and
// a looser `relationships` shape than the generated `ProjectResponse`.
export interface Project {
  name: string
  slug: string
  description?: string | null
  icon?: string | null
  created_at?: string | null
  updated_at?: string | null
  team: {
    name: string
    slug: string
    organization: {
      name: string
      slug: string
    }
  }
  id: string
  project_type?: {
    name: string
    slug: string
    organization: {
      name: string
      slug: string
    }
  }
  project_types?: {
    name: string
    slug: string
    icon?: string | null
    organization: {
      name: string
      slug: string
    }
  }[]
  environments?: Environment[]
  links?: Record<string, string>
  identifiers?: Record<string, string | number>
  relationships?: {
    team?: RelationshipLink
    environments?: RelationshipLink
    href?: string
    outbound_count?: number
    inbound_count?: number
  }
  [key: string]: unknown
}

// `ProjectCreate` stays hand-written: the UI sends `environment_slugs` (a
// flat slug list) whereas the generated `ProjectCreate` expects an
// `environments` map of edge-property dicts + a required `project_type_slugs`.
export interface ProjectCreate {
  name: string
  slug: string
  description?: string | null
  icon?: string | null
  team_slug: string
  environment_slugs?: string[]
  links?: Record<string, string>
  identifiers?: Record<string, string | number>
  [key: string]: unknown
}

export type LinkDefinition = Schemas['LinkDefinitionResponse']
export type LinkDefinitionCreate = Schemas['LinkDefinitionCreate']

export type RelationshipLink = Schemas['RelationshipLink']

// `Environment` tracks the full response shape (with relationships).
// Add a UI-only `url` passthrough — it's surfaced in ProjectEnvironmentsCard
// but not part of the Environment schema itself.
export type Environment = Schemas['EnvironmentResponse'] & {
  url?: string | null
}

// `EnvironmentCreate` stays hand-written: the generated `EnvironmentRequest`
// requires updated_at/description/icon/label_color be explicitly set to
// `string|null`, which the UI create form doesn't do.
export interface EnvironmentCreate {
  name: string
  slug: string
  sort_order?: number | null
  description?: string | null
  icon?: string | null
  label_color?: string | null
  [key: string]: unknown
}

export type ProjectType = Schemas['ProjectTypeResponse']

// `ProjectTypeCreate` stays hand-written: no generated counterpart — the API
// mounts project-type creation via the generic org scoped endpoint.
export interface ProjectTypeCreate {
  name: string
  slug: string
  description?: string | null
  icon?: string | null
  [key: string]: unknown
}

// Activity feed projection for the dashboard — not a 1:1 backend shape.
export interface ProjectFeedEntry {
  type: 'ProjectFeedEntry'
  display_name: string
  email_address: string
  namespace: string
  namespace_id: number
  project_id: number
  project_name: string
  project_type: string
  what: 'created' | 'updated' | 'updated facts'
  occurred_at?: string
  when?: string
  who: string
}

// Activity feed projection; distinct from `OperationsLogRecord`.
export interface OperationsLogEntry {
  type: 'OperationsLogEntry'
  id: number
  occurred_at: string
  recorded_at: string
  recorded_by: string
  email_address: string
  display_name: string
  completed_at?: string | null
  performed_by?: string | null
  project_id?: number | null
  project_name?: string | null
  environment: string
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
  description: string
  link?: string | null
  notes?: string | null
  ticket_slug?: string | null
  version?: string | null
}

export type ActivityFeedEntry = ProjectFeedEntry | OperationsLogEntry

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

export type OperationsLogEntryType = (typeof OPERATIONS_LOG_ENTRY_TYPES)[number]

// Raw record returned by the /operations-log/ API (distinct from the
// activity-feed projection defined above in `OperationsLogEntry`).
export type OperationsLogRecord = Schemas['OperationLogResponse']

export interface OperationsLogFilters {
  project_slug?: string
  environment_slug?: string
  entry_type?: OperationsLogEntryType
  ticket_slug?: string
  performed_by?: string
  since?: string
  until?: string
}

export interface DashboardStats {
  total_projects: number
  projects_by_namespace: Record<string, number>
  projects_by_type: Record<string, number>
  recent_activity: ActivityFeedEntry[]
}

// Auth Types
export interface AuthState {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
}

export type AuthProvider = Schemas['AuthProvider']

export interface LoginRequest {
  email: string
  password: string
}

export type TokenResponse = Schemas['TokenResponse']

// `UserResponse` stays hand-written: it's a UI-side extension of `User`
// (inherits `username`, `user_type`, etc.) which the backend `UserResponse`
// doesn't expose.
export interface UserResponse extends User {
  groups?: string[]
  roles?: string[]
  permissions?: string[]
  created_at?: string
  updated_at?: string
  is_active?: boolean
  is_admin?: boolean
  is_service_account?: boolean
  last_login?: string | null
  avatar_url?: string | null
}

export interface UseAuthReturn {
  user: UserResponse | null
  isAuthenticated: boolean
  isLoading: boolean
  error: Error | null
  login: (credentials: LoginRequest) => Promise<void>
  loginWithOAuth: (providerId: string) => void
  logout: () => Promise<void>
  refreshToken: () => Promise<void>
}

// View Types
export type View =
  | 'dashboard'
  | 'projects'
  | 'operations'
  | 'project-detail'
  | 'deployment-dashboard'
  | 'reports'
  | 'user-profile'
  | 'settings'

export interface ViewChangeConfig {
  view: string
  filter?: Record<string, unknown>
}

// Admin User Management Types (matching API schema)
export type Permission = Schemas['Permission']

// `Role`/`RoleDetail`/`RoleCreate` stay hand-written: the generated
// `Role-Output` is a single flat shape, while the UI separates a summary
// (`Role`) from the detailed (`RoleDetail`) and create (`RoleCreate`) forms.
export interface Role {
  name: string
  slug: string
  description?: string | null
  updated_at?: string | null
}

export interface RoleDetail extends Role {
  priority: number
  is_system: boolean
  permissions: Permission[]
  parent_role?: Role | null
}

export interface RoleCreate {
  name: string
  slug: string
  description?: string | null
  priority?: number
}

export type AdminSettings = Schemas['AdminSettings']

// `RoleUser` stays hand-written: no generated counterpart (the
// /roles/{slug}/users endpoint returns a flattened user projection).
export interface RoleUser {
  email: string
  display_name: string
  is_active: boolean
  is_admin: boolean
  is_service_account: boolean
  created_at: string
  last_login?: string | null
  avatar_url?: string | null
}

// `AdminUser` stays hand-written: no generated counterpart — the UI
// composite flattens group/role/org memberships.
export interface AdminUser {
  email: string
  display_name: string
  is_active: boolean
  is_admin: boolean
  is_service_account: boolean
  created_at: string
  last_login?: string | null
  avatar_url?: string | null
  groups: {
    name: string
    slug: string
    description?: string | null
    roles: Role[]
  }[]
  roles: Role[]
  organizations?: OrgMembership[]
}

export type AdminUserCreate = Schemas['UserCreate']
export type AdminUserUpdate = Schemas['UserUpdate']

// Organization types
export type Organization = Schemas['OrganizationResponse']

// `OrganizationCreate` stays hand-written: the generated
// `OrganizationRequest` requires `updated_at`/`description`/`icon` be
// present (nullable), which the UI create form doesn't send.
export interface OrganizationCreate {
  name: string
  slug: string
  description?: string | null
  icon?: string | null
}

// Team types
export type Team = Schemas['TeamResponse']

// `TeamCreate` stays hand-written (same reason as `OrganizationCreate`).
export interface TeamCreate {
  name: string
  slug: string
  description?: string | null
  icon?: string | null
  [key: string]: unknown
}

// `TeamMember` has no generated counterpart.
export interface TeamMember {
  email: string
  display_name: string
  is_active: boolean
  is_admin: boolean
  is_service_account: boolean
  created_at: string
  last_login?: string | null
  avatar_url?: string | null
}

// Upload types
export type Upload = Schemas['UploadResponse']

// Service Account types
export type ServiceAccount = Schemas['ServiceAccountResponse']
export type ServiceAccountCreate = Schemas['ServiceAccountCreate']
export type ServiceAccountUpdate = Schemas['ServiceAccountUpdate']

export type OrgMembership = Schemas['OrgMembership']

export type ClientCredential = Schemas['ClientCredentialResponse']
export type ClientCredentialCreated = Schemas['ClientCredentialCreateResponse']
export type ClientCredentialCreate = Schemas['ClientCredentialCreate']

// API Key types
export type ApiKey = Schemas['APIKeyResponse']
export type ApiKeyCreated = Schemas['APIKeyCreateResponse']

// Blueprint types
export type BlueprintFilter = Schemas['BlueprintFilter']

export type Blueprint = Schemas['Blueprint-Output']

// `BlueprintCreate` stays hand-written: generated `Blueprint-Input` types
// `json_schema` as the full `Schema-Input` AST, but the UI passes a
// `Record<string, unknown>` (parsed JSON) and includes an `id`/timestamps
// on read-round-trip shapes.
export interface BlueprintCreate {
  name: string
  slug?: string
  kind?: 'node' | 'relationship'
  type?: string | null
  source?: string | null
  target?: string | null
  edge?: string | null
  description?: string | null
  enabled?: boolean
  priority?: number
  filter?: BlueprintFilter | null
  json_schema: Record<string, unknown>
  version?: number
}

// Third-Party Service types
export type ThirdPartyService = Schemas['ThirdPartyServiceResponse']
export type ThirdPartyServiceCreate = Schemas['ThirdPartyServiceCreate']

// Service Application types
export type ServiceApplication = Schemas['ServiceApplicationResponse']
export type ServiceApplicationCreate = Schemas['ServiceApplicationCreate']
export type ServiceApplicationUpdate = Schemas['ServiceApplicationUpdate']
export type ServiceApplicationSecrets = Schemas['ServiceApplicationSecrets']
export type ServiceApplicationSecretsUpdate =
  Schemas['ServiceApplicationSecretsUpdate']

// Webhook types
export type WebhookRule = Schemas['WebhookRuleResponse']
export type Webhook = Schemas['WebhookResponse']
export type WebhookCreate = Schemas['WebhookCreate']

// Project EXISTS_IN types
export type ProjectService = Schemas['ExistsInResponse']
export type ProjectServiceCreate = Schemas['ExistsInCreate']

// `SchemaProperty` is UI-only — a form-builder projection derived from a
// JSON Schema property descriptor.
export interface SchemaProperty {
  id: string
  name: string
  type: 'string' | 'integer' | 'number' | 'boolean' | 'array' | 'object'
  format?: string
  description?: string
  required: boolean
  defaultValue?: string
  enumValues?: string[]
  minimum?: number
  maximum?: number
  minLength?: number
  maxLength?: number
  editable?: boolean
  colorMap?: Record<string, string>
  iconMap?: Record<string, string>
  colorRange?: Record<string, string>
  iconRange?: Record<string, string>
  colorAge?: Record<string, string>
  iconAge?: Record<string, string>
}

// Project Relationships (DEPENDS_ON edges)
export type ProjectRelationshipSummary = Schemas['ProjectRelationshipSummary']
export type ProjectRelationship = Schemas['ProjectRelationship']
export type ProjectRelationshipsResponse =
  Schemas['ProjectRelationshipsResponse']

// JSON Patch operation (RFC 6902)
export type PatchOperation = Schemas['PatchOperation']

// Notes & tags. Inlined here (not from api-generated.ts) because the
// committed openapi.json snapshot predates the notes endpoints.
// Regenerate with `npm run codegen:fetch` once the snapshot is refreshed
// and switch these to `Schemas['NoteResponse']` etc.
export interface TagRef {
  name: string
  slug: string
}

export interface Note {
  id: string
  title: string
  content: string
  created_by: string
  created_at: string
  updated_by?: string | null
  updated_at?: string | null
  project_id: string
  is_pinned: boolean
  tags: TagRef[]
}

export interface NoteCreate {
  title: string
  content: string
  tags?: string[]
}

export type NoteListResponse = CollectionResponse<Note>

export interface Tag {
  id: string
  name: string
  slug: string
  description?: string | null
  created_at?: string | null
  updated_at?: string | null
  organization: { name: string; slug: string }
}
