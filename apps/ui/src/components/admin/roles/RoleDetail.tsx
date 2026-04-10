import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '@/api/client'
import {
  ArrowLeft,
  Edit2,
  Shield,
  Lock,
  Plus,
  Trash2,
  AlertCircle,
  Users,
  UsersRound,
  Info,
  Bot,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Gravatar } from '@/components/ui/gravatar'
import {
  getRole,
  getAdminSettings,
  getRoleUsers,
  getRoleServiceAccounts,
  getRoleGroups,
  grantPermission,
  revokePermission,
} from '@/api/endpoints'
import type { Permission, RoleUser, ServiceAccount } from '@/types'

interface RoleDetailProps {
  slug: string
  onEdit: () => void
  onBack: () => void
  isDarkMode: boolean
}

type DetailTab = 'permissions' | 'users' | 'service-accounts' | 'groups'

export function RoleDetail({
  slug,
  onEdit,
  onBack,
  isDarkMode,
}: RoleDetailProps) {
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<DetailTab>('permissions')
  const [showAddPermission, setShowAddPermission] = useState(false)
  const [selectedPermission, setSelectedPermission] = useState('')

  // Fetch role with permissions
  const {
    data: role,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['role', slug],
    queryFn: () => getRole(slug),
  })

  // Fetch admin settings for available permissions
  const { data: adminSettings } = useQuery({
    queryKey: ['adminSettings'],
    queryFn: getAdminSettings,
  })

  // Fetch users with this role
  const {
    data: roleUsers,
    isLoading: usersLoading,
    error: usersError,
  } = useQuery({
    queryKey: ['roleUsers', slug],
    queryFn: () => getRoleUsers(slug),
    enabled: activeTab === 'users',
  })

  // Fetch service accounts with this role
  const {
    data: roleServiceAccounts,
    isLoading: saLoading,
    error: saError,
  } = useQuery({
    queryKey: ['roleServiceAccounts', slug],
    queryFn: () => getRoleServiceAccounts(slug),
    enabled: activeTab === 'service-accounts',
  })

  // Fetch groups with this role
  const {
    data: roleGroups,
    isLoading: groupsLoading,
    error: groupsError,
  } = useQuery({
    queryKey: ['roleGroups', slug],
    queryFn: () => getRoleGroups(slug),
    enabled: activeTab === 'groups',
  })

  // Grant permission mutation
  const grantMutation = useMutation({
    mutationFn: (permName: string) => grantPermission(slug, permName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['role', slug] })
      setShowAddPermission(false)
      setSelectedPermission('')
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      alert(
        `Failed to grant permission: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  // Revoke permission mutation
  const revokeMutation = useMutation({
    mutationFn: (permName: string) => revokePermission(slug, permName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['role', slug] })
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      alert(
        `Failed to revoke permission: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  // Available permissions not already assigned
  const assignedPermNames = new Set(role?.permissions?.map((p) => p.name) || [])
  const availablePermissions = (adminSettings?.permissions || []).filter(
    (p) => !assignedPermNames.has(p.name),
  )

  const handleGrantPermission = () => {
    if (selectedPermission) {
      grantMutation.mutate(selectedPermission)
    }
  }

  const handleRevokePermission = (permName: string) => {
    if (confirm(`Remove permission "${permName}" from this role?`)) {
      revokeMutation.mutate(permName)
    }
  }

  // Group permissions by resource type
  const groupedPermissions = (role?.permissions || []).reduce<
    Record<string, Permission[]>
  >((acc, perm) => {
    const key = perm.resource_type
    if (!acc[key]) acc[key] = []
    acc[key].push(perm)
    return acc
  }, {})

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div
          className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
        >
          Loading role...
        </div>
      </div>
    )
  }

  if (error || !role) {
    return (
      <div
        className={`flex items-center gap-3 rounded-lg border p-4 ${
          isDarkMode
            ? 'border-red-700 bg-red-900/20 text-red-400'
            : 'border-red-200 bg-red-50 text-red-700'
        }`}
      >
        <AlertCircle className="h-5 w-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load role</div>
          <div className="mt-1 text-sm">
            {error instanceof Error ? error.message : 'Role not found'}
          </div>
        </div>
      </div>
    )
  }

  const tabs: { id: DetailTab; label: string; icon: typeof Shield }[] = [
    { id: 'permissions', label: 'Permissions', icon: Shield },
    { id: 'users', label: 'Users', icon: Users },
    { id: 'service-accounts', label: 'Service Accounts', icon: Bot },
    { id: 'groups', label: 'Groups', icon: UsersRound },
  ]

  return (
    <div className="space-y-6">
      {/* Back button */}
      <div>
        <Button
          variant="outline"
          onClick={onBack}
          className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
        >
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back
        </Button>
      </div>

      {/* Role info card */}
      <div
        className={`rounded-lg border ${isDarkMode ? 'border-gray-700 bg-gray-800' : 'border-gray-200 bg-white'}`}
      >
        {/* Title row */}
        <div
          className={`flex items-start justify-between border-b px-6 py-5 ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
        >
          <div className="flex items-center gap-3">
            <div
              className={`rounded-lg p-2 ${isDarkMode ? 'bg-blue-900/30' : 'bg-blue-100'}`}
            >
              <Shield
                className={`h-6 w-6 ${isDarkMode ? 'text-blue-400' : 'text-blue-600'}`}
              />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2
                  className={`text-2xl ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
                >
                  {role.name}
                </h2>
                {role.is_system && (
                  <span
                    className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium ${
                      isDarkMode
                        ? 'bg-amber-900/30 text-amber-400'
                        : 'bg-amber-100 text-amber-700'
                    }`}
                  >
                    <Lock className="h-3 w-3" />
                    System
                  </span>
                )}
              </div>
              <p
                className={`mt-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                {role.description || 'No description'}
              </p>
            </div>
          </div>
          {!role.is_system && (
            <Button
              onClick={onEdit}
              className="bg-amber-border text-white hover:bg-amber-border-strong"
            >
              <Edit2 className="mr-2 h-4 w-4" />
              Edit Role
            </Button>
          )}
        </div>

        {/* Stats Bar */}
        <div
          className={`flex items-center gap-6 border-b px-6 py-4 ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
        >
          <div>
            <div
              className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
            >
              Slug
            </div>
            <div
              className={`font-mono text-sm ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}
            >
              {role.slug}
            </div>
          </div>
          <div
            className={`h-8 border-l ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
          />
          <div>
            <div
              className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
            >
              Priority
            </div>
            <div
              className={`text-sm ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}
            >
              {role.priority}
            </div>
          </div>
          <div
            className={`h-8 border-l ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
          />
          <div>
            <div
              className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
            >
              Permissions
            </div>
            <div
              className={`text-sm ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}
            >
              {role.permissions?.length || 0}
            </div>
          </div>
          {role.parent_role && (
            <>
              <div
                className={`h-8 border-l ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
              />
              <div>
                <div
                  className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                >
                  Inherits From
                </div>
                <div
                  className={`text-sm ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}
                >
                  {role.parent_role.name}
                </div>
              </div>
            </>
          )}
        </div>

        {/* Tabs */}
        <div
          className={`border-b ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
        >
          <div className="flex gap-0 px-6">
            {tabs.map((tab) => {
              const Icon = tab.icon
              const isActive = activeTab === tab.id
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors ${
                    isActive
                      ? isDarkMode
                        ? 'border-blue-400 text-blue-400'
                        : 'border-[#2A4DD0] text-[#2A4DD0]'
                      : isDarkMode
                        ? 'border-transparent text-gray-400 hover:text-gray-200'
                        : 'border-transparent text-gray-600 hover:text-gray-900'
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  {tab.label}
                </button>
              )
            })}
          </div>
        </div>
      </div>

      {/* Permissions Tab */}
      {activeTab === 'permissions' && (
        <div className="space-y-4">
          {/* Add Permission Section */}
          {!role.is_system && (
            <div
              className={`rounded-lg border p-4 ${
                isDarkMode
                  ? 'border-gray-700 bg-gray-800'
                  : 'border-gray-200 bg-white'
              }`}
            >
              <div className="mb-3 flex items-center justify-between">
                <h3
                  className={`text-sm font-medium ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
                >
                  Assign Permission
                </h3>
                <button
                  onClick={() => setShowAddPermission(!showAddPermission)}
                  className={`text-sm ${isDarkMode ? 'text-blue-400 hover:text-blue-300' : 'text-[#2A4DD0] hover:text-blue-700'}`}
                >
                  {showAddPermission ? 'Cancel' : 'Add Permission'}
                </button>
              </div>

              {showAddPermission && (
                <div className="flex items-center gap-2">
                  <select
                    value={selectedPermission}
                    onChange={(e) => setSelectedPermission(e.target.value)}
                    className={`flex-1 rounded-lg border px-3 py-2 text-sm ${
                      isDarkMode
                        ? 'border-gray-600 bg-gray-700 text-white'
                        : 'border-gray-300 bg-white text-gray-900'
                    }`}
                  >
                    <option value="">Select a permission...</option>
                    {availablePermissions.map((perm) => (
                      <option key={perm.name} value={perm.name}>
                        {perm.name} - {perm.description || perm.action}
                      </option>
                    ))}
                  </select>
                  <Button
                    onClick={handleGrantPermission}
                    disabled={!selectedPermission || grantMutation.isPending}
                    className="bg-amber-border text-white hover:bg-amber-border-strong"
                    size="sm"
                  >
                    <Plus className="mr-2 h-4 w-4" />
                    {grantMutation.isPending ? 'Adding...' : 'Assign'}
                  </Button>
                </div>
              )}

              <div
                className={`mt-3 flex items-start gap-2 rounded p-2 text-xs ${
                  isDarkMode
                    ? 'bg-blue-900/20 text-blue-400'
                    : 'bg-blue-50 text-blue-700'
                }`}
              >
                <AlertCircle className="mt-0.5 h-3 w-3 flex-shrink-0" />
                <span>
                  Permissions define what actions users with this role can
                  perform
                </span>
              </div>
            </div>
          )}

          {/* Permissions Table */}
          {Object.keys(groupedPermissions).length === 0 ? (
            <div
              className={`py-8 text-center ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
            >
              <Shield className="mx-auto mb-2 h-8 w-8 opacity-50" />
              <div>No permissions assigned</div>
              {!role.is_system && (
                <div className="mt-1 text-sm">
                  Use the section above to add permissions
                </div>
              )}
            </div>
          ) : (
            <div
              className={`overflow-hidden rounded-lg border ${
                isDarkMode
                  ? 'border-gray-700 bg-gray-800'
                  : 'border-gray-200 bg-white'
              }`}
            >
              <table className="w-full">
                <thead className="border-b border-tertiary bg-secondary">
                  <tr>
                    <th
                      className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                        isDarkMode ? 'text-gray-400' : 'text-gray-500'
                      }`}
                    >
                      Permission
                    </th>
                    <th
                      className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                        isDarkMode ? 'text-gray-400' : 'text-gray-500'
                      }`}
                    >
                      Description
                    </th>
                    {!role.is_system && (
                      <th
                        className={`px-6 py-3 text-right text-xs uppercase tracking-wider ${
                          isDarkMode ? 'text-gray-400' : 'text-gray-500'
                        }`}
                      >
                        Actions
                      </th>
                    )}
                  </tr>
                </thead>
                <tbody
                  className={
                    isDarkMode
                      ? 'divide-y divide-gray-700'
                      : 'divide-y divide-gray-200'
                  }
                >
                  {(role.permissions || [])
                    .sort((a, b) => a.name.localeCompare(b.name))
                    .map((perm) => (
                      <tr
                        key={perm.name}
                        className={
                          isDarkMode ? 'hover:bg-gray-700' : 'hover:bg-gray-50'
                        }
                      >
                        <td
                          className={`px-6 py-4 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
                        >
                          <code
                            className={`rounded px-2 py-1 text-sm ${
                              isDarkMode
                                ? 'bg-gray-700 text-blue-400'
                                : 'bg-gray-100 text-[#2A4DD0]'
                            }`}
                          >
                            {perm.name}
                          </code>
                        </td>
                        <td
                          className={`px-6 py-4 text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                        >
                          {perm.description || perm.action}
                        </td>
                        {!role.is_system && (
                          <td className="px-6 py-4 text-right">
                            <button
                              onClick={() => handleRevokePermission(perm.name)}
                              disabled={revokeMutation.isPending}
                              className={`rounded p-1.5 ${
                                isDarkMode
                                  ? 'text-red-400 hover:bg-red-900/20'
                                  : 'text-red-600 hover:bg-red-50'
                              }`}
                              title="Remove permission"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </td>
                        )}
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Users Tab */}
      {activeTab === 'users' && (
        <div className="space-y-4">
          {/* Info banner */}
          <div
            className={`flex items-start gap-3 rounded-lg border p-4 ${
              isDarkMode
                ? 'border-gray-700 bg-gray-800'
                : 'border-blue-200 bg-blue-50'
            }`}
          >
            <Info
              className={`mt-0.5 h-5 w-5 flex-shrink-0 ${
                isDarkMode ? 'text-blue-400' : 'text-blue-600'
              }`}
            />
            <div
              className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-blue-700'}`}
            >
              Role assignments are managed via User Management. This list shows
              users directly assigned this role.
            </div>
          </div>

          {/* User list */}
          {usersLoading ? (
            <div className="flex items-center justify-center py-8">
              <div
                className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                Loading users...
              </div>
            </div>
          ) : usersError ? (
            <div
              className={`flex items-center gap-3 rounded-lg border p-4 ${
                isDarkMode
                  ? 'border-red-700 bg-red-900/20 text-red-400'
                  : 'border-red-200 bg-red-50 text-red-700'
              }`}
            >
              <AlertCircle className="h-5 w-5 flex-shrink-0" />
              <div>
                <div className="font-medium">Failed to load users</div>
                <div className="mt-1 text-sm">
                  {usersError instanceof Error
                    ? usersError.message
                    : 'An error occurred'}
                </div>
              </div>
            </div>
          ) : !roleUsers || roleUsers.length === 0 ? (
            <div
              className={`py-8 text-center ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
            >
              <Users className="mx-auto mb-2 h-8 w-8 opacity-50" />
              <div>No users directly assigned this role</div>
              <div className="mt-1 text-sm">
                Assign this role to users via User Management
              </div>
            </div>
          ) : (
            <div
              className={`overflow-hidden rounded-lg border ${
                isDarkMode
                  ? 'border-gray-700 bg-gray-800'
                  : 'border-gray-200 bg-white'
              }`}
            >
              <div
                className={`grid grid-cols-[1fr_auto_auto] gap-4 border-b px-4 py-2.5 text-xs font-medium uppercase tracking-wider ${
                  isDarkMode
                    ? 'border-gray-700 bg-gray-800 text-gray-400'
                    : 'border-gray-200 bg-gray-50 text-gray-500'
                }`}
              >
                <div>User</div>
                <div>Status</div>
                <div>Last Login</div>
              </div>
              <div
                className={`divide-y ${isDarkMode ? 'divide-gray-700' : 'divide-gray-100'}`}
              >
                {roleUsers.map((user: RoleUser) => (
                  <div
                    key={user.email}
                    className="grid grid-cols-[1fr_auto_auto] items-center gap-4 px-4 py-3"
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <Gravatar
                        email={user.email}
                        size={32}
                        className="flex-shrink-0 rounded-full"
                      />
                      <div className="min-w-0">
                        <div
                          className={`truncate text-sm font-medium ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}
                        >
                          {user.display_name}
                        </div>
                        <div
                          className={`truncate text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
                        >
                          {user.email}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {user.is_active ? (
                        <span
                          className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${
                            isDarkMode
                              ? 'bg-green-900/30 text-green-400'
                              : 'bg-green-100 text-green-700'
                          }`}
                        >
                          Active
                        </span>
                      ) : (
                        <span
                          className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${
                            isDarkMode
                              ? 'bg-gray-700 text-gray-400'
                              : 'bg-gray-100 text-gray-500'
                          }`}
                        >
                          Inactive
                        </span>
                      )}
                      {user.is_service_account && (
                        <span
                          className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${
                            isDarkMode
                              ? 'bg-purple-900/30 text-purple-400'
                              : 'bg-purple-100 text-purple-700'
                          }`}
                        >
                          Service
                        </span>
                      )}
                    </div>
                    <div
                      className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
                    >
                      {user.last_login
                        ? new Date(user.last_login).toLocaleDateString()
                        : 'Never'}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Service Accounts Tab */}
      {activeTab === 'service-accounts' && (
        <div className="space-y-4">
          {/* Info banner */}
          <div
            className={`flex items-start gap-3 rounded-lg border p-4 ${
              isDarkMode
                ? 'border-gray-700 bg-gray-800'
                : 'border-blue-200 bg-blue-50'
            }`}
          >
            <Info
              className={`mt-0.5 h-5 w-5 flex-shrink-0 ${
                isDarkMode ? 'text-blue-400' : 'text-blue-600'
              }`}
            />
            <div
              className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-blue-700'}`}
            >
              Role assignments are managed via Service Account Management. This
              list shows service accounts assigned this role via organization
              membership.
            </div>
          </div>

          {/* Service account list */}
          {saLoading ? (
            <div className="flex items-center justify-center py-8">
              <div
                className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                Loading service accounts...
              </div>
            </div>
          ) : saError ? (
            <div
              className={`flex items-center gap-3 rounded-lg border p-4 ${
                isDarkMode
                  ? 'border-red-700 bg-red-900/20 text-red-400'
                  : 'border-red-200 bg-red-50 text-red-700'
              }`}
            >
              <AlertCircle className="h-5 w-5 flex-shrink-0" />
              <div>
                <div className="font-medium">
                  Failed to load service accounts
                </div>
                <div className="mt-1 text-sm">
                  {saError instanceof Error
                    ? saError.message
                    : 'An error occurred'}
                </div>
              </div>
            </div>
          ) : !roleServiceAccounts || roleServiceAccounts.length === 0 ? (
            <div
              className={`py-8 text-center ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
            >
              <Bot className="mx-auto mb-2 h-8 w-8 opacity-50" />
              <div>No service accounts assigned this role</div>
              <div className="mt-1 text-sm">
                Assign this role to service accounts via Service Account
                Management
              </div>
            </div>
          ) : (
            <div
              className={`overflow-hidden rounded-lg border ${
                isDarkMode
                  ? 'border-gray-700 bg-gray-800'
                  : 'border-gray-200 bg-white'
              }`}
            >
              <div
                className={`grid grid-cols-[1fr_auto_auto] gap-4 border-b px-4 py-2.5 text-xs font-medium uppercase tracking-wider ${
                  isDarkMode
                    ? 'border-gray-700 bg-gray-800 text-gray-400'
                    : 'border-gray-200 bg-gray-50 text-gray-500'
                }`}
              >
                <div>Service Account</div>
                <div>Status</div>
                <div>Last Authenticated</div>
              </div>
              <div
                className={`divide-y ${isDarkMode ? 'divide-gray-700' : 'divide-gray-100'}`}
              >
                {roleServiceAccounts.map((sa: ServiceAccount) => (
                  <div
                    key={sa.slug}
                    className="grid grid-cols-[1fr_auto_auto] items-center gap-4 px-4 py-3"
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <div
                        className={`rounded-full p-1.5 ${isDarkMode ? 'bg-purple-900/30' : 'bg-purple-100'}`}
                      >
                        <Bot
                          className={`h-4 w-4 ${isDarkMode ? 'text-purple-400' : 'text-purple-600'}`}
                        />
                      </div>
                      <div className="min-w-0">
                        <div
                          className={`truncate text-sm font-medium ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}
                        >
                          {sa.display_name}
                        </div>
                        <div
                          className={`truncate font-mono text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
                        >
                          {sa.slug}
                        </div>
                      </div>
                    </div>
                    <div>
                      {sa.is_active ? (
                        <span
                          className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${
                            isDarkMode
                              ? 'bg-green-900/30 text-green-400'
                              : 'bg-green-100 text-green-700'
                          }`}
                        >
                          Active
                        </span>
                      ) : (
                        <span
                          className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${
                            isDarkMode
                              ? 'bg-gray-700 text-gray-400'
                              : 'bg-gray-100 text-gray-500'
                          }`}
                        >
                          Inactive
                        </span>
                      )}
                    </div>
                    <div
                      className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
                    >
                      {sa.last_authenticated
                        ? new Date(sa.last_authenticated).toLocaleDateString()
                        : 'Never'}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Groups Tab */}
      {activeTab === 'groups' && (
        <div className="space-y-4">
          {/* Info banner */}
          <div
            className={`flex items-start gap-3 rounded-lg border p-4 ${
              isDarkMode
                ? 'border-gray-700 bg-gray-800'
                : 'border-blue-200 bg-blue-50'
            }`}
          >
            <Info
              className={`mt-0.5 h-5 w-5 flex-shrink-0 ${
                isDarkMode ? 'text-blue-400' : 'text-blue-600'
              }`}
            />
            <div
              className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-blue-700'}`}
            >
              Role assignments to teams are managed via Team Management. All
              members of a team inherit the team's roles.
            </div>
          </div>

          {/* Group list */}
          {groupsLoading ? (
            <div className="flex items-center justify-center py-8">
              <div
                className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                Loading groups...
              </div>
            </div>
          ) : groupsError ? (
            <div
              className={`flex items-center gap-3 rounded-lg border p-4 ${
                isDarkMode
                  ? 'border-red-700 bg-red-900/20 text-red-400'
                  : 'border-red-200 bg-red-50 text-red-700'
              }`}
            >
              <AlertCircle className="h-5 w-5 flex-shrink-0" />
              <div>
                <div className="font-medium">Failed to load groups</div>
                <div className="mt-1 text-sm">
                  {groupsError instanceof Error
                    ? groupsError.message
                    : 'An error occurred'}
                </div>
              </div>
            </div>
          ) : !roleGroups || roleGroups.length === 0 ? (
            <div
              className={`py-8 text-center ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
            >
              <UsersRound className="mx-auto mb-2 h-8 w-8 opacity-50" />
              <div>No groups assigned this role</div>
              <div className="mt-1 text-sm">
                Assign this role to teams via Team Management
              </div>
            </div>
          ) : (
            <div
              className={`overflow-hidden rounded-lg border ${
                isDarkMode
                  ? 'border-gray-700 bg-gray-800'
                  : 'border-gray-200 bg-white'
              }`}
            >
              <div
                className={`grid grid-cols-[1fr_1fr] gap-4 border-b px-4 py-2.5 text-xs font-medium uppercase tracking-wider ${
                  isDarkMode
                    ? 'border-gray-700 bg-gray-800 text-gray-400'
                    : 'border-gray-200 bg-gray-50 text-gray-500'
                }`}
              >
                <div>Group</div>
                <div>Description</div>
              </div>
              <div
                className={`divide-y ${isDarkMode ? 'divide-gray-700' : 'divide-gray-100'}`}
              >
                {roleGroups.map(
                  (group: {
                    name: string
                    slug: string
                    description?: string | null
                  }) => (
                    <div
                      key={group.slug}
                      className="grid grid-cols-[1fr_1fr] items-center gap-4 px-4 py-3"
                    >
                      <div className="flex min-w-0 items-center gap-3">
                        <div
                          className={`rounded p-1.5 ${isDarkMode ? 'bg-gray-700' : 'bg-gray-100'}`}
                        >
                          <UsersRound
                            className={`h-4 w-4 ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}
                          />
                        </div>
                        <div className="min-w-0">
                          <div
                            className={`truncate text-sm font-medium ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}
                          >
                            {group.name}
                          </div>
                          <div
                            className={`truncate font-mono text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
                          >
                            {group.slug}
                          </div>
                        </div>
                      </div>
                      <div
                        className={`truncate text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
                      >
                        {group.description || 'No description'}
                      </div>
                    </div>
                  ),
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
