import {
  ENVIRONMENT_BASE_FIELDS,
  PROJECT_TYPE_BASE_FIELDS,
  TEAM_BASE_FIELDS,
} from '@/lib/constants'
import type {
  AdminPluginsResponse,
  AdminSettings,
  AdminUser,
  AdminUserCreate,
  ApiKey,
  ApiKeyCreated,
  AuthProvider,
  Blueprint,
  BlueprintCreate,
  ClientCredential,
  ClientCredentialCreate,
  ClientCredentialCreated,
  ConfigKeyResponse,
  ConfigKeyValueResponse,
  CurrentReleaseEnvironment,
  DeploymentCommit,
  DeploymentCompareResult,
  DeploymentPromoteRequest,
  DeploymentRef,
  DeploymentRun,
  DeploymentTriggerRequest,
  DeploymentTriggerResponse,
  Document,
  DocumentCreate,
  DocumentListResponse,
  DocumentTemplate,
  DocumentTemplateCreate,
  DraftReleaseNotesRequest,
  DraftReleaseNotesResponse,
  Environment,
  EnvironmentCreate,
  IdentityConnectionPollResponse,
  IdentityConnectionResponse,
  IdentityConnectionStartRequest,
  IdentityConnectionStartResponse,
  InstalledPlugin,
  LinkDefinition,
  LinkDefinitionCreate,
  LocalAuthConfig,
  LogHistogramBucket,
  LoginProviderCreate,
  LoginProviderRead,
  LoginProviderUpdate,
  LoginRequest,
  LogResultResponse,
  OperationsLogFilters,
  OperationsLogRecord,
  Organization,
  OrganizationCreate,
  PatchOperation,
  PluginAssignmentCreate,
  PluginAssignmentInput,
  PluginAssignmentResponse,
  PluginAssignmentRow,
  PluginConfigurationResponse,
  PluginCreate,
  PluginEdge,
  PluginEdgePut,
  PluginEntity,
  PluginEntityCreate,
  PluginEntitySchema,
  PluginResponse,
  PluginUpdate,
  Project,
  ProjectCreate,
  ProjectRelationshipsResponse,
  ProjectType,
  ProjectTypeCreate,
  PromotionOption,
  Role,
  RoleCreate,
  RoleDetail,
  RoleUser,
  ScoringPolicy,
  ScoringPolicyCreate,
  ServiceAccount,
  ServiceAccountCreate,
  ServiceApplication,
  ServiceApplicationCreate,
  ServiceApplicationSecrets,
  Tag,
  Team,
  TeamCreate,
  TeamMember,
  ThirdPartyService,
  ThirdPartyServiceCreate,
  TokenResponse,
  Upload,
  UserResponse,
  Webhook,
  WebhookCreate,
} from '@/types'

import { apiClient, apiUrl } from './client'

// Re-export for backward compatibility with modules that import from here.
export type { PatchOperation }

export const getAuthProviders = (signal?: AbortSignal) =>
  apiClient.get<{ default_redirect: string; providers: AuthProvider[] }>(
    '/auth/providers',
    undefined,
    signal,
  )

export const loginWithPassword = (credentials: LoginRequest) =>
  apiClient.post<TokenResponse>('/auth/login', credentials)

export const refreshToken = (refreshToken: string) =>
  apiClient.post<TokenResponse>('/auth/token/refresh', {
    refresh_token: refreshToken,
  })

export const logoutAuth = () => apiClient.post<void>('/auth/logout', {})

export const getUserByUsername = (username: string, signal?: AbortSignal) =>
  apiClient.get<UserResponse>(`/users/${username}`, undefined, signal)

export const getProjects = async (
  orgSlug: string,
  signal?: AbortSignal,
): Promise<Project[]> => {
  const response = await apiClient.get<Project[]>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/`,
    undefined,
    signal,
  )
  return Array.isArray(response) ? response : []
}

export const getProject = (
  orgSlug: string,
  projectId: string,
  signal?: AbortSignal,
) =>
  apiClient.get<Project>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}`,
    undefined,
    signal,
  )

export interface AttributeContribution {
  attribute_name: string
  mapped_score: number
  policy_slug: string
  value: unknown
  weight: number
  weighted_contribution: number
}

interface ScoreBreakdown {
  attribute_contributions: AttributeContribution[]
  base_score: number
  unfloored_total: number
}

export const getProjectBreakdown = (
  orgSlug: string,
  projectId: string,
  signal?: AbortSignal,
) =>
  apiClient.get<Project & { breakdown?: ScoreBreakdown }>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}`,
    { breakdown: true },
    signal,
  )

export interface ProjectSchemaResponse {
  sections: ProjectSchemaSection[]
}

export interface ProjectSchemaSection {
  description?: null | string
  name: string
  properties: Record<string, ProjectSchemaSectionProperty>
  slug: string
}

export interface ProjectSchemaSectionProperty {
  default?: unknown
  description?: null | string
  enum?: null | string[]
  format?: null | string
  items?: null | {
    enum?: null | string[]
    type?: null | string
  }
  maximum?: null | number
  minimum?: null | number
  title?: null | string
  type?: null | string
  'x-ui'?: null | {
    'color-age'?: Record<string, string>
    'color-map'?: Record<string, string>
    'color-range'?: Record<string, string>
    editable?: boolean
    'icon-age'?: Record<string, string>
    'icon-map'?: Record<string, string>
    'icon-range'?: Record<string, string>
  }
}

export const getProjectSchema = (
  orgSlug: string,
  projectId: string,
  signal?: AbortSignal,
) =>
  apiClient.get<ProjectSchemaResponse>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}/schema`,
    undefined,
    signal,
  )

export const getProjectRelationships = (
  orgSlug: string,
  projectId: string,
  signal?: AbortSignal,
) =>
  apiClient.get<ProjectRelationshipsResponse>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}/relationships`,
    undefined,
    signal,
  )

export const setProjectRelationships = (
  orgSlug: string,
  projectId: string,
  dependsOn: string[],
) =>
  apiClient.put<ProjectRelationshipsResponse>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}/relationships`,
    { depends_on: dependsOn },
  )

export const createProject = (
  orgSlug: string,
  projectTypeSlug: string,
  project: ProjectCreate,
) =>
  apiClient.post<Project>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectTypeSlug)}`,
    project,
  )

export const patchProject = (
  orgSlug: string,
  projectId: string,
  operations: PatchOperation[],
) =>
  apiClient.patch<Project>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}`,
    operations,
  )

