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
  AdminUserCreate
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
  const response = await apiClient.get<CollectionResponse<AdminUser>>('/users', params)
  return response.data
}

export const getAdminUser = (email: string) =>
  apiClient.get<AdminUser>(`/users/${encodeURIComponent(email)}`)

export const createAdminUser = (user: AdminUserCreate) =>
  apiClient.post<AdminUser>('/users', user)

export const updateAdminUser = (email: string, user: AdminUserCreate) =>
  apiClient.put<AdminUser>(`/users/${encodeURIComponent(email)}`, user)

export const deleteAdminUser = (email: string) =>
  apiClient.delete<void>(`/users/${encodeURIComponent(email)}`)
