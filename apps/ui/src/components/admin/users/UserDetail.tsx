import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { AxiosError } from 'axios'
import {
  ArrowLeft,
  Edit2,
  Power,
  Clock,
  User,
  Mail,
  Calendar,
  Shield,
  Plus,
  Trash2,
  Building2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Gravatar } from '@/components/ui/gravatar'
import {
  getRoles,
  addUserToOrg,
  updateUserOrgRole,
  removeUserFromOrg,
} from '@/api/endpoints'
import { useOrganization } from '@/contexts/OrganizationContext'
import type { AdminUser, OrgMembership } from '@/types'

interface UserDetailProps {
  user: AdminUser
  onEdit: () => void
  onBack: () => void
  isDarkMode: boolean
}

export function UserDetail({
  user,
  onEdit,
  onBack,
  isDarkMode,
}: UserDetailProps) {
  const queryClient = useQueryClient()
  const { organizations: allOrgs } = useOrganization()
  const [showAddOrg, setShowAddOrg] = useState(false)
  const [newOrgSlug, setNewOrgSlug] = useState('')
  const [newRoleSlug, setNewRoleSlug] = useState('')

  const { data: availableRoles = [] } = useQuery({
    queryKey: ['roles'],
    queryFn: getRoles,
  })

  const addOrgMutation = useMutation({
    mutationFn: (data: { organization_slug: string; role_slug: string }) =>
      addUserToOrg(user.email, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
      queryClient.invalidateQueries({ queryKey: ['adminUser', user.email] })
      setShowAddOrg(false)
      setNewOrgSlug('')
      setNewRoleSlug('')
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      alert(
        `Failed to add to organization: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  const updateRoleMutation = useMutation({
    mutationFn: ({
      orgSlug,
      roleSlug,
    }: {
      orgSlug: string
      roleSlug: string
    }) => updateUserOrgRole(user.email, orgSlug, { role_slug: roleSlug }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
      queryClient.invalidateQueries({ queryKey: ['adminUser', user.email] })
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      alert(
        `Failed to update role: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  const removeOrgMutation = useMutation({
    mutationFn: (orgSlug: string) => removeUserFromOrg(user.email, orgSlug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
      queryClient.invalidateQueries({ queryKey: ['adminUser', user.email] })
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      alert(
        `Failed to remove from organization: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  // Orgs the user is not already a member of
  const memberOrgSlugs = new Set(
    (user.organizations ?? []).map((o) => o.organization_slug),
  )
  const availableOrgs = allOrgs.filter((o) => !memberOrgSlugs.has(o.slug))

  const formatDate = (dateString?: string | null) => {
    if (!dateString) return 'Never'
    return new Date(dateString).toLocaleString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

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

      {/* User info card */}
      <div
        className={`rounded-lg border ${isDarkMode ? 'border-gray-700 bg-gray-800' : 'border-gray-200 bg-white'}`}
      >
        {/* Title row */}
        <div
          className={`flex items-start justify-between border-b px-6 py-5 ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
        >
          <div className="flex items-center gap-3">
            <Gravatar
              email={user.email}
              size={48}
              alt={user.display_name}
              className="h-12 w-12 rounded-full"
            />
            <div>
              <h2
                className={`text-2xl ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
              >
                {user.display_name}
              </h2>
              <p
                className={`mt-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                {user.email}
              </p>
            </div>
          </div>
          <Button
            onClick={onEdit}
            className="bg-[#2A4DD0] text-white hover:bg-blue-700"
          >
            <Edit2 className="mr-2 h-4 w-4" />
            Edit User
          </Button>
        </div>

        {/* Account Status */}
        <div
          className={`border-b px-6 py-5 ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
        >
          <div className="flex items-center gap-6">
            <div
              className={`flex items-center gap-2 rounded px-3 py-1.5 ${
                user.is_active
                  ? isDarkMode
                    ? 'bg-green-900/30 text-green-400'
                    : 'bg-green-100 text-green-700'
                  : isDarkMode
                    ? 'bg-gray-700 text-gray-400'
                    : 'bg-gray-100 text-gray-600'
              }`}
            >
              <Power className="h-4 w-4" />
              {user.is_active ? 'Active' : 'Inactive'}
            </div>
            {user.is_admin && (
              <div
                className={`flex items-center gap-2 rounded px-3 py-1.5 ${
                  isDarkMode
                    ? 'bg-red-900/30 text-red-400'
                    : 'bg-red-100 text-red-700'
                }`}
              >
                <Shield className="h-4 w-4" />
                Administrator
              </div>
            )}
            {user.is_service_account && (
              <div
                className={`flex items-center gap-2 rounded px-3 py-1.5 ${
                  isDarkMode
                    ? 'bg-purple-900/30 text-purple-400'
                    : 'bg-purple-100 text-purple-700'
                }`}
              >
                Service Account
              </div>
            )}
          </div>
        </div>

        {/* Basic Information */}
        <div className="p-6">
          <div className="grid grid-cols-2 gap-6">
            <div>
              <div
                className={`mb-1 flex items-center gap-2 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                <Mail className="h-4 w-4" />
                Email
              </div>
              <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
                {user.email}
              </div>
            </div>

            <div>
              <div
                className={`mb-1 flex items-center gap-2 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                <User className="h-4 w-4" />
                Display Name
              </div>
              <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
                {user.display_name}
              </div>
            </div>

            <div>
              <div
                className={`mb-1 flex items-center gap-2 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                <Calendar className="h-4 w-4" />
                Created
              </div>
              <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
                {formatDate(user.created_at)}
              </div>
            </div>

            <div>
              <div
                className={`mb-1 flex items-center gap-2 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                <Clock className="h-4 w-4" />
                Last Login
              </div>
              <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
                {formatDate(user.last_login)}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Organization Memberships */}
      <div
        className={`rounded-lg border p-6 ${
          isDarkMode
            ? 'border-gray-700 bg-gray-800'
            : 'border-gray-200 bg-white'
        }`}
      >
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Building2
              className={`h-5 w-5 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
            />
            <h3
              className={`font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
            >
              Organization Memberships
            </h3>
          </div>
          {availableOrgs.length > 0 && (
            <Button
              onClick={() => setShowAddOrg(!showAddOrg)}
              variant="outline"
              size="sm"
              className={
                isDarkMode
                  ? 'border-gray-600 text-gray-300 hover:bg-gray-700'
                  : ''
              }
            >
              <Plus className="mr-2 h-4 w-4" />
              Add to Organization
            </Button>
          )}
        </div>

        {/* Add to Organization Form */}
        {showAddOrg && (
          <div
            className={`mb-4 rounded-lg border p-4 ${
              isDarkMode
                ? 'border-gray-600 bg-gray-700'
                : 'border-gray-200 bg-gray-50'
            }`}
          >
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label
                  className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                >
                  Organization
                </label>
                <select
                  value={newOrgSlug}
                  onChange={(e) => setNewOrgSlug(e.target.value)}
                  className={`w-full rounded-md border px-3 py-2 text-sm ${
                    isDarkMode
                      ? 'border-gray-600 bg-gray-700 text-white'
                      : 'border-gray-300 bg-white text-gray-900'
                  }`}
                >
                  <option value="">Select...</option>
                  {availableOrgs.map((org) => (
                    <option key={org.slug} value={org.slug}>
                      {org.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label
                  className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                >
                  Role
                </label>
                <select
                  value={newRoleSlug}
                  onChange={(e) => setNewRoleSlug(e.target.value)}
                  className={`w-full rounded-md border px-3 py-2 text-sm ${
                    isDarkMode
                      ? 'border-gray-600 bg-gray-700 text-white'
                      : 'border-gray-300 bg-white text-gray-900'
                  }`}
                >
                  <option value="">Select...</option>
                  {availableRoles.map((role) => (
                    <option key={role.slug} value={role.slug}>
                      {role.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="mt-3 flex items-center gap-2">
              <Button
                onClick={() =>
                  addOrgMutation.mutate({
                    organization_slug: newOrgSlug,
                    role_slug: newRoleSlug,
                  })
                }
                disabled={
                  !newOrgSlug || !newRoleSlug || addOrgMutation.isPending
                }
                className="bg-[#2A4DD0] text-white hover:bg-blue-700"
                size="sm"
              >
                {addOrgMutation.isPending ? 'Adding...' : 'Add'}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setShowAddOrg(false)
                  setNewOrgSlug('')
                  setNewRoleSlug('')
                }}
                className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
              >
                Cancel
              </Button>
            </div>
          </div>
        )}

        {/* Memberships List */}
        {(user.organizations ?? []).length > 0 ? (
          <div className="space-y-2">
            {(user.organizations ?? []).map((membership: OrgMembership) => (
              <div
                key={membership.organization_slug}
                className={`flex items-center justify-between rounded-lg border p-3 ${
                  isDarkMode
                    ? 'border-gray-600 bg-gray-700'
                    : 'border-gray-200 bg-gray-50'
                }`}
              >
                <div className="flex-1">
                  <div
                    className={`text-sm font-medium ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
                  >
                    {membership.organization_name}
                  </div>
                  <div
                    className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-500'}`}
                  >
                    {membership.organization_slug}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <select
                    value={membership.role}
                    onChange={(e) =>
                      updateRoleMutation.mutate({
                        orgSlug: membership.organization_slug,
                        roleSlug: e.target.value,
                      })
                    }
                    disabled={updateRoleMutation.isPending}
                    className={`rounded border px-2 py-1 text-xs ${
                      isDarkMode
                        ? 'border-gray-600 bg-gray-700 text-white'
                        : 'border-gray-300 bg-white text-gray-900'
                    }`}
                  >
                    {availableRoles.map((role) => (
                      <option key={role.slug} value={role.slug}>
                        {role.name}
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={() => {
                      if (
                        confirm(
                          `Remove ${user.display_name} from ${membership.organization_name}?`,
                        )
                      ) {
                        removeOrgMutation.mutate(membership.organization_slug)
                      }
                    }}
                    disabled={removeOrgMutation.isPending}
                    className={`rounded p-1.5 ${
                      isDarkMode
                        ? 'text-red-400 hover:bg-gray-700 hover:text-red-300'
                        : 'text-red-600 hover:bg-gray-100 hover:text-red-700'
                    }`}
                    title="Remove from organization"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div
            className={`py-8 text-center ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
          >
            <Building2
              className={`mx-auto mb-2 h-8 w-8 ${isDarkMode ? 'text-gray-600' : 'text-gray-400'}`}
            />
            <div>Not a member of any organization</div>
            <div className="mt-1 text-sm">
              This user has no permissions until added to an organization
            </div>
          </div>
        )}
      </div>

      {/* Active Sessions */}
      <div
        className={`rounded-lg border p-6 ${
          isDarkMode
            ? 'border-gray-700 bg-gray-800'
            : 'border-gray-200 bg-white'
        }`}
      >
        <h3
          className={`mb-4 font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
        >
          Active Sessions
        </h3>
        <div
          className={`py-8 text-center ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
        >
          <div>0 active sessions</div>
          <div className="mt-1 text-sm">
            No JWT tokens currently active for this user
          </div>
        </div>
      </div>
    </div>
  )
}
