import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, Edit2, Users, Shield, UsersRound, Plus, X, AlertCircle, Info
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Gravatar } from '@/components/ui/gravatar'
import { getGroup, getGroupMembers, getRoles, assignGroupRole, unassignGroupRole } from '@/api/endpoints'
import type { GroupMember, Role } from '@/types'

interface GroupDetailProps {
  slug: string
  onEdit: () => void
  onBack: () => void
  isDarkMode: boolean
}

type DetailTab = 'members' | 'roles'

export function GroupDetail({ slug, onEdit, onBack, isDarkMode }: GroupDetailProps) {
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<DetailTab>('members')
  const [showAddRole, setShowAddRole] = useState(false)
  const [selectedRole, setSelectedRole] = useState('')

  const { data: group, isLoading, error } = useQuery({
    queryKey: ['group', slug],
    queryFn: () => getGroup(slug),
  })

  const { data: members, isLoading: membersLoading, error: membersError } = useQuery({
    queryKey: ['groupMembers', slug],
    queryFn: () => getGroupMembers(slug),
    enabled: activeTab === 'members',
  })

  const { data: allRoles } = useQuery({
    queryKey: ['roles'],
    queryFn: getRoles,
  })

  const assignRoleMutation = useMutation({
    mutationFn: (roleSlug: string) => assignGroupRole(slug, roleSlug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['group', slug] })
      setShowAddRole(false)
      setSelectedRole('')
    },
    onError: (error: any) => {
      alert(`Failed to assign role: ${error.response?.data?.detail || error.message}`)
    }
  })

  const unassignRoleMutation = useMutation({
    mutationFn: (roleSlug: string) => unassignGroupRole(slug, roleSlug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['group', slug] })
    },
    onError: (error: any) => {
      alert(`Failed to remove role: ${error.response?.data?.detail || error.message}`)
    }
  })

  const assignedRoleSlugs = new Set(group?.roles?.map(r => r.slug) || [])
  const availableRoles = (allRoles || []).filter(r => !assignedRoleSlugs.has(r.slug))

  const handleAssignRole = () => {
    if (selectedRole) {
      assignRoleMutation.mutate(selectedRole)
    }
  }

  const handleUnassignRole = (roleSlug: string) => {
    const role = group?.roles?.find(r => r.slug === roleSlug)
    if (confirm(`Remove role "${role?.name || roleSlug}" from this group? All members will lose permissions from this role.`)) {
      unassignRoleMutation.mutate(roleSlug)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
          Loading group...
        </div>
      </div>
    )
  }

  if (error || !group) {
    return (
      <div className={`flex items-center gap-3 p-4 rounded-lg border ${
        isDarkMode ? 'bg-red-900/20 border-red-700 text-red-400' : 'bg-red-50 border-red-200 text-red-700'
      }`}>
        <AlertCircle className="w-5 h-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load group</div>
          <div className="text-sm mt-1">{error instanceof Error ? error.message : 'Group not found'}</div>
        </div>
      </div>
    )
  }

  const tabs: { id: DetailTab; label: string; icon: typeof Users }[] = [
    { id: 'members', label: 'Members', icon: Users },
    { id: 'roles', label: 'Roles', icon: Shield },
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
              <UsersRound className={`w-6 h-6 ${isDarkMode ? 'text-blue-400' : 'text-blue-600'}`} />
            </div>
            <div>
              <h2 className={`text-2xl ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
                {group.name}
              </h2>
              <p className={`mt-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                {group.description || 'No description'}
              </p>
            </div>
          </div>
        </div>
        <Button onClick={onEdit} className="bg-[#2A4DD0] hover:bg-blue-700 text-white">
          <Edit2 className="w-4 h-4 mr-2" />
          Edit Group
        </Button>
      </div>

      {/* Stats Bar */}
      <div className={`flex items-center gap-6 p-4 rounded-lg border ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <div>
          <div className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>Slug</div>
          <div className={`text-sm font-mono ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}>
            {group.slug}
          </div>
        </div>
        <div className={`border-l h-8 ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`} />
        <div>
          <div className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>Roles</div>
          <div className={`text-sm ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}>
            {group.roles?.length || 0}
          </div>
        </div>
        {group.parent && (
          <>
            <div className={`border-l h-8 ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`} />
            <div>
              <div className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>Parent Group</div>
              <div className={`text-sm ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}>
                {group.parent.name}
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

      {/* Members Tab */}
      {activeTab === 'members' && (
        <div className="space-y-4">
          {/* Info banner */}
          <div className={`flex items-start gap-3 p-4 rounded-lg border ${
            isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-blue-50 border-blue-200'
          }`}>
            <Info className={`w-5 h-5 flex-shrink-0 mt-0.5 ${
              isDarkMode ? 'text-blue-400' : 'text-blue-600'
            }`} />
            <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-blue-700'}`}>
              Group membership is managed via User Management. This list shows users currently in this group.
            </div>
          </div>

          {/* Member list */}
          {membersLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                Loading members...
              </div>
            </div>
          ) : membersError ? (
            <div className={`flex items-center gap-3 p-4 rounded-lg border ${
              isDarkMode ? 'bg-red-900/20 border-red-700 text-red-400' : 'bg-red-50 border-red-200 text-red-700'
            }`}>
              <AlertCircle className="w-5 h-5 flex-shrink-0" />
              <div>
                <div className="font-medium">Failed to load members</div>
                <div className="text-sm mt-1">
                  {membersError instanceof Error ? membersError.message : 'An error occurred'}
                </div>
              </div>
            </div>
          ) : !members || members.length === 0 ? (
            <div className={`text-center py-8 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
              <Users className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <div>No members in this group</div>
              <div className="text-sm mt-1">Add users to this group via User Management</div>
            </div>
          ) : (
            <div className={`rounded-lg border overflow-hidden ${
              isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
            }`}>
              <div className={`grid grid-cols-[1fr_auto_auto] gap-4 px-4 py-2.5 text-xs font-medium uppercase tracking-wider border-b ${
                isDarkMode ? 'bg-gray-800 border-gray-700 text-gray-400' : 'bg-gray-50 border-gray-200 text-gray-500'
              }`}>
                <div>Member</div>
                <div>Status</div>
                <div>Last Login</div>
              </div>
              <div className={`divide-y ${isDarkMode ? 'divide-gray-700' : 'divide-gray-100'}`}>
                {members.map((member: GroupMember) => (
                  <div key={member.email} className="grid grid-cols-[1fr_auto_auto] gap-4 items-center px-4 py-3">
                    <div className="flex items-center gap-3 min-w-0">
                      <Gravatar email={member.email} size={32} className="rounded-full flex-shrink-0" />
                      <div className="min-w-0">
                        <div className={`text-sm font-medium truncate ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}>
                          {member.display_name}
                        </div>
                        <div className={`text-xs truncate ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                          {member.email}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {member.is_active ? (
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
                      {member.is_service_account && (
                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                          isDarkMode ? 'bg-purple-900/30 text-purple-400' : 'bg-purple-100 text-purple-700'
                        }`}>
                          Service
                        </span>
                      )}
                    </div>
                    <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                      {member.last_login
                        ? new Date(member.last_login).toLocaleDateString()
                        : 'Never'}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Roles Tab */}
      {activeTab === 'roles' && (
        <div className="space-y-4">
          {/* Add Role */}
          <div className="flex items-center gap-2">
            {showAddRole ? (
              <>
                <select
                  value={selectedRole}
                  onChange={(e) => setSelectedRole(e.target.value)}
                  className={`flex-1 px-3 py-2 rounded-md border text-sm ${
                    isDarkMode
                      ? 'bg-gray-700 border-gray-600 text-white'
                      : 'bg-white border-gray-300 text-gray-900'
                  }`}
                >
                  <option value="">Select a role...</option>
                  {availableRoles.map((role: Role) => (
                    <option key={role.slug} value={role.slug}>
                      {role.name}{role.description ? ` - ${role.description}` : ''}
                    </option>
                  ))}
                </select>
                <Button
                  onClick={handleAssignRole}
                  disabled={!selectedRole || assignRoleMutation.isPending}
                  className="bg-[#2A4DD0] hover:bg-blue-700 text-white"
                  size="sm"
                >
                  {assignRoleMutation.isPending ? 'Assigning...' : 'Assign'}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setShowAddRole(false)
                    setSelectedRole('')
                  }}
                  className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
                >
                  Cancel
                </Button>
              </>
            ) : (
              <Button
                onClick={() => setShowAddRole(true)}
                variant="outline"
                size="sm"
                className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
              >
                <Plus className="w-4 h-4 mr-1" />
                Assign Role
              </Button>
            )}
          </div>

          {/* Info banner */}
          <div className={`flex items-start gap-2 p-3 rounded-lg text-xs ${
            isDarkMode ? 'bg-blue-900/20 text-blue-400' : 'bg-blue-50 text-blue-700'
          }`}>
            <AlertCircle className="w-3 h-3 mt-0.5 flex-shrink-0" />
            <span>All members of this group will inherit these role permissions</span>
          </div>

          {/* Roles List */}
          {!group.roles || group.roles.length === 0 ? (
            <div className={`text-center py-8 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
              <Shield className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <div>No roles assigned to this group</div>
              <div className="text-sm mt-1">Assign roles to grant permissions to all group members</div>
            </div>
          ) : (
            <div className={`rounded-lg border overflow-hidden ${
              isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
            }`}>
              <div className={`grid grid-cols-[1fr_1fr_auto] gap-4 px-4 py-2.5 text-xs font-medium uppercase tracking-wider border-b ${
                isDarkMode ? 'bg-gray-800 border-gray-700 text-gray-400' : 'bg-gray-50 border-gray-200 text-gray-500'
              }`}>
                <div>Role</div>
                <div>Description</div>
                <div></div>
              </div>
              <div className={`divide-y ${isDarkMode ? 'divide-gray-700' : 'divide-gray-100'}`}>
                {group.roles.map((role: Role) => (
                  <div key={role.slug} className="grid grid-cols-[1fr_1fr_auto] gap-4 items-center px-4 py-3">
                    <div className="flex items-center gap-3 min-w-0">
                      <div className={`p-1.5 rounded ${isDarkMode ? 'bg-gray-700' : 'bg-gray-100'}`}>
                        <Shield className={`w-4 h-4 ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`} />
                      </div>
                      <div className="min-w-0">
                        <div className={`text-sm font-medium truncate ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}>
                          {role.name}
                        </div>
                        <div className={`text-xs font-mono truncate ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                          {role.slug}
                        </div>
                      </div>
                    </div>
                    <div className={`text-sm truncate ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                      {role.description || 'No description'}
                    </div>
                    <button
                      onClick={() => handleUnassignRole(role.slug)}
                      disabled={unassignRoleMutation.isPending}
                      className={`p-1 rounded ${
                        isDarkMode
                          ? 'text-gray-500 hover:text-red-400 hover:bg-gray-700'
                          : 'text-gray-400 hover:text-red-600 hover:bg-gray-100'
                      }`}
                      title="Remove role"
                    >
                      <X className="w-4 h-4" />
                    </button>
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