export const deleteProject = (orgSlug: string, projectId: string) =>
  apiClient.delete<void>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}`,
  )

// Link Definitions (org-scoped)
export const listLinkDefinitions = async (
  orgSlug: string,
  signal?: AbortSignal,
): Promise<LinkDefinition[]> => {
  const response = await apiClient.get<LinkDefinition[]>(
    `/organizations/${encodeURIComponent(orgSlug)}/link-definitions/`,
    undefined,
    signal,
  )
  return Array.isArray(response) ? response : []
}

export const createLinkDefinition = (
  orgSlug: string,
  data: LinkDefinitionCreate,
) =>
  apiClient.post<LinkDefinition>(
    `/organizations/${encodeURIComponent(orgSlug)}/link-definitions/`,
    data,
  )

export const updateLinkDefinition = (
  orgSlug: string,
  slug: string,
  operations: PatchOperation[],
) =>
  apiClient.patch<LinkDefinition>(
    `/organizations/${encodeURIComponent(orgSlug)}/link-definitions/${encodeURIComponent(slug)}`,
    operations,
  )

export const deleteLinkDefinition = (orgSlug: string, slug: string) =>
  apiClient.delete<void>(
    `/organizations/${encodeURIComponent(orgSlug)}/link-definitions/${encodeURIComponent(slug)}`,
  )

// Document Templates (org-scoped)
export const listDocumentTemplates = async (
  orgSlug: string,
  signal?: AbortSignal,
): Promise<DocumentTemplate[]> => {
  const response = await apiClient.get<DocumentTemplate[]>(
    `/organizations/${encodeURIComponent(orgSlug)}/document-templates/`,
    undefined,
    signal,
  )
  return Array.isArray(response) ? response : []
}

export const createDocumentTemplate = (
  orgSlug: string,
  data: DocumentTemplateCreate,
) =>
  apiClient.post<DocumentTemplate>(
    `/organizations/${encodeURIComponent(orgSlug)}/document-templates/`,
    data,
  )

export const updateDocumentTemplate = (
  orgSlug: string,
  slug: string,
  operations: PatchOperation[],
) =>
  apiClient.patch<DocumentTemplate>(
    `/organizations/${encodeURIComponent(orgSlug)}/document-templates/${encodeURIComponent(slug)}`,
    operations,
  )

export const deleteDocumentTemplate = (orgSlug: string, slug: string) =>
  apiClient.delete<void>(
    `/organizations/${encodeURIComponent(orgSlug)}/document-templates/${encodeURIComponent(slug)}`,
  )

export interface OperationsLogMetrics {
  deploys: number
  deploys_by_environment: Record<string, number>
  environments: number
  event_count: number
  projects: number
  team_members: number
}

export interface OperationsLogPage {
  entries: OperationsLogRecord[]
  metrics?: OperationsLogMetrics
  nextCursor?: string
}

interface OperationsLogEnvelope {
  data: OperationsLogRecord[]
  metrics: null | OperationsLogMetrics
}

function parseNextCursor(headers: Headers): string | undefined {
  const link = headers.get('link')
  if (!link) return undefined
  const match = link.match(/<([^>]+)>;\s*rel="next"/)
  if (!match) return undefined
  try {
    const url = new URL(match[1], window.location.origin)
    return url.searchParams.get('cursor') || undefined
  } catch {
    return undefined
  }
}

export const listOperationsLog = async (
  params: {
    cursor?: string
    filters?: OperationsLogFilters
    limit?: number
  },
  signal?: AbortSignal,
): Promise<OperationsLogPage> => {
  const query: Record<string, unknown> = { limit: params.limit ?? 50 }
  if (params.cursor) query.cursor = params.cursor
  if (params.filters) {
    for (const [k, v] of Object.entries(params.filters)) {
      if (v) query[k] = v
    }
  }
  const { data, headers } =
    await apiClient.getWithHeaders<OperationsLogEnvelope>(
      '/operations-log/',
      query,
      signal,
    )
  return {
    entries: Array.isArray(data?.data) ? data.data : [],
    metrics: data?.metrics ?? undefined,
    nextCursor: parseNextCursor(headers),
  }
}

export const getOperationsLogEntry = (entryId: string, signal?: AbortSignal) =>
  apiClient.get<OperationsLogRecord>(
    `/operations-log/${encodeURIComponent(entryId)}`,
    undefined,
    signal,
  )

// Events
export interface EventRecord {
  attributed_to: string
  id: string
  metadata: Record<string, unknown>
  payload: Record<string, unknown>
  project_id: string
  recorded_at: string
  third_party_service: string
  type: string
}

export interface EventsPage {
  entries: EventRecord[]
  nextCursor?: string
}

interface EventsEnvelope {
  data: EventRecord[]
}

export const listProjectEvents = async (
  params: {
    cursor?: string
    limit?: number
    orgSlug: string
    projectId: string
    type?: string
  },
  signal?: AbortSignal,
): Promise<EventsPage> => {
  const query: Record<string, unknown> = { limit: params.limit ?? 50 }
  if (params.cursor) query.cursor = params.cursor
  if (params.type) query.type = params.type
  const { data, headers } = await apiClient.getWithHeaders<EventsEnvelope>(
    `/organizations/${encodeURIComponent(params.orgSlug)}/projects/${encodeURIComponent(params.projectId)}/events/`,
    query,
    signal,
  )
  return {
    entries: Array.isArray(data?.data) ? data.data : [],
    nextCursor: parseNextCursor(headers),
  }
}

export const listEnvironments = async (
  orgSlug: string,
  signal?: AbortSignal,
): Promise<Environment[]> => {
  const response = await apiClient.get<Environment[]>(
    `/organizations/${encodeURIComponent(orgSlug)}/environments/`,
    undefined,
    signal,
  )
  return Array.isArray(response) ? response : []
}

export const createEnvironment = (orgSlug: string, env: EnvironmentCreate) =>
  apiClient.post<Environment>(
    `/organizations/${encodeURIComponent(orgSlug)}/environments/`,
    env,
  )

export const updateEnvironment = (
  orgSlug: string,
  slug: string,
  operations: PatchOperation[],
) =>
  apiClient.patch<Environment>(
    `/organizations/${encodeURIComponent(orgSlug)}/environments/${encodeURIComponent(slug)}`,
    operations,
  )

export const deleteEnvironment = (orgSlug: string, slug: string) =>
  apiClient.delete<void>(
    `/organizations/${encodeURIComponent(orgSlug)}/environments/${encodeURIComponent(slug)}`,
  )

export const getEnvironmentSchema = (signal?: AbortSignal) =>
  getDynamicSchema('EnvironmentRequest', ENVIRONMENT_BASE_FIELDS, signal)

// Admin - Project Types
export const listProjectTypes = async (
  orgSlug: string,
  signal?: AbortSignal,
): Promise<ProjectType[]> => {
  const response = await apiClient.get<ProjectType[]>(
    `/organizations/${encodeURIComponent(orgSlug)}/project-types/`,
    undefined,
    signal,
  )
  return Array.isArray(response) ? response : []
}

export const createProjectType = (orgSlug: string, pt: ProjectTypeCreate) =>
  apiClient.post<ProjectType>(
    `/organizations/${encodeURIComponent(orgSlug)}/project-types/`,
    pt,
  )

export const updateProjectType = (
  orgSlug: string,
  slug: string,
  operations: PatchOperation[],
) =>
  apiClient.patch<ProjectType>(
    `/organizations/${encodeURIComponent(orgSlug)}/project-types/${encodeURIComponent(slug)}`,
    operations,
  )

export const deleteProjectType = (orgSlug: string, slug: string) =>
  apiClient.delete<void>(
    `/organizations/${encodeURIComponent(orgSlug)}/project-types/${encodeURIComponent(slug)}`,
  )

export const getProjectTypeSchema = (signal?: AbortSignal) =>
  getDynamicSchema('ProjectTypeRequest', PROJECT_TYPE_BASE_FIELDS, signal)

// Admin - User Management
export const listAdminUsers = async (
  params?: {
    is_active?: boolean
    is_admin?: boolean
  },
  signal?: AbortSignal,
): Promise<AdminUser[]> => {
  const response = await apiClient.get<AdminUser[]>('/users/', params, signal)
  // Users endpoint returns array directly, not wrapped in { data: [] }
  return Array.isArray(response) ? response : []
}

export const getAdminUser = (email: string, signal?: AbortSignal) =>
  apiClient.get<AdminUser>(
    `/users/${encodeURIComponent(email)}`,
    undefined,
    signal,
  )

export const createAdminUser = (user: AdminUserCreate) =>
  apiClient.post<AdminUser>('/users/', user)

export const updateAdminUser = (email: string, operations: PatchOperation[]) =>
  apiClient.patch<AdminUser>(`/users/${encodeURIComponent(email)}`, operations)

export const deleteAdminUser = (email: string) =>
  apiClient.delete<void>(`/users/${encodeURIComponent(email)}`)

// User organization membership
export const addUserToOrg = (
  email: string,
  data: { organization_slug: string; role_slug: string },
) => apiClient.post(`/users/${encodeURIComponent(email)}/organizations`, data)

export const updateUserOrgRole = (
  email: string,
  orgSlug: string,
  operations: PatchOperation[],
) =>
  apiClient.patch(
    `/users/${encodeURIComponent(email)}/organizations/${encodeURIComponent(orgSlug)}`,
    operations,
  )

export const removeUserFromOrg = (email: string, orgSlug: string) =>
  apiClient.delete(
    `/users/${encodeURIComponent(email)}/organizations/${encodeURIComponent(orgSlug)}`,
  )

// Admin - Roles Management
export const getRoles = async (signal?: AbortSignal): Promise<Role[]> => {
  const response = await apiClient.get<Role[]>('/roles/', undefined, signal)
  return Array.isArray(response) ? response : []
}

export const getRole = (slug: string, signal?: AbortSignal) =>
  apiClient.get<RoleDetail>(
    `/roles/${encodeURIComponent(slug)}`,
    undefined,
    signal,
  )

export const createRole = (role: RoleCreate) =>
  apiClient.post<RoleDetail>('/roles/', role)

export const updateRole = (slug: string, operations: PatchOperation[]) =>
  apiClient.patch<RoleDetail>(`/roles/${encodeURIComponent(slug)}`, operations)

export const deleteRole = (slug: string) =>
  apiClient.delete<void>(`/roles/${encodeURIComponent(slug)}`)

export const grantPermission = (slug: string, permissionName: string) =>
  apiClient.post<void>(`/roles/${encodeURIComponent(slug)}/permissions`, {
    permission_name: permissionName,
  })

export const revokePermission = (slug: string, permissionName: string) =>
  apiClient.delete<void>(
    `/roles/${encodeURIComponent(slug)}/permissions/${encodeURIComponent(permissionName)}`,
  )

export const getRoleUsers = async (
  slug: string,
  signal?: AbortSignal,
): Promise<RoleUser[]> => {
  const response = await apiClient.get<RoleUser[]>(
    `/roles/${encodeURIComponent(slug)}/users`,
    undefined,
    signal,
  )
  return Array.isArray(response) ? response : []
}

export const getRoleServiceAccounts = async (
  slug: string,
  signal?: AbortSignal,
): Promise<ServiceAccount[]> => {
  const response = await apiClient.get<ServiceAccount[]>(
    `/roles/${encodeURIComponent(slug)}/service-accounts`,
    undefined,
    signal,
  )
  return Array.isArray(response) ? response : []
}

export const getRoleGroups = async (
  slug: string,
  signal?: AbortSignal,
): Promise<{ name: string; slug: string }[]> => {
  const response = await apiClient.get<{ name: string; slug: string }[]>(
    `/roles/${encodeURIComponent(slug)}/groups`,
    undefined,
    signal,
  )
  return Array.isArray(response) ? response : []
}

// Admin - Scoring Policies
export const listScoringPolicies = async (
  signal?: AbortSignal,
): Promise<ScoringPolicy[]> => {
  const response = await apiClient.get<ScoringPolicy[]>(
    '/scoring/policies/',
    undefined,
    signal,
  )
  return Array.isArray(response) ? response : []
}

export const createScoringPolicy = (data: ScoringPolicyCreate) =>
  apiClient.post<ScoringPolicy>('/scoring/policies/', data)

export const updateScoringPolicy = (
  slug: string,
  operations: PatchOperation[],
) =>
  apiClient.patch<ScoringPolicy>(
    `/scoring/policies/${encodeURIComponent(slug)}`,
    operations,
  )

export const deleteScoringPolicy = (slug: string) =>
  apiClient.delete<void>(`/scoring/policies/${encodeURIComponent(slug)}`)

export const rescoreAll = () =>
  apiClient.post<{ enqueued: number }>('/scoring/rescore')

export const rescoreProject = (projectId: string) =>
  apiClient.post<{ enqueued: number }>('/scoring/rescore', {
    project_id: projectId,
  })

export interface ScoreTrend {
  current: null | number
  delta: null | number
  period_days: number
  previous: null | number
}

export const getScoreTrend = (
  orgSlug: string,
  projectId: string,
  days = 30,
  signal?: AbortSignal,
) =>
  apiClient.get<ScoreTrend>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}/score/trend`,
    { days },
    signal,
  )

