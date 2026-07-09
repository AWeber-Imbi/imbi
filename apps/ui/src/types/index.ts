import type { components } from './api-generated'
import type { ProjectServiceEdge } from './integrations'

export type ActivityFeedEntry = OperationsLogEntry | ProjectFeedEntry

export interface AgeScoringPolicy extends ScoringPolicyBase {
  age_score_map: Record<string, number>
  attribute_name: string
  category: 'age'
}

export interface AgeScoringPolicyCreate extends ScoringPolicyCreateBase {
  age_score_map: Record<string, number>
  attribute_name: string
  category: 'age'
}

export interface AllCondition {
  all: Condition[]
}

export interface AnalysisResultScoringPolicy extends ScoringPolicyBase {
  category: 'analysis_result'
  result_slug: string
  status_score_map?: null | Record<'fail' | 'pass' | 'warn', number>
}

export interface AnalysisResultScoringPolicyCreate extends ScoringPolicyCreateBase {
  category: 'analysis_result'
  result_slug: string
  status_score_map?: null | Record<'fail' | 'pass' | 'warn', number>
}

export interface AnyCondition {
  any: Condition[]
}

// Back-compat alias: the archive / unarchive endpoints originally
// shipped this response type, and downstream components import it by
// name.  Identical shape to ``ProjectMutationResponse`` -- prefer the
// new name in fresh code.
export type ArchiveProjectResponse = ProjectMutationResponse

export interface AttributeCondition {
  attribute: string
  op: ConditionOp
  value?: unknown
}

export interface AttributeScoringPolicy extends ScoringPolicyBase {
  attribute_name: string
  category: 'attribute'
  range_score_map?: null | Record<string, number>
  value_score_map?: null | Record<string, number>
}

export interface AttributeScoringPolicyCreate extends ScoringPolicyCreateBase {
  attribute_name: string
  category: 'attribute'
  range_score_map?: null | Record<string, number>
  value_score_map?: null | Record<string, number>
}

// API Response Wrappers
export interface CollectionResponse<T> {
  data: T[]
}

export type Condition =
  | AllCondition
  | AnyCondition
  | AttributeCondition
  | NotCondition
  | RelationshipCondition

// ---- Condition (multi-conditional / relationship compound) scoring ----
// A recursive boolean expression tree. Each node is exactly one shape:
// a combinator (all/any/not), an attribute predicate on the project being
// scored, or a relationship predicate on the project's outgoing DEPENDS_ON
// neighbours. Mirrors the imbi-common `Condition` model (keys all/any/not are
// the JSON aliases the API serialises/accepts).
export type ConditionOp =
  | 'absent'
  | 'eq'
  | 'ge'
  | 'gt'
  | 'le'
  | 'lt'
  | 'ne'
  | 'present'

export interface ConditionScoringPolicy extends ScoringPolicyBase {
  category: 'condition'
  condition: Condition
  false_score: number
  true_score: number
}

export interface ConditionScoringPolicyCreate extends ScoringPolicyCreateBase {
  category: 'condition'
  condition: Condition
  false_score: number
  true_score: number
}

// `Environment` tracks the full response shape (with relationships).
// Add a UI-only `url` passthrough — it's surfaced in ProjectEnvironmentsCard
// but not part of the Environment schema itself.
// `can_deploy` / `can_promote` are sourced from the backend env model
// (defaults: true / false respectively). Kept optional here so older
// snapshots still type-check until the generated schema is refreshed.
export type Environment = Schemas['EnvironmentResponse'] & {
  can_deploy?: boolean
  can_promote?: boolean
  url?: null | string
}

// `EnvironmentCreate` stays hand-written: the generated `EnvironmentRequest`
// requires updated_at/description/icon/label_color be explicitly set to
// `string|null`, which the UI create form doesn't do.
export interface EnvironmentCreate {
  [key: string]: unknown
  can_deploy?: boolean
  can_promote?: boolean
  description?: null | string
  icon?: null | string
  label_color?: null | string
  name: string
  slug: string
  sort_order?: null | number
}

