import { apiClient } from './client'
import {
  TEAM_BASE_FIELDS,
  ENVIRONMENT_BASE_FIELDS,
  PROJECT_TYPE_BASE_FIELDS,
} from '@/lib/constants'
import type {
  ApiStatus,
  User,
  Project,
  ActivityFeedEntry,
  Namespace,
  Environment,
  EnvironmentCreate,
  ProjectType,
  ProjectTypeCreate,
  CollectionResponse,
  AuthProvider,
  TokenResponse,
  LoginRequest,
  UserResponse,
  AdminUser,
  AdminUserCreate,
  AdminSettings,
  Role,
  RoleDetail,
  RoleCreate,
  RoleUser,
  Blueprint,
  BlueprintCreate,
  Organization,
  OrganizationCreate,
  Team,
  TeamCreate,
  TeamMember,
  ThirdPartyService,
  ThirdPartyServiceCreate,
  Upload,
  ApiKey,
  ApiKeyCreated,
  ServiceAccount,
  ServiceAccountCreate,
  ClientCredential,
  ClientCredentialCreated,
  ClientCredentialCreate,
} from '@/types'

// Status/Health
export const getStatus = () => apiClient.get<ApiStatus>('/status')

// User/Auth
export const getAuthProviders = () =>
  apiClient.get<{ providers: AuthProvider[], default_redirect: string }>('/auth/providers')

export const loginWithPassword = (credentials: LoginRequest) =>
  apiClient.post<TokenResponse>('/auth/login', credentials)

export const refreshToken = (refreshToken: string) =>
  apiClient.post<TokenResponse>('/auth/token/refresh', { refresh_token: refreshToken })

export const logoutAuth = () =>
  apiClient.post<void>('/auth/logout', {})

export const getUserByUsername = (username: string) =>
  apiClient.get<UserResponse>(`/users/${username}`)

// Legacy endpoints (kept for backward compatibility)
export const getCurrentUser = () => apiClient.get<User>('/ui/user')
export const logout = () => apiClient.get<void>('/ui/logout')

// Projects
export const getProjects = async (params?: {
  namespace_id?: number
  project_type_id?: number
  include_archived?: boolean
}): Promise<Project[]> => {
  const response = await apiClient.get<CollectionResponse<Project>>('/projects', params)
  return response.data
}

export const getProject = (id: number) => apiClient.get<Project>(`/projects/${id}`)

// Activity Feed
export const getActivityFeed = async (params?: {
  limit?: number
  omit_user?: string
  token?: string
}): Promise<ActivityFeedEntry[]> => {
  try {
    const response = await apiClient.get<ActivityFeedEntry[]>('/activity-feed', params)
    // Activity feed returns array directly, not wrapped in { data: [] }
    console.log('[API] Activity feed response:', response)
    console.log('[API] First activity item:', response?.[0])
    return Array.isArray(response) ? response : []
  } catch (error) {
    console.error('[API] Activity feed error:', error)
    return []
  }
}

// Metadata
export const getNamespaces = async (): Promise<Namespace[]> => {
  const response = await apiClient.get<CollectionResponse<Namespace>>('/namespaces')
  return response.data
}

export const getEnvironments = async (): Promise<Environment[]> => {
  const response = await apiClient.get<CollectionResponse<Environment>>('/environments')
  return response.data
}

export const getProjectTypes = async (): Promise<ProjectType[]> => {
  const response = await apiClient.get<CollectionResponse<ProjectType>>('/project-types')
  return response.data
}

// Admin - Environments
export const listEnvironments = async (): Promise<Environment[]> => {
  const response = await apiClient.get<Environment[]>('/environments/')
  return Array.isArray(response) ? response : []
}

export const getEnvironment = (slug: string) =>
  apiClient.get<Environment>(`/environments/${encodeURIComponent(slug)}`)

export const createEnvironment = (env: EnvironmentCreate) =>
  apiClient.post<Environment>('/environments/', env)

export const updateEnvironment = (slug: string, env: EnvironmentCreate) =>
  apiClient.put<Environment>(`/environments/${encodeURIComponent(slug)}`, env)

export const deleteEnvironment = (slug: string) =>
  apiClient.delete<void>(`/environments/${encodeURIComponent(slug)}`)

export const getEnvironmentSchema = () =>
  getDynamicSchema('EnvironmentWithBlueprints', ENVIRONMENT_BASE_FIELDS)

// Admin - Project Types
export const listProjectTypes = async (): Promise<ProjectType[]> => {
  const response = await apiClient.get<ProjectType[]>('/project-types/')
  return Array.isArray(response) ? response : []
}

export const getProjectType = (slug: string) =>
  apiClient.get<ProjectType>(`/project-types/${encodeURIComponent(slug)}`)