export type ScoreChangeReason =
  | 'attribute_change'
  | 'blueprint_change'
  | 'bulk_rescore'
  | 'policy_change'
  | 'system'

export interface ScoreHistoryPoint {
  change_reason: null | ScoreChangeReason
  previous_score: null | number
  score: number
  timestamp: string
}

interface ScoreHistory {
  granularity: 'day' | 'hour' | 'raw'
  points: ScoreHistoryPoint[]
  project_id: string
}

export const getScoreHistory = (
  orgSlug: string,
  projectId: string,
  params?: {
    from?: string
    granularity?: 'day' | 'hour' | 'raw'
    to?: string
  },
  signal?: AbortSignal,
) =>
  apiClient.get<ScoreHistory>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}/score/history`,
    params,
    signal,
  )

// Admin - Settings (reference data)
export const getAdminSettings = (signal?: AbortSignal) =>
  apiClient.get<AdminSettings>('/admin/settings', undefined, signal)

// Admin - Blueprints
export const listBlueprints = async (
  params?: {
    enabled?: boolean
  },
  signal?: AbortSignal,
): Promise<Blueprint[]> => {
  const response = await apiClient.get<Blueprint[]>(
    '/blueprints/',
    params,
    signal,
  )
  return Array.isArray(response) ? response : []
}

export const getBlueprint = (
  type: string,
  slug: string,
  signal?: AbortSignal,
) =>
  apiClient.get<Blueprint>(
    `/blueprints/${encodeURIComponent(type)}/${encodeURIComponent(slug)}`,
    undefined,
    signal,
  )

export const createBlueprint = (blueprint: BlueprintCreate) =>
  apiClient.post<Blueprint>('/blueprints/', blueprint)

export const updateBlueprint = (
  type: string,
  slug: string,
  operations: PatchOperation[],
) =>
  apiClient.patch<Blueprint>(
    `/blueprints/${encodeURIComponent(type)}/${encodeURIComponent(slug)}`,
    operations,
  )

export const deleteBlueprint = (type: string, slug: string) =>
  apiClient.delete<void>(
    `/blueprints/${encodeURIComponent(type)}/${encodeURIComponent(slug)}`,
  )

// Admin - Organizations
export const listOrganizations = async (
  signal?: AbortSignal,
): Promise<Organization[]> => {
  const response = await apiClient.get<Organization[]>(
    '/organizations/',
    undefined,
    signal,
  )
  return Array.isArray(response) ? response : []
}

export const createOrganization = (org: OrganizationCreate) =>
  apiClient.post<Organization>('/organizations/', org)

export const updateOrganization = (
  slug: string,
  operations: PatchOperation[],
) =>
  apiClient.patch<Organization>(
    `/organizations/${encodeURIComponent(slug)}`,
    operations,
  )

export const deleteOrganization = (slug: string) =>
  apiClient.delete<void>(`/organizations/${encodeURIComponent(slug)}`)

// Dynamic blueprint schema extraction from OpenAPI spec

export interface DynamicFieldSchema {
  default?: unknown
  description?: string
  enum?: string[]
  format?: string
  maximum?: number
  maxLength?: number
  minimum?: number
  minLength?: number
  title?: string
  type?: string
}

export interface DynamicSchema {
  properties: Record<string, DynamicFieldSchema>
  required?: string[]
}

interface OpenApiResponse {
  components?: {
    schemas?: Record<
      string,
      {
        properties?: Record<string, Record<string, unknown>>
        required?: string[]
      }
    >
  }
}

// Flatten Pydantic/OpenAPI 3.1 anyOf nullable patterns.
// e.g. { anyOf: [{type:"string",format:"email"},{type:"null"}] } → {type:"string",format:"email"}
export function flattenNullableAnyOf(
  prop: Record<string, unknown>,
): DynamicFieldSchema {
  const anyOf = prop.anyOf as Record<string, unknown>[] | undefined
  if (!Array.isArray(anyOf)) return prop as DynamicFieldSchema
  const nonNull = anyOf.filter((v) => v.type !== 'null')
  if (nonNull.length === 1) {
    const { anyOf: _, ...rest } = prop
    return { ...rest, ...nonNull[0] } as DynamicFieldSchema
  }
  return prop as DynamicFieldSchema
}

/**
 * Fetch the dynamic (blueprint) fields for a given OpenAPI schema name,
 * filtering out the provided base fields.
 */
const getDynamicSchema = async (
  schemaName: string,
  baseFields: string[],
  signal?: AbortSignal,
): Promise<DynamicSchema | null> => {
  const response = await apiClient.get<OpenApiResponse>(
    '/openapi.json',
    undefined,
    signal,
  )
  const schema = response.components?.schemas?.[schemaName]
  if (!schema?.properties) return null
  const baseSet = new Set(baseFields)
  const dynamicProperties: Record<string, DynamicFieldSchema> = {}
  for (const [key, value] of Object.entries(schema.properties)) {
    if (!baseSet.has(key)) {
      dynamicProperties[key] = flattenNullableAnyOf(value)
    }
  }
  if (Object.keys(dynamicProperties).length === 0) return null
  const dynamicRequired = Array.isArray(schema.required)
    ? schema.required.filter((key) => !baseSet.has(key))
    : []
  return {
    properties: dynamicProperties,
    ...(dynamicRequired.length > 0 ? { required: dynamicRequired } : {}),
  }
}

export const getTeamSchema = (signal?: AbortSignal) =>
  getDynamicSchema('TeamRequest', TEAM_BASE_FIELDS, signal)

// Admin - Teams
export const listTeams = async (
  orgSlug: string,
  signal?: AbortSignal,
): Promise<Team[]> => {
  const response = await apiClient.get<Team[]>(
    `/organizations/${encodeURIComponent(orgSlug)}/teams/`,
    undefined,
    signal,
  )
  return Array.isArray(response) ? response : []
}

export const createTeam = (orgSlug: string, team: TeamCreate) =>
  apiClient.post<Team>(
    `/organizations/${encodeURIComponent(orgSlug)}/teams/`,
    team,
  )

export const updateTeam = (
  orgSlug: string,
  slug: string,
  operations: PatchOperation[],
) =>
  apiClient.patch<Team>(
    `/organizations/${encodeURIComponent(orgSlug)}/teams/${encodeURIComponent(slug)}`,
    operations,
  )

export const deleteTeam = (orgSlug: string, slug: string) =>
  apiClient.delete<void>(
    `/organizations/${encodeURIComponent(orgSlug)}/teams/${encodeURIComponent(slug)}`,
  )

export const getTeamMembers = async (
  orgSlug: string,
  slug: string,
  signal?: AbortSignal,
): Promise<TeamMember[]> => {
  const response = await apiClient.get<TeamMember[]>(
    `/organizations/${encodeURIComponent(orgSlug)}/teams/${encodeURIComponent(slug)}/members`,
    undefined,
    signal,
  )
  return Array.isArray(response) ? response : []
}

export const addTeamMember = (orgSlug: string, slug: string, email: string) =>
  apiClient.post<void>(
    `/organizations/${encodeURIComponent(orgSlug)}/teams/${encodeURIComponent(slug)}/members`,
    { email },
  )

export const removeTeamMember = (
  orgSlug: string,
  slug: string,
  email: string,
) =>
  apiClient.delete<void>(
    `/organizations/${encodeURIComponent(orgSlug)}/teams/${encodeURIComponent(slug)}/members/${encodeURIComponent(email)}`,
  )

// Admin - Third-Party Services
export const listThirdPartyServices = async (
  orgSlug: string,
  signal?: AbortSignal,
): Promise<ThirdPartyService[]> => {
  const response = await apiClient.get<ThirdPartyService[]>(
    `/organizations/${encodeURIComponent(orgSlug)}/third-party-services/`,
    undefined,
    signal,
  )
  return Array.isArray(response) ? response : []
}

export const createThirdPartyService = (
  orgSlug: string,
  svc: ThirdPartyServiceCreate,
) =>
  apiClient.post<ThirdPartyService>(
    `/organizations/${encodeURIComponent(orgSlug)}/third-party-services/`,
    svc,
  )

export const updateThirdPartyService = (
  orgSlug: string,
  slug: string,
  operations: PatchOperation[],
) =>
  apiClient.patch<ThirdPartyService>(
    `/organizations/${encodeURIComponent(orgSlug)}/third-party-services/${encodeURIComponent(slug)}`,
    operations,
  )

export const deleteThirdPartyService = (orgSlug: string, slug: string) =>
  apiClient.delete<void>(
    `/organizations/${encodeURIComponent(orgSlug)}/third-party-services/${encodeURIComponent(slug)}`,
  )

// Service Applications (nested under Third-Party Services)
// `usage` defaults to `'integration'` server-side, which yields rows in
// this org with `usage IN ('integration','both')` plus any global
// `usage IN ('login','both')` row from any org as `is_global=true`.
export const listServiceApplications = async (
  orgSlug: string,
  serviceSlug: string,
  usage?: 'integration' | 'login',
  signal?: AbortSignal,
): Promise<ServiceApplication[]> => {
  const response = await apiClient.get<ServiceApplication[]>(
    `/organizations/${encodeURIComponent(orgSlug)}/third-party-services/${encodeURIComponent(serviceSlug)}/applications/`,
    usage ? { usage } : undefined,
    signal,
  )
  return Array.isArray(response) ? response : []
}

export const createServiceApplication = (
  orgSlug: string,
  serviceSlug: string,
  data: ServiceApplicationCreate,
) =>
  apiClient.post<ServiceApplication>(
    `/organizations/${encodeURIComponent(orgSlug)}/third-party-services/${encodeURIComponent(serviceSlug)}/applications/`,
    data,
  )

export const updateServiceApplication = (
  orgSlug: string,
  serviceSlug: string,
  appSlug: string,
  operations: PatchOperation[],
) =>
  apiClient.patch<ServiceApplication>(
    `/organizations/${encodeURIComponent(orgSlug)}/third-party-services/${encodeURIComponent(serviceSlug)}/applications/${encodeURIComponent(appSlug)}`,
    operations,
  )

export const deleteServiceApplication = (
  orgSlug: string,
  serviceSlug: string,
  appSlug: string,
) =>
  apiClient.delete<void>(
    `/organizations/${encodeURIComponent(orgSlug)}/third-party-services/${encodeURIComponent(serviceSlug)}/applications/${encodeURIComponent(appSlug)}`,
  )

// Service Application Secrets
export const getApplicationSecrets = (
  orgSlug: string,
  serviceSlug: string,
  appSlug: string,
  signal?: AbortSignal,
) =>
  apiClient.get<ServiceApplicationSecrets>(
    `/organizations/${encodeURIComponent(orgSlug)}/third-party-services/${encodeURIComponent(serviceSlug)}/applications/${encodeURIComponent(appSlug)}/secrets`,
    undefined,
    signal,
  )

export const updateApplicationSecrets = (
  orgSlug: string,
  serviceSlug: string,
  appSlug: string,
  operations: PatchOperation[],
) =>
  apiClient.patch<ServiceApplicationSecrets>(
    `/organizations/${encodeURIComponent(orgSlug)}/third-party-services/${encodeURIComponent(serviceSlug)}/applications/${encodeURIComponent(appSlug)}/secrets`,
    operations,
  )

// Uploads
export const uploadFile = (file: File): Promise<Upload> => {
  const formData = new FormData()
  formData.append('file', file)
  return apiClient.postFormData<Upload>('/uploads/', formData)
}

export const getUploadUrl = (id: string): string =>
  apiUrl(`/uploads/${encodeURIComponent(id)}`)

export const getUploadThumbnailUrl = (id: string): string =>
  apiUrl(`/uploads/${encodeURIComponent(id)}/thumbnail`)

export const deleteUpload = (id: string) =>
  apiClient.delete<void>(`/uploads/${encodeURIComponent(id)}`)

// API Keys (routes use the authenticated user, no user prefix)
export const listApiKeys = async (signal?: AbortSignal): Promise<ApiKey[]> => {
  const response = await apiClient.get<ApiKey[]>('/api-keys', undefined, signal)
  return Array.isArray(response) ? response : []
}

export const createApiKey = (name?: string) =>
  apiClient.post<ApiKeyCreated>('/api-keys', { name: name || 'default' })

export const deleteApiKey = (keyId: string) =>
  apiClient.delete<void>(`/api-keys/${encodeURIComponent(keyId)}`)

// Service Accounts
export const listServiceAccounts = (
  params?: { is_active?: boolean },
  signal?: AbortSignal,
) => apiClient.get<ServiceAccount[]>('/service-accounts', params, signal)

export const getServiceAccount = (slug: string, signal?: AbortSignal) =>
  apiClient.get<ServiceAccount>(
    `/service-accounts/${encodeURIComponent(slug)}`,
    undefined,
    signal,
  )

export const createServiceAccount = (data: ServiceAccountCreate) =>
  apiClient.post<ServiceAccount>('/service-accounts', data)

export const updateServiceAccount = (
  slug: string,
  operations: PatchOperation[],
) =>
  apiClient.patch<ServiceAccount>(
    `/service-accounts/${encodeURIComponent(slug)}`,
    operations,
  )

export const deleteServiceAccount = (slug: string) =>
  apiClient.delete(`/service-accounts/${encodeURIComponent(slug)}`)

export const addServiceAccountToOrg = (
  slug: string,
  data: { organization_slug: string; role_slug: string },
) =>
  apiClient.post(
    `/service-accounts/${encodeURIComponent(slug)}/organizations`,
    data,
  )

export const updateServiceAccountOrgRole = (
  slug: string,
  orgSlug: string,
  operations: PatchOperation[],
) =>
  apiClient.patch(
    `/service-accounts/${encodeURIComponent(slug)}/organizations/${encodeURIComponent(orgSlug)}`,
    operations,
  )

export const removeServiceAccountFromOrg = (slug: string, orgSlug: string) =>
  apiClient.delete(
    `/service-accounts/${encodeURIComponent(slug)}/organizations/${encodeURIComponent(orgSlug)}`,
  )

// Service Account Client Credentials
export const listClientCredentials = (slug: string, signal?: AbortSignal) =>
  apiClient.get<ClientCredential[]>(
    `/service-accounts/${encodeURIComponent(slug)}/client-credentials`,
    undefined,
    signal,
  )

export const createClientCredential = (
  slug: string,
  data: ClientCredentialCreate,
) =>
  apiClient.post<ClientCredentialCreated>(
    `/service-accounts/${encodeURIComponent(slug)}/client-credentials`,
    data,
  )

export const revokeClientCredential = (slug: string, clientId: string) =>
  apiClient.delete(
    `/service-accounts/${encodeURIComponent(slug)}/client-credentials/${encodeURIComponent(clientId)}`,
  )

export const rotateClientCredential = (slug: string, clientId: string) =>
  apiClient.post<ClientCredentialCreated>(
    `/service-accounts/${encodeURIComponent(slug)}/client-credentials/${encodeURIComponent(clientId)}/rotate`,
  )

// Service Account API Keys
export const listServiceAccountApiKeys = (slug: string, signal?: AbortSignal) =>
  apiClient.get<ApiKey[]>(
    `/service-accounts/${encodeURIComponent(slug)}/api-keys`,
    undefined,
    signal,
  )

export const createServiceAccountApiKey = (
  slug: string,
  data: {
    description?: string
    expires_in_days?: number
    name: string
    scopes?: string[]
  },
) =>
  apiClient.post<ApiKeyCreated>(
    `/service-accounts/${encodeURIComponent(slug)}/api-keys`,
    data,
  )

export const revokeServiceAccountApiKey = (slug: string, keyId: string) =>
  apiClient.delete(
    `/service-accounts/${encodeURIComponent(slug)}/api-keys/${encodeURIComponent(keyId)}`,
  )

export const rotateServiceAccountApiKey = (slug: string, keyId: string) =>
  apiClient.post<ApiKeyCreated>(
    `/service-accounts/${encodeURIComponent(slug)}/api-keys/${encodeURIComponent(keyId)}/rotate`,
  )

// Admin - Webhooks
export const listWebhooks = async (
  orgSlug: string,
  signal?: AbortSignal,
): Promise<Webhook[]> => {
  const response = await apiClient.get<Webhook[]>(
    `/organizations/${encodeURIComponent(orgSlug)}/webhooks/`,
    undefined,
    signal,
  )
  return Array.isArray(response) ? response : []
}

export const createWebhook = (orgSlug: string, data: WebhookCreate) =>
  apiClient.post<Webhook>(
    `/organizations/${encodeURIComponent(orgSlug)}/webhooks/`,
    data,
  )

export const updateWebhook = (
  orgSlug: string,
  slug: string,
  operations: PatchOperation[],
) =>
  apiClient.patch<Webhook>(
    `/organizations/${encodeURIComponent(orgSlug)}/webhooks/${encodeURIComponent(slug)}`,
    operations,
  )

export const deleteWebhook = (orgSlug: string, slug: string) =>
  apiClient.delete<void>(
    `/organizations/${encodeURIComponent(orgSlug)}/webhooks/${encodeURIComponent(slug)}`,
  )

export const listServiceWebhooks = async (
  orgSlug: string,
  serviceSlug: string,
  signal?: AbortSignal,
): Promise<Webhook[]> => {
  const response = await apiClient.get<Webhook[]>(
    `/organizations/${encodeURIComponent(orgSlug)}/third-party-services/${encodeURIComponent(serviceSlug)}/webhooks/`,
    undefined,
    signal,
  )
  return Array.isArray(response) ? response : []
}

// Admin - Auth Providers (login-eligible service applications)
export const listAuthProviders = async (
  signal?: AbortSignal,
): Promise<LoginProviderRead[]> => {
  const response = await apiClient.get<unknown>(
    '/admin/auth-providers',
    undefined,
    signal,
  )
  if (!Array.isArray(response)) {
    throw new Error('Invalid auth providers response')
  }
  return response as LoginProviderRead[]
}

export const createAuthProvider = (data: LoginProviderCreate) =>
  apiClient.post<LoginProviderRead>('/admin/auth-providers', data)

export const updateAuthProvider = (slug: string, data: LoginProviderUpdate) =>
  apiClient.put<LoginProviderRead>(
    `/admin/auth-providers/${encodeURIComponent(slug)}`,
    data,
  )

export const deleteAuthProvider = (slug: string) =>
  apiClient.delete<void>(`/admin/auth-providers/${encodeURIComponent(slug)}`)

export const getLocalAuthConfig = (signal?: AbortSignal) =>
  apiClient.get<LocalAuthConfig>('/admin/local-auth', undefined, signal)

export const updateLocalAuthConfig = (
  data: { enabled: boolean },
  signal?: AbortSignal,
) => apiClient.put<LocalAuthConfig>('/admin/local-auth', data, signal)

export const listProjectDocuments = async (
  orgSlug: string,
  projectId: string,
  params?: { cursor?: string; limit?: number; tag?: string },
  signal?: AbortSignal,
): Promise<Document[]> => {
  const response = await apiClient.get<DocumentListResponse>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}/documents/`,
    params,
    signal,
  )
  return response?.data ?? []
}

