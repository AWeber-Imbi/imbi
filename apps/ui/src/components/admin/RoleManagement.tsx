import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { AxiosError } from 'axios'
import {
  Plus,
  Search,
  Edit2,
  Trash2,
  Shield,
  AlertCircle,
  Lock,
} from 'lucide-react'
import { formatRelativeDate } from '@/lib/formatDate'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { RoleForm } from './roles/RoleForm'
import { RoleDetail } from './roles/RoleDetail'
import { useAdminNav } from '@/hooks/useAdminNav'
import {
  getRoles,
  getRole,
  deleteRole,
  createRole,
  updateRole,
  grantPermission,
  revokePermission,
} from '@/api/endpoints'
import type { RoleDetail as RoleDetailType, RoleCreate } from '@/types'

interface RoleManagementProps {
  isDarkMode: boolean
}

export function RoleManagement({ isDarkMode }: RoleManagementProps) {
  const queryClient = useQueryClient()
  const {
    viewMode,
    slug: selectedRoleSlug,
    goToList,
    goToCreate,
    goToDetail,
    goToEdit,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')

  // Fetch roles from API
  const {
    data: roles = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ['roles'],
    queryFn: getRoles,
  })

  // Delete role mutation
  const deleteMutation = useMutation({
    mutationFn: deleteRole,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['roles'] })
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      alert(
        `Failed to delete role: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  // Sync permissions: grant new ones, revoke removed ones
  const syncPermissions = async (slug: string, desired: string[]) => {
    const current = await getRole(slug)
    const currentPerms = new Set(current.permissions?.map((p) => p.name) || [])
    const desiredPerms = new Set(desired)

    const toGrant = desired.filter((p) => !currentPerms.has(p))
    const toRevoke = [...currentPerms].filter((p) => !desiredPerms.has(p))

    await Promise.all([
      ...toGrant.map((p) => grantPermission(slug, p)),
      ...toRevoke.map((p) => revokePermission(slug, p)),
    ])
  }

  // Create role mutation with permission sync
  const createMutation = useMutation({
    mutationFn: async ({
      role,
      permissions,
    }: {
      role: RoleCreate
      permissions: string[]
    }) => {
      const created = await createRole(role)
      if (permissions.length > 0) {
        await syncPermissions(created.slug, permissions)
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['roles'] })
      goToList()
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      console.error('Failed to create role:', error)
    },
  })

  // Update role mutation with permission sync
  const updateMutation = useMutation({
    mutationFn: async ({
      slug,
      role,
      permissions,
    }: {
      slug: string
      role: RoleCreate
      permissions: string[]
    }) => {
      const updated = await updateRole(slug, role)
      await syncPermissions(updated.slug, permissions)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['roles'] })
      queryClient.invalidateQueries({ queryKey: ['role'] })
      goToList()
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      console.error('Failed to update role:', error)
    },
  })

  // Filter roles locally
  const filteredRoles = roles.filter((role) => {
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      return (
        role.name.toLowerCase().includes(query) ||
        role.slug.toLowerCase().includes(query) ||
        (role.description?.toLowerCase().includes(query) ?? false)
      )
    }
    return true
  })

  const handleDelete = (slug: string) => {
    if (
      confirm(
        'Are you sure you want to delete this role? This action cannot be undone.',
      )
    ) {
      deleteMutation.mutate(slug)
    }
  }

  const handleCreateClick = () => {
    goToCreate()
  }

  const handleEditClick = (slug: string) => {
    goToEdit(slug)
  }

  const handleViewClick = (slug: string) => {
    goToDetail(slug)
  }

  const handleSave = (roleData: RoleCreate, permissions: string[]) => {
    if (viewMode === 'create') {
      createMutation.mutate({ role: roleData, permissions })
    } else if (selectedRoleSlug) {
      updateMutation.mutate({
        slug: selectedRoleSlug,
        role: roleData,
        permissions,
      })
    }
  }

  const handleCancel = () => {
    goToList()
  }

  // Loading state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div
          className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
        >
          Loading roles...
        </div>
      </div>
    )
  }

  // Error state
  if (error) {
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
          <div className="font-medium">Failed to load roles</div>
          <div className="mt-1 text-sm">
            {error instanceof Error ? error.message : 'An error occurred'}
          </div>
        </div>
      </div>
    )
  }

  // View mode: Create or Edit
  if (viewMode === 'create' || viewMode === 'edit') {
    const isCreate = viewMode === 'create'
    return (
      <RoleForm
        roleSlug={selectedRoleSlug}
        onSave={handleSave}
        onCancel={handleCancel}
        isDarkMode={isDarkMode}
        isLoading={
          isCreate ? createMutation.isPending : updateMutation.isPending
        }
        error={isCreate ? createMutation.error : updateMutation.error}
      />
    )
  }

  // View mode: Detail
  if (viewMode === 'detail' && selectedRoleSlug) {
    return (
      <RoleDetail
        slug={selectedRoleSlug}
        onEdit={() => handleEditClick(selectedRoleSlug)}
        onBack={handleCancel}
        isDarkMode={isDarkMode}
      />
    )
  }

  // View mode: List (default)
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex-1">
          <div className="relative max-w-md">
            <Search
              className={`absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${
                isDarkMode ? 'text-gray-400' : 'text-gray-500'
              }`}
            />
            <Input
              placeholder="Search roles..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={`pl-10 ${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''}`}
            />
          </div>
        </div>
        <Button
          onClick={handleCreateClick}
          className="bg-[#2A4DD0] text-white hover:bg-blue-700"
        >
          <Plus className="mr-2 h-4 w-4" />
          New Role
        </Button>
      </div>

      {/* Roles Table */}
      <div
        className={`overflow-hidden rounded-lg border ${
          isDarkMode
            ? 'border-gray-700 bg-gray-800'
            : 'border-gray-200 bg-white'
        }`}
      >
        <table className="w-full">
          <thead
            className={`${isDarkMode ? 'bg-gray-750 border-b border-gray-700' : 'border-b border-gray-200 bg-gray-50'}`}
          >
            <tr>
              <th
                className={`px-4 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Role
              </th>
              <th
                className={`px-4 py-3 text-center text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Slug
              </th>
              <th
                className={`px-4 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Description
              </th>
              <th
                className={`px-4 py-3 text-center text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Type
              </th>
              <th
                className={`whitespace-nowrap px-4 py-3 text-center text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Last Updated
              </th>
              <th
                className={`px-4 py-3 text-right text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Actions
              </th>
            </tr>
          </thead>
          <tbody
            className={
              isDarkMode
                ? 'divide-y divide-gray-700'
                : 'divide-y divide-gray-200'
            }
          >
            {filteredRoles.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center">
                  <div
                    className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
                  >
                    {searchQuery
                      ? 'No roles match your search'
                      : 'No roles created yet'}
                  </div>
                </td>
              </tr>
            ) : (
              filteredRoles.map((role) => {
                const isSystem =
                  'is_system' in role && (role as RoleDetailType).is_system
                return (
                  <tr
                    key={role.slug}
                    onClick={() => handleViewClick(role.slug)}
                    className={`cursor-pointer ${isDarkMode ? 'hover:bg-gray-750' : 'hover:bg-gray-50'}`}
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <Shield
                          className={`h-4 w-4 flex-shrink-0 ${
                            isDarkMode ? 'text-blue-400' : 'text-blue-600'
                          }`}
                        />
                        <span
                          className={`text-sm font-medium ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
                        >
                          {role.name}
                        </span>
                      </div>
                    </td>
                    <td
                      className={`whitespace-nowrap px-4 py-3 text-center font-mono text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                    >
                      {role.slug}
                    </td>
                    <td
                      className={`px-4 py-3 text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                    >
                      {role.description || '-'}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-center">
                      {isSystem ? (
                        <span
                          className={`inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium ${
                            isDarkMode
                              ? 'bg-amber-900/30 text-amber-400'
                              : 'bg-amber-100 text-amber-700'
                          }`}
                        >
                          <Lock className="h-3 w-3" />
                          System
                        </span>
                      ) : (
                        <span
                          className={`rounded px-2 py-1 text-xs font-medium ${
                            isDarkMode
                              ? 'bg-blue-900/30 text-blue-400'
                              : 'bg-blue-100 text-blue-700'
                          }`}
                        >
                          Custom
                        </span>
                      )}
                    </td>
                    <td
                      className={`whitespace-nowrap px-4 py-3 text-center text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}
                    >
                      {formatRelativeDate(role.updated_at)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            handleEditClick(role.slug)
                          }}
                          disabled={isSystem}
                          className={`rounded p-1.5 ${
                            isSystem
                              ? 'cursor-not-allowed opacity-40'
                              : isDarkMode
                                ? 'text-gray-400 hover:bg-gray-700 hover:text-gray-200'
                                : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                          }`}
                          title={
                            isSystem ? 'System roles cannot be edited' : 'Edit'
                          }
                        >
                          <Edit2 className="h-4 w-4" />
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            handleDelete(role.slug)
                          }}
                          disabled={deleteMutation.isPending || isSystem}
                          className={`rounded p-1.5 ${
                            isSystem
                              ? 'cursor-not-allowed opacity-40'
                              : isDarkMode
                                ? 'text-red-400 hover:bg-gray-700 hover:text-red-300'
                                : 'text-red-600 hover:bg-gray-100 hover:text-red-700'
                          }`}
                          title={
                            isSystem
                              ? 'System roles cannot be deleted'
                              : 'Delete'
                          }
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