export const createProjectType = (pt: ProjectTypeCreate) =>
  apiClient.post<ProjectType>('/project-types/', pt)

export const updateProjectType = (slug: string, pt: ProjectTypeCreate) =>
  apiClient.put<ProjectType>(`/project-types/${encodeURIComponent(slug)}`, pt)

export const deleteProjectType = (slug: string) =>
  apiClient.delete<void>(`/project-types/${encodeURIComponent(slug)}`)

export const getProjectTypeSchema = () =>
  getDynamicSchema('ProjectTypeWithBlueprints', PROJECT_TYPE_BASE_FIELDS)

// Admin - User Management
export const listAdminUsers = async (params?: {
  is_active?: boolean
  is_admin?: boolean
}): Promise<AdminUser[]> => {
  try {
    const response = await apiClient.get<AdminUser[]>('/users/', params)
    console.log('[API] listAdminUsers response:', response)
    // Users endpoint returns array directly, not wrapped in { data: [] }
    return Array.isArray(response) ? response : []
  } catch (error) {
    console.error('[API] listAdminUsers error:', error)
    return []
  }
}

export const getAdminUser = (email: string) =>
  apiClient.get<AdminUser>(`/users/${encodeURIComponent(email)}`)

export const createAdminUser = (user: AdminUserCreate) =>
  apiClient.post<AdminUser>('/users/', user)

export const updateAdminUser = (email: string, user: AdminUserCreate) =>
  apiClient.put<AdminUser>(`/users/${encodeURIComponent(email)}`, user)

export const deleteAdminUser = (email: string) =>
  apiClient.delete<void>(`/users/${encodeURIComponent(email)}`)

// Admin - Roles Management
export const getRoles = async (): Promise<Role[]> => {
  try {
    const response = await apiClient.get<Role[]>('/roles/')
    console.log('[API] getRoles response:', response)
    return Array.isArray(response) ? response : []
  } catch (error) {
    console.error('[API] getRoles error:', error)
    return []
  }
}

export const getRole = (slug: string) =>
  apiClient.get<RoleDetail>(`/roles/${encodeURIComponent(slug)}`)

export const createRole = (role: RoleCreate) =>
  apiClient.post<RoleDetail>('/roles/', role)

export const updateRole = (slug: string, role: RoleCreate) =>
  apiClient.put<RoleDetail>(`/roles/${encodeURIComponent(slug)}`, role)

export const deleteRole = (slug: string) =>
  apiClient.delete<void>(`/roles/${encodeURIComponent(slug)}`)

export const grantPermission = (slug: string, permissionName: string) =>
  apiClient.post<void>(`/roles/${encodeURIComponent(slug)}/permissions`, {
    permission_name: permissionName
  })

export const revokePermission = (slug: string, permissionName: string) =>
  apiClient.delete<void>(
    `/roles/${encodeURIComponent(slug)}/permissions/${encodeURIComponent(permissionName)}`
  )

export const getRoleUsers = async (slug: string): Promise<RoleUser[]> => {
  const response = await apiClient.get<RoleUser[]>(
    `/roles/${encodeURIComponent(slug)}/users`
  )
  return Array.isArray(response) ? response : []
}

export const getRoleGroups = async (slug: string): Promise<{ name: string; slug: string }[]> => {
  const response = await apiClient.get<{ name: string; slug: string }[]>(
    `/roles/${encodeURIComponent(slug)}/groups`
  )
  return Array.isArray(response) ? response : []
}

// Admin - Settings (reference data)
export const getAdminSettings = () =>
  apiClient.get<AdminSettings>('/admin/settings')

// Admin - Blueprints
export const listBlueprints = async (params?: {
  enabled?: boolean
}): Promise<Blueprint[]> => {
  const response = await apiClient.get<Blueprint[]>('/blueprints/', params)
  return Array.isArray(response) ? response : []
}

export const listBlueprintsByType = async (
  type: string,
  params?: { enabled?: boolean }
): Promise<Blueprint[]> => {
  const response = await apiClient.get<Blueprint[]>(
    `/blueprints/${encodeURIComponent(type)}`,
    params
  )
  return Array.isArray(response) ? response : []
}

export const getBlueprint = (type: string, slug: string) =>
  apiClient.get<Blueprint>(
    `/blueprints/${encodeURIComponent(type)}/${encodeURIComponent(slug)}`
  )

export const createBlueprint = (blueprint: BlueprintCreate) =>
  apiClient.post<Blueprint>('/blueprints/', blueprint)

export const updateBlueprint = (
  type: string,
  slug: string,
  blueprint: BlueprintCreate
) =>
  apiClient.put<Blueprint>(
    `/blueprints/${encodeURIComponent(type)}/${encodeURIComponent(slug)}`,
    blueprint
  )