export const createProjectDocument = (
  orgSlug: string,
  projectId: string,
  data: DocumentCreate,
) =>
  apiClient.post<Document>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}/documents/`,
    data,
  )

export const patchProjectDocument = (
  orgSlug: string,
  projectId: string,
  documentId: string,
  operations: PatchOperation[],
) =>
  apiClient.patch<Document>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(documentId)}`,
    operations,
  )

export const deleteProjectDocument = (
  orgSlug: string,
  projectId: string,
  documentId: string,
) =>
  apiClient.delete<void>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(documentId)}`,
  )

// Tags (org-scoped)
export const listTags = async (
  orgSlug: string,
  signal?: AbortSignal,
): Promise<Tag[]> => {
  const response = await apiClient.get<Tag[]>(
    `/organizations/${encodeURIComponent(orgSlug)}/tags/`,
    undefined,
    signal,
  )
  return Array.isArray(response) ? response : []
}

export const createTag = (
  orgSlug: string,
  data: { description?: null | string; name: string; slug?: null | string },
) =>
  apiClient.post<Tag>(
    `/organizations/${encodeURIComponent(orgSlug)}/tags/`,
    data,
  )

// Releases
export const listCurrentReleases = async (
  orgSlug: string,
  projectId: string,
  signal?: AbortSignal,
): Promise<CurrentReleaseEnvironment[]> => {
  const response = await apiClient.get<CurrentReleaseEnvironment[]>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}/releases/current`,
    undefined,
    signal,
  )
  return Array.isArray(response) ? response : []
}

