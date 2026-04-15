import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '@/api/client'
import { Plus, Search, Edit2, Shield, AlertCircle, Lock } from 'lucide-react'
import { formatRelativeDate } from '@/lib/formatDate'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { AdminTable } from '@/components/ui/admin-table'
import type { CanDeleteResult } from '@/components/ui/admin-table'
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

type Role = Awaited<ReturnType<typeof getRoles>>[number]

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
    onError: (error: ApiError<{ detail?: string }>) => {
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
    onError: (error: ApiError<{ detail?: string }>) => {
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
    onError: (error: ApiError<{ detail?: string }>) => {
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

  const handleDelete = (role: Role) => {
    deleteMutation.mutate(role.slug)
  }

  const canDeleteRole = (role: Role): CanDeleteResult => {
    const isSystem = 'is_system' in role && (role as RoleDetailType).is_system
    if (isSystem)
      return { allowed: false, reason: 'System roles cannot be deleted' }
    return { allowed: true }
  }

  const roleActions = (role: Role) => {
    const isSystem = 'is_system' in role && (role as RoleDetailType).is_system
    return (
      <TooltipProvider delayDuration={200}>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="inline-flex">
              <button
                type="button"
                aria-label={
                  isSystem
                    ? `System role ${role.name} cannot be edited`
                    : `Edit role ${role.name}`
                }
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
              >
                <Edit2 className="h-4 w-4" />
              </button>
            </span>
          </TooltipTrigger>
          <TooltipContent>
            <p>{isSystem ? 'System roles cannot be edited' : 'Edit'}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    )
  }

  const handleCreateClick = () => {
    goToCreate()
  }

  const handleEditClick = (slug: string) => {
    goToEdit(slug)
  }

  const handleViewClick = (slug: string) => {
    goToEdit(slug)
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
          className="bg-amber-border text-white hover:bg-amber-border-strong"
        >
          <Plus className="mr-2 h-4 w-4" />
          New Role
        </Button>
      </div>

      <AdminTable
        columns={[
          {
            key: 'name',
            header: 'Role',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (role) => (
              <div className="flex items-center gap-2">
                <Shield
                  className={`h-4 w-4 flex-shrink-0 ${isDarkMode ? 'text-blue-400' : 'text-blue-600'}`}
                />
                <span
                  className={`text-sm font-medium ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
                >
                  {role.name}
                </span>
              </div>
            ),
          },
          {
            key: 'slug',
            header: 'Slug',
            headerAlign: 'center',
            cellAlign: 'center',
            render: (role) => (
              <span
                className={`font-mono text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                {role.slug}
              </span>
            ),
          },
          {
            key: 'description',
            header: 'Description',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (role) => (
              <span
                className={`text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                {role.description || '-'}
              </span>
            ),
          },
          {
            key: 'type',
            header: 'Type',
            headerAlign: 'center',
            cellAlign: 'center',
            render: (role) => {
              const isSystem =
                'is_system' in role && (role as RoleDetailType).is_system
              return isSystem ? (
                <span
                  className={`inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium ${isDarkMode ? 'bg-amber-900/30 text-amber-400' : 'bg-amber-100 text-amber-700'}`}
                >
                  <Lock className="h-3 w-3" />
                  System
                </span>
              ) : (
                <span
                  className={`rounded px-2 py-1 text-xs font-medium ${isDarkMode ? 'bg-blue-900/30 text-blue-400' : 'bg-blue-100 text-blue-700'}`}
                >
                  Custom
                </span>
              )
            },
          },
          {
            key: 'updated',
            header: 'Last Updated',
            headerAlign: 'center',
            cellAlign: 'center',
            render: (role) => formatRelativeDate(role.updated_at),
          },
        ]}
        rows={filteredRoles}
        getRowKey={(role) => role.slug}
        getDeleteLabel={(role) => role.name}
        onRowClick={(role) => handleViewClick(role.slug)}
        isRowClickable={(role) =>
          !('is_system' in role && (role as RoleDetailType).is_system)
        }
        onDelete={handleDelete}
        canDelete={canDeleteRole}
        isDeleting={deleteMutation.isPending}
        actions={roleActions}
        emptyMessage={
          searchQuery ? 'No roles match your search' : 'No roles created yet'
        }
      />
    </div>
  )
}