export const deleteBlueprint = (type: string, slug: string) =>
  apiClient.delete<void>(
    `/blueprints/${encodeURIComponent(type)}/${encodeURIComponent(slug)}`
  )

// Admin - Organizations
export const listOrganizations = async (): Promise<Organization[]> => {
  const response = await apiClient.get<Organization[]>('/organizations/')
  return Array.isArray(response) ? response : []
}

export const getOrganization = (slug: string) =>
  apiClient.get<Organization>(`/organizations/${encodeURIComponent(slug)}`)

export const createOrganization = (org: OrganizationCreate) =>
  apiClient.post<Organization>('/organizations/', org)

export const updateOrganization = (slug: string, org: OrganizationCreate) =>
  apiClient.put<Organization>(`/organizations/${encodeURIComponent(slug)}`, org)

export const deleteOrganization = (slug: string) =>
  apiClient.delete<void>(`/organizations/${encodeURIComponent(slug)}`)

// Dynamic blueprint schema extraction from OpenAPI spec

export interface DynamicFieldSchema {
  type?: string
  format?: string
  title?: string
  description?: string
  enum?: string[]
  default?: unknown
  minLength?: number
  maxLength?: number
  minimum?: number
  maximum?: number
}

export interface DynamicSchema {
  properties: Record<string, DynamicFieldSchema>
  required?: string[]
}

// Flatten Pydantic/OpenAPI 3.1 anyOf nullable patterns.
// e.g. { anyOf: [{type:"string",format:"email"},{type:"null"}] } → {type:"string",format:"email"}
function flattenNullableAnyOf(prop: Record<string, unknown>): DynamicFieldSchema {
  const anyOf = prop.anyOf as Record<string, unknown>[] | undefined
  if (!Array.isArray(anyOf)) return prop as DynamicFieldSchema
  const nonNull = anyOf.filter((v) => v.type !== 'null')
  if (nonNull.length === 1) {
    const { anyOf: _, ...rest } = prop
    return { ...rest, ...nonNull[0] } as DynamicFieldSchema
  }
  return prop as DynamicFieldSchema
}

interface OpenApiResponse {
  components?: {
    schemas?: Record<string, {
      properties?: Record<string, Record<string, unknown>>
      required?: string[]
    }>
  }
}

/**
 * Fetch the dynamic (blueprint) fields for a given OpenAPI schema name,
 * filtering out the provided base fields.
 */