// Deployments
const deploymentsBase = (orgSlug: string, projectId: string): string =>
  `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}/deployments`

export const listDeploymentRefs = async (
  orgSlug: string,
  projectId: string,
  params: {
    kind?: 'all' | 'branch' | 'default' | 'tag'
    q?: string
    source?: string
  } = {},
  signal?: AbortSignal,
): Promise<DeploymentRef[]> => {
  const search = new URLSearchParams()
  if (params.kind) search.set('kind', params.kind)
  if (params.q) search.set('q', params.q)
  if (params.source) search.set('source', params.source)
  const query = search.toString()
  const response = await apiClient.get<DeploymentRef[]>(
    `${deploymentsBase(orgSlug, projectId)}/refs${query ? `?${query}` : ''}`,
    undefined,
    signal,
  )
  return Array.isArray(response) ? response : []
}

export const listRefCommits = async (
  orgSlug: string,
  projectId: string,
  ref: string,
  params: { limit?: number; source?: string } = {},
  signal?: AbortSignal,
): Promise<DeploymentCommit[]> => {
  const search = new URLSearchParams()
  if (params.limit != null) search.set('limit', String(params.limit))
  if (params.source) search.set('source', params.source)
  const query = search.toString()
  const response = await apiClient.get<DeploymentCommit[]>(
    `${deploymentsBase(orgSlug, projectId)}/refs/${encodeURIComponent(ref)}/commits${query ? `?${query}` : ''}`,
    undefined,
    signal,
  )
  return Array.isArray(response) ? response : []
}