// Plugin Architecture v3 — Integration, plugin, capability, and
// project↔integration edge types (hand-authored; the OpenAPI snapshot
// predates v3). Includes ProjectServiceEdge / ProjectServiceEdgeCreate.
export * from './integrations'

// Per-plugin outcome returned by the archive / unarchive endpoints, one
// entry per lifecycle plugin assigned to the project. `failed` is the
// case worth surfacing — e.g. a GitHub repo transfer that left the repo
// un-archived. Mirrors the API's `LifecycleInvocation`.
export interface LifecycleInvocation {
  artifacts: Record<string, string>
  message: null | string
  plugin_id: string
  plugin_slug: string
  status: 'failed' | 'ok' | 'skipped'
}
// One row of the ``GET /projects/{id}/lifecycle/preview`` response --
// per-plugin "would the project-type change move my target?" answer
// the UI uses to gate the "Also move repository to ..." opt-in.
export interface LifecyclePreviewEntry {
  current_target: null | RelocationTarget
  next_target: null | RelocationTarget
  plugin_id: string
  plugin_slug: string
  would_relocate: boolean
}

export interface LifecyclePreviewResponse {
  previews: LifecyclePreviewEntry[]
}

export type LinkDefinition = Schemas['LinkDefinitionResponse']

export type LinkDefinitionCreate = Schemas['LinkDefinitionCreate']

export interface LinkPresenceScoringPolicy extends ScoringPolicyBase {
  category: 'link_presence'
  link_slug: string
  missing_score?: null | number
  present_score?: null | number
}

export interface LinkPresenceScoringPolicyCreate extends ScoringPolicyCreateBase {
  category: 'link_presence'
  link_slug: string
  missing_score?: null | number
  present_score?: null | number
}

export interface NotCondition {
  not: Condition
}

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
export interface PresenceScoringPolicy extends ScoringPolicyBase {
  attribute_name: string
  category: 'presence'
  missing_score?: null | number
  present_score?: null | number
}

export interface PresenceScoringPolicyCreate extends ScoringPolicyCreateBase {
  attribute_name: string
  category: 'presence'
  missing_score?: null | number
  present_score?: null | number
}