export const getDynamicSchema = async (
  schemaName: string,
  baseFields: string[]
): Promise<DynamicSchema | null> => {
  const response = await apiClient.get<OpenApiResponse>('/openapi.json')
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

export const getTeamSchema = () =>
  getDynamicSchema('TeamWithBlueprints', TEAM_BASE_FIELDS)

// Admin - Teams
export const listTeams = async (): Promise<Team[]> => {
  const response = await apiClient.get<Team[]>('/teams/')
  return Array.isArray(response) ? response : []
}

export const getTeam = (slug: string) =>
  apiClient.get<Team>(`/teams/${encodeURIComponent(slug)}`)

export const createTeam = (team: TeamCreate) =>
  apiClient.post<Team>('/teams/', team)

export const updateTeam = (slug: string, team: TeamCreate) =>
  apiClient.put<Team>(`/teams/${encodeURIComponent(slug)}`, team)

export const deleteTeam = (slug: string) =>
  apiClient.delete<void>(`/teams/${encodeURIComponent(slug)}`)

export const getTeamMembers = async (slug: string): Promise<TeamMember[]> => {
  const response = await apiClient.get<TeamMember[]>(
    `/teams/${encodeURIComponent(slug)}/members`
  )
  return Array.isArray(response) ? response : []
}

export const addTeamMember = (slug: string, email: string) =>
  apiClient.post<void>(`/teams/${encodeURIComponent(slug)}/members`, { email })

export const removeTeamMember = (slug: string, email: string) =>
  apiClient.delete<void>(
    `/teams/${encodeURIComponent(slug)}/members/${encodeURIComponent(email)}`
  )

// Admin - Third-Party Services
export const listThirdPartyServices = async (): Promise<ThirdPartyService[]> => {
  const response = await apiClient.get<ThirdPartyService[]>('/third-party-services/')
  return Array.isArray(response) ? response : []
}

export const getThirdPartyService = (slug: string) =>
  apiClient.get<ThirdPartyService>(`/third-party-services/${encodeURIComponent(slug)}`)

export const createThirdPartyService = (svc: ThirdPartyServiceCreate) =>
  apiClient.post<ThirdPartyService>('/third-party-services/', svc)

export const updateThirdPartyService = (slug: string, svc: ThirdPartyServiceCreate) =>
  apiClient.put<ThirdPartyService>(`/third-party-services/${encodeURIComponent(slug)}`, svc)

export const deleteThirdPartyService = (slug: string) =>
  apiClient.delete<void>(`/third-party-services/${encodeURIComponent(slug)}`)

// Uploads
export const uploadFile = (file: File): Promise<Upload> => {
  const formData = new FormData()
  formData.append('file', file)
  return apiClient.postFormData<Upload>('/uploads/', formData)
}

export const getUploadUrl = (id: string): string => {
  const baseUrl = import.meta.env.VITE_API_URL || '/api'
  return `${baseUrl}/uploads/${encodeURIComponent(id)}`
}

export const getUploadThumbnailUrl = (id: string): string => {
  const baseUrl = import.meta.env.VITE_API_URL || '/api'
  return `${baseUrl}/uploads/${encodeURIComponent(id)}/thumbnail`
}

export const deleteUpload = (id: string) =>
  apiClient.delete<void>(`/uploads/${encodeURIComponent(id)}`)

// API Keys
export const listApiKeys = async (email: string): Promise<ApiKey[]> => {
  const response = await apiClient.get<ApiKey[]>(
    `/users/${encodeURIComponent(email)}/api-keys`
  )
  return Array.isArray(response) ? response : []
}

export const createApiKey = (email: string, name?: string) =>
  apiClient.post<ApiKeyCreated>(
    `/users/${encodeURIComponent(email)}/api-keys`,
    { name: name || 'default' }
  )

export const deleteApiKey = (email: string, keyId: string) =>
  apiClient.delete<void>(
    `/users/${encodeURIComponent(email)}/api-keys/${encodeURIComponent(keyId)}`
  )

// Service Accounts
export const listServiceAccounts = (params?: { is_active?: boolean }) =>
  apiClient.get<ServiceAccount[]>('/service-accounts', params)

export const getServiceAccount = (slug: string) =>
  apiClient.get<ServiceAccount>(`/service-accounts/${encodeURIComponent(slug)}`)

export const createServiceAccount = (data: ServiceAccountCreate) =>
  apiClient.post<ServiceAccount>('/service-accounts', data)

export const updateServiceAccount = (slug: string, data: ServiceAccountCreate) =>
  apiClient.put<ServiceAccount>(`/service-accounts/${encodeURIComponent(slug)}`, data)

export const deleteServiceAccount = (slug: string) =>
  apiClient.delete(`/service-accounts/${encodeURIComponent(slug)}`)

export const addServiceAccountToOrg = (
  slug: string,
  data: { organization_slug: string; role_slug: string }
) =>
  apiClient.post(
    `/service-accounts/${encodeURIComponent(slug)}/organizations`,
    data
  )

export const removeServiceAccountFromOrg = (slug: string, orgSlug: string) =>
  apiClient.delete(
    `/service-accounts/${encodeURIComponent(slug)}/organizations/${encodeURIComponent(orgSlug)}`
  )

// Service Account Client Credentials
export const listClientCredentials = (slug: string) =>
  apiClient.get<ClientCredential[]>(
    `/service-accounts/${encodeURIComponent(slug)}/client-credentials`
  )

export const createClientCredential = (
  slug: string,
  data: ClientCredentialCreate
) =>
  apiClient.post<ClientCredentialCreated>(
    `/service-accounts/${encodeURIComponent(slug)}/client-credentials`,
    data
  )

export const revokeClientCredential = (slug: string, clientId: string) =>
  apiClient.delete(
    `/service-accounts/${encodeURIComponent(slug)}/client-credentials/${encodeURIComponent(clientId)}`
  )

export const rotateClientCredential = (slug: string, clientId: string) =>
  apiClient.post<ClientCredentialCreated>(
    `/service-accounts/${encodeURIComponent(slug)}/client-credentials/${encodeURIComponent(clientId)}/rotate`
  )

// Service Account API Keys
export const listServiceAccountApiKeys = (slug: string) =>
  apiClient.get<ApiKey[]>(
    `/service-accounts/${encodeURIComponent(slug)}/api-keys`
  )

export const createServiceAccountApiKey = (
  slug: string,
  data: {
    name: string
    description?: string
    scopes?: string[]
    expires_in_days?: number
  }
) =>
  apiClient.post<ApiKeyCreated>(
    `/service-accounts/${encodeURIComponent(slug)}/api-keys`,
    data
  )

export const revokeServiceAccountApiKey = (slug: string, keyId: string) =>
  apiClient.delete(
    `/service-accounts/${encodeURIComponent(slug)}/api-keys/${encodeURIComponent(keyId)}`
  )

export const rotateServiceAccountApiKey = (slug: string, keyId: string) =>
  apiClient.post<ApiKeyCreated>(
    `/service-accounts/${encodeURIComponent(slug)}/api-keys/${encodeURIComponent(keyId)}/rotate`
  )