export const resolveCommit = (
  orgSlug: string,
  projectId: string,
  committish: string,
  source?: string,
  signal?: AbortSignal,
): Promise<DeploymentCommit> => {
  const search = source ? `?source=${encodeURIComponent(source)}` : ''
  return apiClient.get<DeploymentCommit>(
    `${deploymentsBase(orgSlug, projectId)}/commits/${encodeURIComponent(committish)}${search}`,
    undefined,
    signal,
  )
}

export const compareDeploymentRefs = (
  orgSlug: string,
  projectId: string,
  base: string,
  head: string,
  source?: string,
  signal?: AbortSignal,
): Promise<DeploymentCompareResult> => {
  const search = new URLSearchParams({ base, head })
  if (source) search.set('source', source)
  return apiClient.get<DeploymentCompareResult>(
    `${deploymentsBase(orgSlug, projectId)}/compare?${search.toString()}`,
    undefined,
    signal,
  )
}

export const triggerDeployment = (
  orgSlug: string,
  projectId: string,
  body: DeploymentTriggerRequest,
  source?: string,
): Promise<DeploymentTriggerResponse> => {
  const search = source ? `?source=${encodeURIComponent(source)}` : ''
  return apiClient.post<DeploymentTriggerResponse>(
    `${deploymentsBase(orgSlug, projectId)}${search}`,
    body,
  )
}

export const promoteDeployment = (
  orgSlug: string,
  projectId: string,
  body: DeploymentPromoteRequest,
  source?: string,
): Promise<DeploymentTriggerResponse> => {
  const search = source ? `?source=${encodeURIComponent(source)}` : ''
  return apiClient.post<DeploymentTriggerResponse>(
    `${deploymentsBase(orgSlug, projectId)}${search}`,
    body,
  )
}

export const draftReleaseNotes = (
  orgSlug: string,
  projectId: string,
  body: DraftReleaseNotesRequest,
  source?: string,
): Promise<DraftReleaseNotesResponse> => {
  const search = source ? `?source=${encodeURIComponent(source)}` : ''
  return apiClient.post<DraftReleaseNotesResponse>(
    `${deploymentsBase(orgSlug, projectId)}/draft-release-notes${search}`,
    body,
  )
}

export const getDeploymentRunStatus = (
  orgSlug: string,
  projectId: string,
  runId: string,
  source?: string,
  signal?: AbortSignal,
): Promise<DeploymentRun> => {
  const search = source ? `?source=${encodeURIComponent(source)}` : ''
  return apiClient.get<DeploymentRun>(
    `${deploymentsBase(orgSlug, projectId)}/runs/${encodeURIComponent(runId)}${search}`,
    undefined,
    signal,
  )
}