// `Project` keeps its hand-written shape: it has UI-only convenience fields
// (`project_type`, `[key: string]: unknown` for blueprint-defined extras) and
// a looser `relationships` shape than the generated `ProjectResponse`.
export interface Project {
  [key: string]: unknown
  archived?: boolean
  archived_at?: null | string
  closed_pr_count?: number
  created_at?: null | string
  current_releases?: Record<string, ReleaseInfo>
  description?: null | string
  environments?: Environment[]
  icon?: null | string
  id: string
  identifiers?: Record<string, number | string>
  links?: Record<string, string>
  name: string
  open_pr_count?: number
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
  // Read-only EXISTS_IN connections (third-party service relationships).
  // Maintained via the project-services endpoints / Integrations panel,
  // not by editing `identifiers`.
  services?: ProjectServiceEdge[]
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
  viewer_closed_pr_count?: number
  viewer_open_pr_count?: number
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

// Response from DELETE /projects/{id} (post-2.7).  Body carries only
// the per-plugin lifecycle results -- the project node is gone by the
// time the response is built.  Empty ``lifecycle_results`` means the
// delete short-circuited the plugin dispatch
// (``?delete_repository=false``) or the project had no lifecycle
// plugins assigned.
export interface ProjectDeletedResponse {
  lifecycle_results: LifecycleInvocation[]
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

// Response from project create / patch / archive / unarchive: the
// updated project plus the per-plugin lifecycle results.  All four
// endpoints share this shape post-`imbi-api` 2.7 -- the older
// ``ArchiveProjectResponse`` alias is kept above for components still
// referencing it by name.
export interface ProjectMutationResponse extends Project {
  lifecycle_results?: LifecycleInvocation[]
}

export type ProjectType = Schemas['ProjectTypeResponse']

// `ProjectTypeCreate` stays hand-written: no generated counterpart — the API
// mounts project-type creation via the generic org scoped endpoint.
export interface ProjectTypeCreate {
  [key: string]: unknown
  deployable?: boolean
  description?: null | string
  icon?: null | string
  name: string
  releasable?: boolean
  slug: string
  tag_formats?: TagFormat[]
}

export interface PullRequest {
  additions: number
  author: string
  changed_files: number
  created_at: string
  deletions: number
  draft: boolean
  merged: boolean
  merged_at: null | string
  pr_id: string
  pr_number: number
  project_id: string
  state: string
  title: string
  updated_at: string
  url: string
}

export interface PullRequestListResponse {
  data: PullRequest[]
  project_count: number
  total: number
}

export interface RelationshipCondition {
  relationship: {
    direction: 'outgoing'
    edge: 'DEPENDS_ON'
    quantifier: 'all' | 'any' | 'none'
    where: Condition
  }
}

export type RelationshipLink = Schemas['RelationshipLink']

export interface ReleaseInfo {
  committish?: null | string
  deployed_at: string
  performed_by?: null | string
  tag?: null | string
}

// Where a lifecycle plugin would route the project's external link --
// mirror of the API's ``RelocationTarget``.  The UI compares two
// targets by ``identifier`` to decide whether a hypothetical
// project-type change would actually move the repo (``would_relocate``
// on :type:`LifecyclePreviewEntry`).
export interface RelocationTarget {
  display: null | string
  identifier: string
  link_key: string
}

// Scoring policy types — discriminated union on `category`. See
// imbi-common/scoring/models.py for the canonical shape.
export type ScoringPolicy =
  | AgeScoringPolicy
  | AnalysisResultScoringPolicy
  | AttributeScoringPolicy
  | ConditionScoringPolicy
  | LinkPresenceScoringPolicy
  | PresenceScoringPolicy

export type ScoringPolicyCategory =
  | 'age'
  | 'analysis_result'
  | 'attribute'
  | 'condition'
  | 'link_presence'
  | 'presence'

export type ScoringPolicyCreate =
  | AgeScoringPolicyCreate
  | AnalysisResultScoringPolicyCreate
  | AttributeScoringPolicyCreate
  | ConditionScoringPolicyCreate
  | LinkPresenceScoringPolicyCreate
  | PresenceScoringPolicyCreate

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

interface ScoringPolicyBase {
  description?: null | string
  enabled: boolean
  id: string
  name: string
  priority: number
  slug: string
  targets?: string[]
  weight: number
}

interface ScoringPolicyCreateBase {
  category: ScoringPolicyCategory
  description?: null | string
  enabled: boolean
  name: string
  priority: number
  slug: string
  targets: string[]
  weight: number
}

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

// API Key types
export type ApiKey = Schemas['APIKeyResponse']

export type ApiKeyCreated = Schemas['APIKeyCreateResponse']

export type AuthProvider = Schemas['AuthProvider']

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
  ci_status: DeploymentCommitCiStatus | null
  current_status: DeploymentStatus | null
  environment: { name: string; slug: string }
  external_run_url: null | string
  last_event_at: null | string
  // Deployer of the latest event, for display: an Imbi user's display
  // name when resolved, else the raw remote login; null for in-product
  // deploys with no recorded actor.
  performed_by?: null | string
  // Email of the deployer when they resolve to an Imbi user (profile
  // link + Gravatar); null for unresolved remote logins.
  performed_by_email?: null | string
  release: null | Release
}

export interface CutReleaseRequest {
  committish: string
  prerelease?: boolean
  release_name?: null | string
  release_notes_markdown?: null | string
  tag: string
}

export interface CutReleaseResponse {
  committish: string
  recorded: boolean
  release_url: null | string
  tag: string
  warning?: null | string
}

// Dashboard types are hand-written: the /admin/dashboard/* endpoints are
// not in the committed OpenAPI snapshot yet. (DatastoreStatus /
// ServiceStatus live in their own alphabetical slots for module sort.)
export interface DashboardMetrics {
  events: { daily: number[]; total: number }
  ops_log: { daily: number[]; total: number }
  pull_requests: { daily: number[]; total: number }
  releases: { daily: number[]; total: number }
  releases_by_environment: { count: number; slug: string }[]
  since: string
}

export interface DashboardStatus {
  checked_at: string
  datastores: DatastoreStatus[]
  services: ServiceStatus[]
}

export interface DatastoreStatus {
  detail?: null | string
  latency_ms?: null | number
  name: string
  role: string
  size_bytes?: null | number
  status: 'error' | 'ok'
  total_bytes?: null | number
}

export type DeploymentAction = 'deploy' | 'redeploy'

export interface DeploymentCommit {
  author?: null | string
  authored_at?: null | string
  ci_status: DeploymentCommitCiStatus
  is_head: boolean
  message: string
  pr_number?: null | number
  sha: string
  short_sha: string
  url?: null | string
}

export type DeploymentCommitCiStatus = 'fail' | 'pass' | 'unknown' | 'warn'

export interface DeploymentCompareResult {
  additions: number
  ahead: number
  base_sha: string
  behind: number
  commits: DeploymentCommit[]
  deletions: number
  files_changed: number
  head_sha: string
  pr_numbers: number[]
}

export interface DeploymentPromoteRequest {
  action: 'promote'
  from_committish: string
  from_environment: string
  prerelease?: boolean
  release_name?: null | string
  release_notes_markdown?: string
  tag: string
  to_environment: string
}

export interface DeploymentRef {
  ahead?: null | number
  behind?: null | number
  is_default: boolean
  kind: DeploymentRefKind
  name: string
  pr_number?: null | number
  pr_state?: 'closed' | 'merged' | 'open' | null
  pr_title?: null | string
  sha: string
}

// Deployment plugin shapes (mirrors imbi_common.plugins.base).
export type DeploymentRefKind = 'branch' | 'default' | 'tag'

export interface DeploymentRun {
  completed_at?: null | string
  run_id: string
  run_url?: null | string
  started_at?: null | string
  status: DeploymentRunStatus
}

export type DeploymentRunStatus =
  | 'cancelled'
  | 'failure'
  | 'in_progress'
  | 'queued'
  | 'success'
  | 'unknown'

// Releases
export type DeploymentStatus =
  | 'failed'
  | 'in_progress'
  | 'pending'
  | 'rolled_back'
  | 'success'

export interface DeploymentTriggerRequest {
  action: DeploymentAction
  committish: string
  environment: string
  inputs?: null | Record<string, string>
  ref_label?: null | string
}

export interface DeploymentTriggerResponse {
  plugin_id: string
  plugin_slug: string
  recorded: boolean
  release_url?: null | string
  run: DeploymentRun
  tag?: null | string
  // Human-readable narrative for any non-fatal failure encountered
  // while running the per-environment promote steps (e.g. the
  // GitHub Deployments POST returned 422 because the repo's
  // ``on: deployment`` workflow isn't wired up yet). The promote
  // itself still records a DeploymentEvent; the UI surfaces this as
  // an amber inline note.
  warning?: null | string
}

export interface Document {
  attached_to?: DocumentAttachment | null
  comment_count?: number
  content: string
  created_at: string
  created_by: string
  created_by_name?: null | string
  id: string
  is_pinned: boolean
  project_id: null | string
  tags: TagRef[]
  title: string
  updated_at?: null | string
  updated_by?: null | string
}

// The vertex a document is attached to. `id` is the project id, the
// project-type slug, or the user email depending on `kind`; `team` and
// `project_types` are only populated for projects.
export interface DocumentAttachment {
  id: string
  kind: 'project' | 'project_type' | 'user'
  name: string
  project_types?: string[]
  team?: null | string
}

export interface DocumentCreate {
  content: string
  tags?: string[]
  title: string
}

export type DocumentListResponse = CollectionResponse<Document>

export interface DocumentTemplate {
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
  type?: DocumentTemplateType
  updated_at?: null | string
}

export interface DocumentTemplateCreate {
  content?: string
  description?: null | string
  icon?: null | string
  name: string
  project_type_slugs?: string[]
  slug: string
  sort_order?: number
  tags?: string[]
  title?: null | string
  type?: DocumentTemplateType
}

// Document Templates. Inlined for the same reason as Document/Tag — the
// committed openapi.json snapshot predates these endpoints. Switch to
// `Schemas['DocumentTemplateResponse']` etc. once the snapshot is refreshed.
// Which attachment contexts may use a template: 'project', 'user', and
// 'project_type' restrict the template to documents attached to that
// vertex kind; 'global' applies everywhere.
export type DocumentTemplateType =
  | 'global'
  | 'project'
  | 'project_type'
  | 'user'

export interface DraftReleaseNotesRequest {
  base_sha: string
  head_sha: string
  last_tag?: null | string
}

export interface DraftReleaseNotesResponse {
  bump: SemverBump
  commits_considered: number
  degraded: boolean
  notes_markdown: string
  reasoning: string
  version: string
}

/**
 * Types for the admin graph query workbench. Matches the backend contract:
 *   POST /admin/graph/query
 *   GET  /admin/graph/schema
 */
export interface GraphQueryCard {
  collapsed: boolean
  elapsedMs?: number
  error?: GraphQueryError
  id: string
  query: string
  result?: GraphQueryResult
  startedAt: number
  status: 'error' | 'success'
  tab: GraphQueryCardTab
}

export type GraphQueryCardTab = 'graph' | 'raw' | 'table'

export type GraphQueryCell =
  | boolean
  | GraphQueryCellEdge
  | GraphQueryCellNode
  | null
  | number
  | Record<string, unknown>
  | string
  | unknown[]

export interface GraphQueryCellEdge {
  _kind: 'edge'
  id: string
  properties: Record<string, unknown>
  type: string
}

/**
 * Cell discriminators returned inside `rows` when a cell is itself a node or
 * edge.  Anything else is left as-is and rendered as JSON.
 */
export interface GraphQueryCellNode {
  _kind: 'node'
  id: string
  labels: string[]
  properties: Record<string, unknown>
}

export interface GraphQueryEdge {
  end: string
  id: string
  properties: Record<string, unknown>
  start: string
  type: string
}

export interface GraphQueryError {
  code?: string
  column?: number
  hint?: string
  line?: number
  message: string
}

export interface GraphQueryErrorEnvelope {
  error: GraphQueryError
}

export interface GraphQueryHistoryEntry {
  executedAt: number
  query: string
}

/**
 * A node, edge, or table row selected in a result card and shown in the
 * detail drawer as a flat list of key/value pairs.
 */
export interface GraphQueryInspection {
  entries: Array<[string, unknown]>
  heading: string
  id?: string
  kind: 'edge' | 'node' | 'row'
}

export interface GraphQueryNode {
  id: string
  labels: string[]
  properties: Record<string, unknown>
}

export interface GraphQueryResult {
  columns: string[]
  edges: GraphQueryEdge[]
  elapsed_ms: number
  nodes: GraphQueryNode[]
  rows: Array<Record<string, GraphQueryCell>>
}

export interface GraphSchema {
  edge_types: Array<{ count: number; type: string }>
  node_labels: Array<{ count: number; label: string }>
  property_keys: string[]
}

export interface IdentityConnectionPollResponse {
  return_to?: null | string
  status: 'complete' | 'pending'
}

export interface IdentityConnectionResponse {
  expires_at: null | string
  id: string
  integration_id: string
  integration_name: null | string
  integration_slug: string
  last_used_at: null | string
  metadata: Record<string, unknown>
  // Slug of the plugin backing the integration; for plugin-level joins.
  plugin: null | string
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

// Mirrors imbi_common.plugins.IncidentResult / IncidentView, returned by
// GET /organizations/{org}/projects/{id}/incidents/.
export interface IncidentResult {
  incidents: IncidentView[]
  next_cursor: null | string
  total: null | number
}

export interface IncidentView {
  created_at: string
  id: string
  resolved_at?: null | string
  service?: null | string
  status: string
  title: string
  urgency?: null | string
  url: string
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

export interface LoginRequest {
  email: string
  password: string
}

export interface LogResultResponse {
  entries: LogEntryResponse[]
  next_cursor: null | string
  total: null | number
}

export interface MCPServer {
  auth_type: MCPServerAuthType
  created_at?: null | string
  description?: null | string
  enabled: boolean
  has_oauth_client_secret: boolean
  has_static_value: boolean
  icon?: null | string
  id: string
  ignored_tools: string[]
  last_error?: null | string
  last_tested_at?: null | string
  last_tested_latency_ms?: null | number
  name: string
  oauth_client_id?: null | string
  oauth_scope?: null | string
  oauth_token_url?: null | string
  slug: string
  static_header?: null | string
  status: MCPServerStatus
  timeout: number
  tool_prefix?: null | string
  tools_discovered?: null | number
  updated_at?: null | string
  url: string
  verify_ssl: boolean
}

// MCP server admin types — mirror imbi_api/endpoints/mcp_servers.py. These
// are hand-written because the codegen snapshot predates the endpoints;
// regenerate via `npm run codegen:fetch` once the backend snapshot includes
// /mcp-servers, then collapse these onto `Schemas['MCPServerResponse']`.
export type MCPServerAuthType = 'none' | 'oauth_client_credentials' | 'static'

export interface MCPServerCreate {
  auth_type?: MCPServerAuthType
  description?: null | string
  enabled?: boolean
  icon?: null | string
  ignored_tools?: string[]
  name: string
  oauth_client_id?: null | string
  oauth_client_secret?: null | string
  oauth_scope?: null | string
  oauth_token_url?: null | string
  slug: string
  static_header?: null | string
  static_value?: null | string
  timeout?: number
  tool_prefix?: null | string
  url: string
  verify_ssl?: boolean
}

export type MCPServerStatus = 'degraded' | 'healthy' | 'unknown' | 'unreachable'

// Body for POST /mcp-servers/test (test an unsaved config). name/slug are
// optional server-side; the URL and auth fields are what matter.
export type MCPServerTestConfig = Omit<MCPServerCreate, 'name' | 'slug'> & {
  name?: string
  slug?: string
}

export interface MCPServerTestResult {
  error?: null | string
  latency_ms: number
  ok: boolean
  status: 'degraded' | 'healthy' | 'unreachable'
  tested_at: string
  tools: string[]
  tools_discovered: number
}

export type MCPServerUpdate = Partial<MCPServerCreate>

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
// `plugin_slug` is augmented here pending an openapi snapshot refresh against
// the upstream `imbi-api` change — the backend already returns it.
export type OperationsLogRecord = Schemas['OperationLogResponse'] & {
  plugin_slug?: string
}

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

export interface PluginAssignmentResponse {
  default: boolean
  identity_plugin_id?: null | string
  label: string
  options: Record<string, unknown>
  plugin_id: string
  plugin_slug: string
  plugin_type: PluginType
  // Parent third-party service so the UI can show which service
  // powers the tab.
  service_icon?: null | string
  service_name?: null | string
  source: 'merged' | 'project' | 'project_type'
  supports_deployment_sync?: boolean
  supports_histogram?: boolean
  supports_lifecycle_sync?: boolean
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

export interface PluginOptionDef {
  choices?: null | string[]
  default?: boolean | null | number | string
  description: null | string
  label: string
  name: string
  required: boolean
  type: 'boolean' | 'integer' | 'mapping' | 'secret' | 'string'
}

// A plugin assignment is keyed by the plugin's type. Mirrors
// imbi_common.plugins.PluginType (the full manifest set).
export type PluginType =
  | 'analysis'
  | 'configuration'
  | 'deployment'
  | 'identity'
  | 'incidents'
  | 'lifecycle'
  | 'logs'
  | 'webhook'

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
// `deprecated` is surfaced on the neighbour summary by the relationships
// endpoint so the UI can flag deprecated dependencies. Kept optional until
// the generated schema snapshot is refreshed.
export type ProjectRelationship = Omit<
  Schemas['ProjectRelationship'],
  'project'
> & {
  project: Schemas['ProjectRelationshipSummary'] & { deprecated?: boolean }
}

export type ProjectRelationshipsResponse =
  Schemas['ProjectRelationshipsResponse']
// Releases tab (build-and-release-only projects). Commit/tag data is read
// from ClickHouse; release notes come from the graph Release nodes.
export interface RecentCommit {
  author?: null | string
  /** Imbi user email the author resolves to via identity attribution. */
  author_email?: null | string
  authored_at: string
  ci_status: DeploymentCommitCiStatus
  message: string
  sha: string
  short_sha: string
  url?: null | string
}
export interface Release {
  committish: string
  created_at: string
  created_by: string
  description?: null | string
  id: string
  links: ReleaseLink[]
  project_id: string
  tag?: null | string
  title: string
  updated_at?: null | string
}
export interface ReleaseDependenciesResponse {
  components: ReleaseDependencyComponent[]
  release_id: string
}

export interface ReleaseDependencyComponent {
  description?: null | string
  ecosystem: string
  groups: string[]
  hashes: Record<string, string>
  identifiers: ReleaseDependencyIdentifier[]
  license?: null | string
  name: string
  purl_name: string
  scope?: null | ReleaseDependencyScope
  supplier?: null | string
  version: string
}
export interface ReleaseDependencyIdentifier {
  kind: string
  value: string
}

export type ReleaseDependencyScope = 'excluded' | 'optional' | 'required'

export interface ReleaseDrift {
  commits: RecentCommit[]
  commits_since_tag: number
  head_sha: null | string
  latest_tag: null | string
  latest_tag_at: null | string
  latest_tag_sha: null | string
  suggested_bump: SemverBump
  suggested_tag: string
}

export interface ReleaseHistoryEntry {
  author?: null | string
  /** Imbi user email of the release author (the resolved `created_by`). */
  author_email?: null | string
  ci_status: DeploymentCommitCiStatus
  notes_markdown?: null | string
  package_url?: null | string
  published_at?: null | string
  release_url?: null | string
  sha: string
  short_sha: string
  tag: string
  tag_url?: null | string
  title?: null | string
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
  // Human-readable display transform applied to the rendered value
  // (serialized as `x-display.format`; see DISPLAY_FORMATS).
  displayFormat?: string
  editable?: boolean
  enumValues?: string[]
  format?: string
  iconAge?: Record<string, string>
  iconMap?: Record<string, string>
  iconRange?: Record<string, string>
  id: string
  itemsEnumValues?: string[]
  itemsType?: 'boolean' | 'integer' | 'number' | 'string'
  maximum?: number
  maxLength?: number
  minimum?: number
  minLength?: number
  name: string
  required: boolean
  type: 'array' | 'boolean' | 'integer' | 'number' | 'object' | 'string'
}

export type SemverBump = 'major' | 'minor' | 'patch'

// Service Account types
export type ServiceAccount = Schemas['ServiceAccountResponse']

export type ServiceAccountCreate = Schemas['ServiceAccountCreate']

// Part of the hand-written dashboard system-health types; see
// DashboardStatus for context.
export interface ServiceStatus {
  detail?: null | string
  latency_ms?: null | number
  name: string
  status: 'down' | 'up'
  version?: null | string
}

export interface Tag {
  created_at?: null | string
  description?: null | string
  id: string
  name: string
  organization: { name: string; slug: string }
  slug: string
  updated_at?: null | string
}

// A named release/deploy tag-format policy. Mirrors `imbi_common.models.
// TagFormat`; carried as a list on both organizations and project types.
export interface TagFormat {
  label: string
  pattern: string
}

// Documents & tags. Inlined here (not from api-generated.ts) because the
// committed openapi.json snapshot predates the documents endpoints.
// Regenerate with `npm run codegen:fetch` once the snapshot is refreshed
// and switch these to `Schemas['DocumentResponse']` etc.
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

// Mirror of the backend `TeamMembership` model returned on
// GET /users/me. Lets the UI offer membership-scoped filters (e.g. the
// "My Teams" toggle on the projects list) without extra requests.
export interface TeamMembership {
  organization_slug: string
  team_name: string
  team_slug: string
}

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
// (inherits `username`, `user_type`, etc.). `permissions`, `is_admin`, and
// `teams` are populated by GET /users/me (the backend's
// CurrentUserResponse); other optional fields (`groups`, `roles`) are not
// yet exposed by the API.
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
  teams?: TeamMembership[]
  updated_at?: string
}

export type Webhook = Schemas['WebhookResponse']

export type WebhookCreate = Schemas['WebhookCreate']

// Webhook types
export type WebhookRule = Schemas['WebhookRuleResponse']
