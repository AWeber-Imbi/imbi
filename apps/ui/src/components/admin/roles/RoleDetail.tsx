import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, Edit2, Shield, Lock, Plus, X, AlertCircle,
  Users, UsersRound, Info
} from 'lucide-react'
import { Button } from '../../ui/button'
import { Gravatar } from '../../ui/gravatar'
import { getRole, getAdminSettings, getRoleUsers, getRoleGroups, grantPermission, revokePermission } from '@/api/endpoints'
import type { Permission, RoleUser, Group } from '@/types'

interface RoleDetailProps {
  slug: string
  onEdit: () => void
  onBack: () => void
  isDarkMode: boolean
}

type DetailTab = 'permissions' | 'users' | 'groups'

export function RoleDetail({ slug, onEdit, onBack, isDarkMode }: RoleDetailProps) {
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<DetailTab>('permissions')
  const [showAddPermission, setShowAddPermission] = useState(false)
  const [selectedPermission, setSelectedPermission] = useState('')

  // Fetch role with permissions
  const { data: role, isLoading, error } = useQuery({
    queryKey: ['role', slug],
    queryFn: () => getRole(slug),
  })

  // Fetch admin settings for available permissions
  const { data: adminSettings } = useQuery({
    queryKey: ['adminSettings'],
    queryFn: getAdminSettings,
  })

  // Fetch users with this role
  const { data: roleUsers, isLoading: usersLoading } = useQuery({
    queryKey: ['roleUsers', slug],
    queryFn: () => getRoleUsers(slug),
    enabled: activeTab === 'users',
  })

  // Fetch groups with this role
  const { data: roleGroups, isLoading: groupsLoading } = useQuery({
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
    onError: (error: any) => {
      alert(`Failed to grant permission: ${error.response?.data?.detail || error.message}`)
    }
  })

  // Revoke permission mutation
  const revokeMutation = useMutation({
    mutationFn: (permName: string) => revokePermission(slug, permName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['role', slug] })
    },
    onError: (error: any) => {
      alert(`Failed to revoke permission: ${error.response?.data?.detail || error.message}`)
    }
  })

  // Available permissions not already assigned
  const assignedPermNames = new Set(role?.permissions?.map(p => p.name) || [])
  const availablePermissions = (adminSettings?.permissions || [])
    .filter(p => !assignedPermNames.has(p.name))

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
  const groupedPermissions = (role?.permissions || []).reduce<Record<string, Permission[]>>(
    (acc, perm) => {
      const key = perm.resource_type
      if (!acc[key]) acc[key] = []
      acc[key].push(perm)
      return acc
    },
    {}
  )

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
          Loading role...
        </div>
      </div>
    )
  }

  if (error || !role) {
    return (
      <div className={`flex items-center gap-3 p-4 rounded-lg border ${
        isDarkMode ? 'bg-red-900/20 border-red-700 text-red-400' : 'bg-red-50 border-red-200 text-red-700'
      }`}>
        <AlertCircle className="w-5 h-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load role</div>
          <div className="text-sm mt-1">{error instanceof Error ? error.message : 'Role not found'}</div>
        </div>
      </div>
    )
  }

  const tabs: { id: DetailTab; label: string; icon: typeof Shield }[] = [
    { id: 'permissions', label: 'Permissions', icon: Shield },
    { id: 'users', label: 'Users', icon: Users },
    { id: 'groups', label: 'Groups', icon: UsersRound },
  ]

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="outline" onClick={onBack} className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}>
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back
          </Button>
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-lg ${isDarkMode ? 'bg-blue-900/30' : 'bg-blue-100'}`}>
              <Shield className={`w-6 h-6 ${isDarkMode ? 'text-blue-400' : 'text-blue-600'}`} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className={`text-2xl ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
                  {role.name}
                </h2>
                {role.is_system && (
                  <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${
                    isDarkMode ? 'bg-amber-900/30 text-amber-400' : 'bg-amber-100 text-amber-700'
                  }`}>
                    <Lock className="w-3 h-3" />
                    System
                  </span>
                )}
              </div>
              <p className={`mt-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                {role.description || 'No description'}
              </p>
            </div>
          </div>
        </div>
        {!role.is_system && (
          <Button onClick={onEdit} className="bg-[#2A4DD0] hover:bg-blue-700 text-white">
            <Edit2 className="w-4 h-4 mr-2" />
            Edit Role
          </Button>
        )}
      </div>

      {/* Stats Bar */}
      <div className={`flex items-center gap-6 p-4 rounded-lg border ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <div>
          <div className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>Slug</div>
          <div className={`text-sm font-mono ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}>
            {role.slug}
          </div>
        </div>
        <div className={`border-l h-8 ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`} />
        <div>
          <div className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>Priority</div>
          <div className={`text-sm ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}>
            {role.priority}
          </div>
        </div>
        <div className={`border-l h-8 ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`} />
        <div>
          <div className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>Permissions</div>
          <div className={`text-sm ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}>
            {role.permissions?.length || 0}
          </div>
        </div>
        {role.parent_role && (
          <>
            <div className={`border-l h-8 ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`} />
            <div>
              <div className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>Inherits From</div>
              <div className={`text-sm ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}>
                {role.parent_role.name}
              </div>
            </div>
          </>
        )}
      </div>

      {/* Tabs */}
      <div className={`border-b ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}>
        <div className="flex gap-0">
          {tabs.map((tab) => {
            const Icon = tab.icon
            const isActive = activeTab === tab.id
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                  isActive
                    ? isDarkMode
                      ? 'border-blue-400 text-blue-400'
                      : 'border-[#2A4DD0] text-[#2A4DD0]'
                    : isDarkMode
                      ? 'border-transparent text-gray-400 hover:text-gray-200'
                      : 'border-transparent text-gray-600 hover:text-gray-900'
                }`}
              >
                <Icon className="w-4 h-4" />
                {tab.label}
              </button>
            )
          })}
        </div>
      </div>

      {/* Permissions Tab */}
      {activeTab === 'permissions' && (
        <div className="space-y-4">
          {/* Add Permission */}
          {!role.is_system && (
            <div className="flex items-center gap-2">
              {showAddPermission ? (
                <>
                  <select
                    value={selectedPermission}
                    onChange={(e) => setSelectedPermission(e.target.value)}
                    className={`flex-1 px-3 py-2 rounded-md border text-sm ${
                      isDarkMode
                        ? 'bg-gray-700 border-gray-600 text-white'
                        : 'bg-white border-gray-300 text-gray-900'
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
                    className="bg-[#2A4DD0] hover:bg-blue-700 text-white"
                    size="sm"
                  >
                    {grantMutation.isPending ? 'Adding...' : 'Add'}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setShowAddPermission(false)
                      setSelectedPermission('')
                    }}
                    className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
                  >
                    Cancel
                  </Button>
                </>
              ) : (
                <Button
                  onClick={() => setShowAddPermission(true)}
                  variant="outline"
                  size="sm"
                  className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
                >
                  <Plus className="w-4 h-4 mr-1" />
                  Add Permission
                </Button>
              )}
            </div>
          )}

          {/* Grouped Permissions */}
          {Object.keys(groupedPermissions).length === 0 ? (
            <div className={`text-center py-8 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
              <Shield className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <div>No permissions assigned</div>
              {!role.is_system && (
                <div className="text-sm mt-1">Use the button above to add permissions</div>
              )}
            </div>
          ) : (
            Object.entries(groupedPermissions)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([resourceType, perms]) => (
                <div
                  key={resourceType}
                  className={`rounded-lg border ${
                    isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
                  }`}
                >
                  <div className={`px-4 py-3 border-b ${
                    isDarkMode ? 'border-gray-700' : 'border-gray-200'
                  }`}>
                    <h4 className={`text-sm font-medium capitalize ${
                      isDarkMode ? 'text-gray-200' : 'text-gray-900'
                    }`}>
                      {resourceType}
                    </h4>
                  </div>
                  <div className="divide-y divide-gray-100 dark:divide-gray-700">
                    {perms.sort((a, b) => a.action.localeCompare(b.action)).map((perm) => (
                      <div key={perm.name} className="flex items-center justify-between px-4 py-2.5">
                        <div className="flex items-center gap-3">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-mono ${
                            isDarkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-700'
                          }`}>
                            {perm.action}
                          </span>
                          <span className={`text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}>
                            {perm.description || perm.name}
                          </span>
                        </div>
                        {!role.is_system && (
                          <button
                            onClick={() => handleRevokePermission(perm.name)}
                            disabled={revokeMutation.isPending}
                            className={`p-1 rounded ${
                              isDarkMode
                                ? 'text-gray-500 hover:text-red-400 hover:bg-gray-700'
                                : 'text-gray-400 hover:text-red-600 hover:bg-gray-100'
                            }`}
                            title="Remove permission"
                          >
                            <X className="w-4 h-4" />
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ))
          )}
        </div>
      )}

      {/* Users Tab */}
      {activeTab === 'users' && (
        <div className="space-y-4">
          {/* Info banner */}
          <div className={`flex items-start gap-3 p-4 rounded-lg border ${
            isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-blue-50 border-blue-200'
          }`}>
            <Info className={`w-5 h-5 flex-shrink-0 mt-0.5 ${
              isDarkMode ? 'text-blue-400' : 'text-blue-600'
            }`} />
            <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-blue-700'}`}>
              Role assignments are managed via User Management. This list shows users directly assigned this role.
            </div>
          </div>

          {/* User list */}
          {usersLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                Loading users...
              </div>
            </div>
          ) : !roleUsers || roleUsers.length === 0 ? (
            <div className={`text-center py-8 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
              <Users className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <div>No users directly assigned this role</div>
              <div className="text-sm mt-1">Assign this role to users via User Management</div>
            </div>
          ) : (
            <div className={`rounded-lg border overflow-hidden ${
              isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
            }`}>
              <div className={`grid grid-cols-[1fr_auto_auto] gap-4 px-4 py-2.5 text-xs font-medium uppercase tracking-wider border-b ${
                isDarkMode ? 'bg-gray-800 border-gray-700 text-gray-400' : 'bg-gray-50 border-gray-200 text-gray-500'
              }`}>
                <div>User</div>
                <div>Status</div>
                <div>Last Login</div>
              </div>
              <div className={`divide-y ${isDarkMode ? 'divide-gray-700' : 'divide-gray-100'}`}>
                {roleUsers.map((user: RoleUser) => (
                  <div key={user.email} className="grid grid-cols-[1fr_auto_auto] gap-4 items-center px-4 py-3">
                    <div className="flex items-center gap-3 min-w-0">
                      <Gravatar email={user.email} size={32} className="rounded-full flex-shrink-0" />
                      <div className="min-w-0">
                        <div className={`text-sm font-medium truncate ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}>
                          {user.display_name}
                        </div>
                        <div className={`text-xs truncate ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                          {user.email}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {user.is_active ? (
                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                          isDarkMode ? 'bg-green-900/30 text-green-400' : 'bg-green-100 text-green-700'
                        }`}>
                          Active
                        </span>
                      ) : (
                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                          isDarkMode ? 'bg-gray-700 text-gray-400' : 'bg-gray-100 text-gray-500'
                        }`}>
                          Inactive
                        </span>
                      )}
                      {user.is_service_account && (
                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                          isDarkMode ? 'bg-purple-900/30 text-purple-400' : 'bg-purple-100 text-purple-700'
                        }`}>
                          Service
                        </span>
                      )}
                    </div>
                    <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
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

      {/* Groups Tab */}
      {activeTab === 'groups' && (
        <div className="space-y-4">
          {/* Info banner */}
          <div className={`flex items-start gap-3 p-4 rounded-lg border ${
            isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-blue-50 border-blue-200'
          }`}>
            <Info className={`w-5 h-5 flex-shrink-0 mt-0.5 ${
              isDarkMode ? 'text-blue-400' : 'text-blue-600'
            }`} />
            <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-blue-700'}`}>
              Role assignments to groups are managed via Group Management. All members of a group inherit the group's roles.
            </div>
          </div>

          {/* Group list */}
          {groupsLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                Loading groups...
              </div>
            </div>
          ) : !roleGroups || roleGroups.length === 0 ? (
            <div className={`text-center py-8 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
              <UsersRound className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <div>No groups assigned this role</div>
              <div className="text-sm mt-1">Assign this role to groups via Group Management</div>
            </div>
          ) : (
            <div className={`rounded-lg border overflow-hidden ${
              isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
            }`}>
              <div className={`grid grid-cols-[1fr_1fr] gap-4 px-4 py-2.5 text-xs font-medium uppercase tracking-wider border-b ${
                isDarkMode ? 'bg-gray-800 border-gray-700 text-gray-400' : 'bg-gray-50 border-gray-200 text-gray-500'
              }`}>
                <div>Group</div>
                <div>Description</div>
              </div>
              <div className={`divide-y ${isDarkMode ? 'divide-gray-700' : 'divide-gray-100'}`}>
                {roleGroups.map((group: Group) => (
                  <div key={group.slug} className="grid grid-cols-[1fr_1fr] gap-4 items-center px-4 py-3">
                    <div className="flex items-center gap-3 min-w-0">
                      <div className={`p-1.5 rounded ${isDarkMode ? 'bg-gray-700' : 'bg-gray-100'}`}>
                        <UsersRound className={`w-4 h-4 ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`} />
                      </div>
                      <div className="min-w-0">
                        <div className={`text-sm font-medium truncate ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}>
                          {group.name}
                        </div>
                        <div className={`text-xs font-mono truncate ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                          {group.slug}
                        </div>
                      </div>
                    </div>
                    <div className={`text-sm truncate ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                      {group.description || 'No description'}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