export const listPromotionOptions = async (
  orgSlug: string,
  projectId: string,
  source?: string,
  signal?: AbortSignal,
): Promise<PromotionOption[]> => {
  const search = source ? `?source=${encodeURIComponent(source)}` : ''
  const response = await apiClient.get<PromotionOption[]>(
    `${deploymentsBase(orgSlug, projectId)}/promotion-options${search}`,
    undefined,
    signal,
  )
  return Array.isArray(response) ? response : []
}

// Identity Plugins (org-scoped)
export interface IdentityPluginRef {
  label: string
  plugin_id: string
  plugin_slug: string
}

export const listIdentityPlugins = async (
  orgSlug: string,
  signal?: AbortSignal,
): Promise<IdentityPluginRef[]> => {
  const response = await apiClient.get<IdentityPluginRef[]>(
    `/organizations/${encodeURIComponent(orgSlug)}/identity-plugins/`,
    undefined,
    signal,
  )
  return Array.isArray(response) ? response : []
}

// Service Plugins
export const listServicePlugins = (
  orgSlug: string,
  serviceSlug: string,
  signal?: AbortSignal,
) =>
  apiClient.get<PluginResponse[]>(
    `/organizations/${encodeURIComponent(orgSlug)}/third-party-services/${encodeURIComponent(serviceSlug)}/plugins/`,
    undefined,
    signal,
  )

export const createServicePlugin = (
  orgSlug: string,
  serviceSlug: string,
  data: PluginCreate,
) =>
  apiClient.post<PluginResponse>(
    `/organizations/${encodeURIComponent(orgSlug)}/third-party-services/${encodeURIComponent(serviceSlug)}/plugins/`,
    data,
  )

export const updateServicePlugin = (
  orgSlug: string,
  serviceSlug: string,
  pluginId: string,
  data: PluginUpdate,
) =>
  apiClient.put<PluginResponse>(
    `/organizations/${encodeURIComponent(orgSlug)}/third-party-services/${encodeURIComponent(serviceSlug)}/plugins/${encodeURIComponent(pluginId)}`,
    data,
  )

export const deleteServicePlugin = (
  orgSlug: string,
  serviceSlug: string,
  pluginId: string,
  force = false,
) =>
  apiClient.delete<void>(
    `/organizations/${encodeURIComponent(orgSlug)}/third-party-services/${encodeURIComponent(serviceSlug)}/plugins/${encodeURIComponent(pluginId)}${force ? '?force=true' : ''}`,
  )

export const listProjectPlugins = (
  orgSlug: string,
  projectId: string,
  signal?: AbortSignal,
) =>
  apiClient.get<PluginAssignmentResponse[]>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}/plugins/`,
    undefined,
    signal,
  )

export const replaceProjectPlugins = (
  orgSlug: string,
  projectId: string,
  assignments: PluginAssignmentCreate[],
) =>
  apiClient.put<PluginAssignmentResponse[]>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}/plugins/`,
    assignments,
  )

// Project Configuration
export const listConfigurationKeys = (
  orgSlug: string,
  projectId: string,
  params?: { environment?: string; source?: string },
  signal?: AbortSignal,
) =>
  apiClient.get<ConfigKeyResponse[]>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}/configuration/`,
    params,
    signal,
  )

export const fetchConfigurationValues = (
  orgSlug: string,
  projectId: string,
  keys: string[],
  params?: { environment?: string; source?: string },
) =>
  apiClient.post<ConfigKeyValueResponse[]>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}/configuration/values:fetch${params ? `?${new URLSearchParams(Object.entries(params).filter(([, v]) => v != null) as [string, string][]).toString()}` : ''}`,
    { keys },
  )

export const setConfigurationValue = (
  orgSlug: string,
  projectId: string,
  key: string,
  data: { data_type: string; secret: boolean; value: unknown },
  params?: { environment?: string; source?: string },
) =>
  apiClient.put<ConfigKeyResponse>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}/configuration/${encodeURIComponent(key)}${params ? `?${new URLSearchParams(Object.entries(params).filter(([, v]) => v != null) as [string, string][]).toString()}` : ''}`,
    data,
  )

export const deleteConfigurationKey = (
  orgSlug: string,
  projectId: string,
  key: string,
  params?: { environment?: string; source?: string },
) =>
  apiClient.delete<void>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}/configuration/${encodeURIComponent(key)}${params ? `?${new URLSearchParams(Object.entries(params).filter(([, v]) => v != null) as [string, string][]).toString()}` : ''}`,
  )

// Project Logs
export interface LogSearchParams {
  cursor?: string
  end_time?: string
  environment?: string | string[]
  filter?: string[]
  level?: string[]
  limit?: number
  source?: string
  start_time?: string
}

export const getProjectLogsHistogram = (
  orgSlug: string,
  projectId: string,
  params?: {
    bucket_count?: number
    end_time?: string
    environment?: string | string[]
    filter?: string[]
    source?: string
    start_time?: string
  },
  signal?: AbortSignal,
) => {
  const query: Record<string, string | string[]> = {}
  if (params) {
    if (params.source) query.source = params.source
    if (params.environment) query.environment = params.environment
    if (params.start_time) query.start_time = params.start_time
    if (params.end_time) query.end_time = params.end_time
    if (params.bucket_count != null)
      query.bucket_count = String(params.bucket_count)
    if (params.filter?.length) query.filter = params.filter
  }
  return apiClient.get<LogHistogramBucket[]>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}/logs/histogram`,
    query,
    signal,
  )
}

export const searchProjectLogs = (
  orgSlug: string,
  projectId: string,
  params?: LogSearchParams,
  signal?: AbortSignal,
) => {
  const query: Record<string, string | string[]> = {}
  if (params) {
    if (params.source) query.source = params.source
    if (params.environment) query.environment = params.environment
    if (params.start_time) query.start_time = params.start_time
    if (params.end_time) query.end_time = params.end_time
    if (params.cursor) query.cursor = params.cursor
    if (params.limit != null) query.limit = String(params.limit)
    if (params.filter?.length) query.filter = params.filter
    if (params.level?.length) query.level = params.level
  }
  return apiClient.get<LogResultResponse>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}/logs/`,
    query,
    signal,
  )
}

export interface ScoreRollupRow {
  avg_score: number
  dimension: 'organization' | 'project_type' | 'team'
  key: string
  last_updated: null | string
  latest_score: number
}

export const getScoreRollup = (
  dimension: 'organization' | 'project_type' | 'team' = 'team',
  signal?: AbortSignal,
) => apiClient.get<ScoreRollupRow[]>('/scores/rollup', { dimension }, signal)

export interface GlobalScoreEvent {
  change_reason: null | string
  previous_score: null | number
  project_id: string
  project_name: string
  score: number
  team_key: string
  timestamp: string
}

export interface MonthlyImprovementRow {
  current_avg_score: null | number
  dimension: string
  improvement: null | number
  key: string
  previous_avg_score: null | number
  project_count: number
}

export interface TeamScoreHistoryPoint {
  score: number
  timestamp: string
}

export interface TeamScoreSeries {
  key: string
  points: TeamScoreHistoryPoint[]
}

interface ScoreHistoryByTeamResponse {
  granularity: 'day' | 'hour'
  teams: TeamScoreSeries[]
}

export const getScoreHistoryFeed = (
  params?: {
    from?: string
    limit?: number
    to?: string
  },
  signal?: AbortSignal,
) => apiClient.get<GlobalScoreEvent[]>('/scores/history-feed', params, signal)

export const getScoreHistoryByTeam = (
  params?: {
    from?: string
    granularity?: 'day' | 'hour'
    to?: string
  },
  signal?: AbortSignal,
) =>
  apiClient.get<ScoreHistoryByTeamResponse>(
    '/scores/history-by-team',
    params,
    signal,
  )

