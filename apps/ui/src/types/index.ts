// API Response Wrappers
export interface CollectionResponse<T> {
  data: T[]
}

// API Response Types
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

export interface User {
  username: string
  display_name: string
  email_address: string
  user_type: string
  external_id?: string
  groups?: string[]
}

export interface Project {
  id: number
  namespace_id: number
  namespace: string
  project_type_id: number
  project_type: string
  name: string
  slug: string
  description?: string
  environments?: string[]
  archived?: boolean
  created_at: string
  last_modified_at?: string
}

export interface Namespace {
  id: number
  name: string
  slug: string
  icon_class?: string
  maintained_by?: string[]
}

export interface Environment {
  name: string
  description?: string
  icon_class?: string
}

export interface ProjectType {
  id: number
  name: string
  plural_name: string
  slug: string
  description?: string
  icon_class?: string
  environment_urls?: boolean
}

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
  change_type: 'Configured' | 'Decommissioned' | 'Deployed' | 'Migrated' | 'Provisioned' | 'Restarted' | 'Rolled Back' | 'Scaled' | 'Upgraded'
  description: string
  link?: string | null
  notes?: string | null
  ticket_slug?: string | null
  version?: string | null
}

export type ActivityFeedEntry = ProjectFeedEntry | OperationsLogEntry

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

export interface AuthProvider {
  id: string
  type: 'oauth' | 'password'
  name: string
  enabled: boolean
  auth_url?: string
  icon: string
}

export interface LoginRequest {
  email: string
  password: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
  expires_in: number
}

export interface UserResponse extends User {
  groups?: string[]
  roles?: string[]
  permissions?: string[]
  created_at?: string
  last_modified_at?: string
  is_active?: boolean
  is_admin?: boolean
  is_service_account?: boolean
  last_login?: string | null
  avatar_url?: string | null
}

export interface UseAuthReturn {
  user: User | null
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
export interface Permission {
  name: string
  resource_type: string
  action: string
  description?: string | null
}

export interface Role {
  name: string
  slug: string
  description?: string | null
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

export interface AdminSettings {
  permissions: Permission[]
  oauth_provider_types: string[]
  auth_methods: string[]
  auth_types: string[]
}

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

export interface Group {
  name: string
  slug: string
  description?: string | null
  icon_url?: string | null
  parent?: Group | null
  roles: Role[]
}

export interface AdminUser {
  email: string
  display_name: string
  is_active: boolean
  is_admin: boolean
  is_service_account: boolean
  created_at: string
  last_login?: string | null
  avatar_url?: string | null
  groups: Group[]
  roles: Role[]
}

export interface AdminUserCreate {
  email: string
  display_name: string
  password?: string | null
  is_active?: boolean
  is_admin?: boolean
  is_service_account?: boolean
}
