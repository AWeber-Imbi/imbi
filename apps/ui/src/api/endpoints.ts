import { apiClient } from './client'
import type {
  ApiStatus,
  User,
  Project,
  ActivityFeedEntry,
  Namespace,
  Environment,
  ProjectType,
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
  Upload,
  ApiKey,
  ApiKeyCreated
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

export const refreshBlueprintSchemas = () =>
  apiClient.post<{ refreshed_models: number }>('/schema/refresh', {})

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

const TEAM_BASE_FIELDS = [
  'name', 'slug', 'description', 'icon', 'icon_url',
  'organization', 'organization_slug', 'created_at', 'last_modified_at',
]

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