export const getMonthlyImprovement = (
  params: {
    dimension?: 'organization' | 'project_type' | 'team'
    month: number
    year: number
  },
  signal?: AbortSignal,
) =>
  apiClient.get<MonthlyImprovementRow[]>(
    '/scores/monthly-improvement',
    {
      dimension: params.dimension ?? 'team',
      month: params.month,
      year: params.year,
    },
    signal,
  )

// Identity connections (per-user)
export const getMyIdentities = (signal?: AbortSignal) =>
  apiClient.get<IdentityConnectionResponse[]>(
    '/me/identities',
    undefined,
    signal,
  )

export const startMyIdentity = (
  pluginId: string,
  body: IdentityConnectionStartRequest = {},
) =>
  apiClient.post<IdentityConnectionStartResponse>(
    `/me/identities/${encodeURIComponent(pluginId)}/start`,
    body,
  )

export const pollMyIdentity = (pluginId: string, state: string) =>
  apiClient.post<IdentityConnectionPollResponse>(
    `/me/identities/${encodeURIComponent(pluginId)}/poll`,
    { state },
  )

export const refreshMyIdentity = (pluginId: string) =>
  apiClient.post<{ status: string }>(
    `/me/identities/${encodeURIComponent(pluginId)}/refresh`,
    {},
  )

export const disconnectMyIdentity = (pluginId: string) =>
  apiClient.delete<void>(`/me/identities/${encodeURIComponent(pluginId)}`)

// Admin Plugins
export const getAdminPlugins = (signal?: AbortSignal) =>
  apiClient.get<AdminPluginsResponse>('/admin/plugins', undefined, signal)

export const getAdminPlugin = (slug: string, signal?: AbortSignal) =>
  apiClient.get<InstalledPlugin>(
    `/admin/plugins/${encodeURIComponent(slug)}`,
    undefined,
    signal,
  )

export const setAdminPluginEnabled = (slug: string, enabled: boolean) =>
  apiClient.patch<InstalledPlugin>(
    `/admin/plugins/${encodeURIComponent(slug)}`,
    { enabled },
  )

// Operator-overrides patch.  ``widget_text``: ``null`` clears the
// override (UI inherits the manifest); a string sets it.
// ``vertex_label_overrides``: ``{label_name: {field: value-or-null}}`` —
// null on a field clears that field, an empty inner dict clears every
// override for that label, ``null`` for the whole field clears every
// override entirely.
export interface AdminPluginPatch {
  vertex_label_overrides?: null | Record<string, Record<string, null | string>>
  widget_text?: null | string
}

export const updateAdminPlugin = (slug: string, body: AdminPluginPatch) =>
  apiClient.patch<InstalledPlugin>(
    `/admin/plugins/${encodeURIComponent(slug)}`,
    body,
  )

export const getServicePluginConfiguration = (
  orgSlug: string,
  serviceSlug: string,
  pluginId: string,
  signal?: AbortSignal,
) =>
  apiClient.get<PluginConfigurationResponse>(
    `/organizations/${encodeURIComponent(orgSlug)}/third-party-services/${encodeURIComponent(serviceSlug)}/plugins/${encodeURIComponent(pluginId)}/configuration`,
    undefined,
    signal,
  )

export const patchServicePluginConfiguration = (
  orgSlug: string,
  serviceSlug: string,
  pluginId: string,
  values: Record<string, null | string>,
) =>
  apiClient.patch<PluginConfigurationResponse>(
    `/organizations/${encodeURIComponent(orgSlug)}/third-party-services/${encodeURIComponent(serviceSlug)}/plugins/${encodeURIComponent(pluginId)}/configuration`,
    values,
  )

export const listServicePluginAssignments = (
  orgSlug: string,
  serviceSlug: string,
  pluginId: string,
  signal?: AbortSignal,
) =>
  apiClient.get<PluginAssignmentRow[]>(
    `/organizations/${encodeURIComponent(orgSlug)}/third-party-services/${encodeURIComponent(serviceSlug)}/plugins/${encodeURIComponent(pluginId)}/assignments`,
    undefined,
    signal,
  )

export const replaceServicePluginAssignments = (
  orgSlug: string,
  serviceSlug: string,
  pluginId: string,
  body: PluginAssignmentInput[],
) =>
  apiClient.put<PluginAssignmentRow[]>(
    `/organizations/${encodeURIComponent(orgSlug)}/third-party-services/${encodeURIComponent(serviceSlug)}/plugins/${encodeURIComponent(pluginId)}/assignments`,
    body,
  )

// ---------------------------------------------------------------------------
// Generic plugin entities + edges (declared by the plugin manifest's
// vertex_labels / edge_labels; the host serves CRUD without per-plugin code).
// ---------------------------------------------------------------------------

const pluginEntitiesPath = (slug: string, label: string) =>
  `/admin/plugins/${encodeURIComponent(slug)}/entities/${encodeURIComponent(label)}`

export const listPluginEntities = (
  slug: string,
  label: string,
  signal?: AbortSignal,
) =>
  apiClient.get<PluginEntity[]>(
    pluginEntitiesPath(slug, label),
    undefined,
    signal,
  )

export const getPluginEntitySchema = (
  slug: string,
  label: string,
  signal?: AbortSignal,
) =>
  apiClient.get<PluginEntitySchema>(
    `${pluginEntitiesPath(slug, label)}/_schema`,
    undefined,
    signal,
  )

export const createPluginEntity = (
  slug: string,
  label: string,
  body: PluginEntityCreate,
) => apiClient.post<PluginEntity>(pluginEntitiesPath(slug, label), body)

export const updatePluginEntity = (
  slug: string,
  label: string,
  id: string,
  body: Record<string, unknown>,
) =>
  apiClient.patch<PluginEntity>(
    `${pluginEntitiesPath(slug, label)}/${encodeURIComponent(id)}`,
    body,
  )

export const deletePluginEntity = (slug: string, label: string, id: string) =>
  apiClient.delete<void>(
    `${pluginEntitiesPath(slug, label)}/${encodeURIComponent(id)}`,
  )

const environmentEdgesPath = (
  orgSlug: string,
  envSlug: string,
  relType: string,
) =>
  `/organizations/${encodeURIComponent(orgSlug)}/environments/${encodeURIComponent(envSlug)}/edges/${encodeURIComponent(relType)}`

export const listEnvironmentEdges = (
  orgSlug: string,
  envSlug: string,
  relType: string,
  signal?: AbortSignal,
) =>
  apiClient.get<PluginEdge[]>(
    environmentEdgesPath(orgSlug, envSlug, relType),
    undefined,
    signal,
  )

export const setEnvironmentEdge = (
  orgSlug: string,
  envSlug: string,
  relType: string,
  body: PluginEdgePut,
) =>
  apiClient.put<PluginEdge>(
    environmentEdgesPath(orgSlug, envSlug, relType),
    body,
  )

export const deleteEnvironmentEdge = (
  orgSlug: string,
  envSlug: string,
  relType: string,
) => apiClient.delete<void>(environmentEdgesPath(orgSlug, envSlug, relType))

export const listPluginEdgesByOrg = (
  pluginSlug: string,
  relType: string,
  orgSlug: string,
  signal?: AbortSignal,
) =>
  apiClient.get<Record<string, PluginEdge[]>>(
    `/admin/plugins/${encodeURIComponent(pluginSlug)}/edges`,
    { org_slug: orgSlug, rel_type: relType },
    signal,
  )
