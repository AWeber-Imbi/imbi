import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Crown, Power } from 'lucide-react'
import { toast } from 'sonner'

import {
  createAdminUser,
  deleteAdminUser,
  getAdminUser,
  listAdminUsers,
  updateAdminUser,
} from '@/api/endpoints'
import { AdminTable } from '@/components/ui/admin-table'
import { ErrorBanner } from '@/components/ui/error-banner'
import { LoadingState } from '@/components/ui/loading-state'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import { useAdminNav } from '@/hooks/useAdminNav'
import { extractApiErrorDetail } from '@/lib/apiError'
import { buildDiffPatch, buildReplacePatch } from '@/lib/json-patch'
import type { AdminUser, AdminUserCreate, PatchOperation } from '@/types'

import { Badge } from '../ui/badge'
import { Gravatar } from '../ui/gravatar'
import { AdminSection } from './AdminSection'
import { UserDetail } from './users/UserDetail'
import { UserForm } from './users/UserForm'

type StatusFilter = 'active' | 'all' | 'inactive'
type UserFilter = 'admins' | 'all' | 'users'

export function UserManagement() {
  const queryClient = useQueryClient()
  const {
    goToCreate,
    goToEdit,
    goToList,
    slug: selectedUserEmail,
    viewMode,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')
  const [userFilter, setUserFilter] = useState<UserFilter>('all')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')

  const {
    createMutation,
    deleteMutation,
    error,
    isLoading,
    items: users,
    updateMutation,
  } = useAdminCrud<
    AdminUser,
    AdminUserCreate,
    { email: string; operations: PatchOperation[] },
    string
  >({
    createFn: createAdminUser,
    deleteErrorLabel: 'user',
    deleteFn: deleteAdminUser,
    listFn: (signal) => listAdminUsers(undefined, signal),
    onMutationSuccess: goToList,
    queryKey: ['adminUsers'],
    updateFn: ({ email, operations }) => updateAdminUser(email, operations),
  })

  // Toggle-active is a bespoke mutation: it fires in the list view, mustn't
  // navigate, and toasts on failure but not via useAdminCrud's update flow.
  const toggleActiveMutation = useMutation({
    mutationFn: ({
      email,
      operations,
    }: {
      email: string
      operations: PatchOperation[]
    }) => updateAdminUser(email, operations),
    onError: (error: unknown) => {
      toast.error(`Failed to update user: ${extractApiErrorDetail(error)}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
    },
  })

  // Filter users locally - exclude service accounts (managed separately)
  const filteredUsers = users.filter((user) => {
    if (user.is_service_account) return false

    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      const matches =
        user.email.toLowerCase().includes(query) ||
        user.display_name.toLowerCase().includes(query)
      if (!matches) return false
    }

    if (userFilter === 'admins' && !user.is_admin) return false
    if (userFilter === 'users' && user.is_admin) return false

    if (statusFilter === 'active' && !user.is_active) return false
    if (statusFilter === 'inactive' && user.is_active) return false

    return true
  })

  const handleToggleActive = (user: AdminUser) => {
    toggleActiveMutation.mutate({
      email: user.email,
      operations: buildReplacePatch({ is_active: !user.is_active }),
    })
  }

  const handleDelete = (user: AdminUser) => {
    deleteMutation.mutate(user.email)
  }

  const formatDate = (dateString?: null | string) => {
    if (!dateString) return 'Never'
    return new Date(dateString).toLocaleString('en-US', {
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      month: 'short',
      year: 'numeric',
    })
  }

  // Fetch full user detail (with orgs) when viewing/editing a specific user
  const {
    data: selectedUser = null,
    error: selectedUserError,
    isLoading: selectedUserLoading,
  } = useQuery({
    enabled:
      !!selectedUserEmail && (viewMode === 'detail' || viewMode === 'edit'),
    queryFn: ({ signal }) => getAdminUser(selectedUserEmail!, signal),
    queryKey: ['adminUser', selectedUserEmail],
  })

  const handleEditClick = (user: AdminUser) => {
    goToEdit(user.email)
  }

  const handleViewClick = (user: AdminUser) => {
    goToEdit(user.email)
  }

  const handleSave = (userData: AdminUserCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate(userData)
    } else if (selectedUser) {
      // Strip create-only single-org fields; memberships flow via `organizations`
      const { organization_slug: _, role_slug: __, ...updateData } = userData
      // Normalize selectedUser.organizations to {organization_slug, role}
      // so the diff doesn't see organization_name as a phantom change.
      const before = {
        ...selectedUser,
        organizations: (selectedUser.organizations ?? []).map((m) => ({
          organization_slug: m.organization_slug,
          role: m.role,
        })),
      }
      const operations = buildDiffPatch(
        before as unknown as Record<string, unknown>,
        updateData as unknown as Record<string, unknown>,
        { fields: Object.keys(updateData) },
      )
      if (operations.length === 0) {
        goToList()
        return
      }
      updateMutation.mutate({ email: selectedUser.email, operations })
    }
  }

  const handleCancel = () => {
    goToList()
  }

  // For deep-linked edit/detail: resolve the per-user fetch before rendering
  // so UserForm never gets user={null} and detail doesn't flash back to list.
  if ((viewMode === 'edit' || viewMode === 'detail') && !!selectedUserEmail) {
    if (selectedUserLoading) {
      return <LoadingState label="Loading user..." />
    }
    if (selectedUserError) {
      return (
        <ErrorBanner error={selectedUserError} title="Failed to load user" />
      )
    }
    if (!selectedUser) {
      return (
        <div className="border-tertiary text-secondary rounded-lg border p-4">
          User not found. They may have been removed.
        </div>
      )
    }
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <UserForm
        error={createMutation.error || updateMutation.error}
        isDeleting={deleteMutation.isPending}
        isLoading={createMutation.isPending || updateMutation.isPending}
        onCancel={handleCancel}
        onDelete={handleDelete}
        onSave={handleSave}
        user={selectedUser}
      />
    )
  }

  if (viewMode === 'detail' && selectedUser) {
    return (
      <UserDetail
        onBack={handleCancel}
        onEdit={() => handleEditClick(selectedUser)}
        user={selectedUser}
      />
    )
  }

  return (
    <AdminSection
      createLabel="New User"
      error={error}
      errorTitle="Failed to load users"
      headerExtras={
        <>
          <select
            aria-label="Filter users by type"
            className="border-input bg-background text-foreground rounded-lg border px-3 py-2 text-sm"
            onChange={(e) => setUserFilter(e.target.value as UserFilter)}
            value={userFilter}
          >
            <option value="all">All Types</option>
            <option value="users">Regular Users</option>
            <option value="admins">Administrators</option>
          </select>
          <select
            aria-label="Filter users by status"
            className="border-input bg-background text-foreground rounded-lg border px-3 py-2 text-sm"
            onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
            value={statusFilter}
          >
            <option value="all">All Status</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </>
      }
      isLoading={isLoading}
      loadingLabel="Loading users..."
      onCreate={goToCreate}
      onSearchChange={setSearchQuery}
      search={searchQuery}
      searchPlaceholder="Search users..."
    >
      <AdminTable
        columns={[
          {
            cellAlign: 'left',
            header: 'User',
            headerAlign: 'left',
            key: 'user',
            render: (user) => (
              <div className="flex items-center gap-3">
                <Gravatar
                  alt={user.display_name}
                  className="size-8 rounded-full"
                  email={user.email}
                  size={32}
                />
                <div className="text-primary text-sm font-medium">
                  {user.display_name}
                </div>
              </div>
            ),
          },
          {
            cellAlign: 'left',
            header: 'Email',
            headerAlign: 'left',
            key: 'email',
            render: (user) => (
              <span className="text-secondary text-sm">{user.email}</span>
            ),
          },
          {
            cellAlign: 'left',
            header: 'Type',
            headerAlign: 'left',
            key: 'type',
            render: (user) =>
              user.is_admin ? (
                <Badge className="gap-1" variant="danger">
                  <Crown className="size-3" />
                  Admin
                </Badge>
              ) : (
                <Badge variant="info">User</Badge>
              ),
          },
          {
            cellAlign: 'center',
            header: 'Status',
            headerAlign: 'center',
            key: 'status',
            render: (user) => (
              <button
                className={`inline-flex items-center gap-1.5 rounded px-2 py-1 text-xs font-medium ${
                  user.is_active
                    ? 'bg-success text-success'
                    : 'bg-secondary text-secondary'
                }`}
                disabled={toggleActiveMutation.isPending}
                onClick={(e) => {
                  e.stopPropagation()
                  handleToggleActive(user)
                }}
              >
                <Power className="size-3" />
                {user.is_active ? 'Active' : 'Inactive'}
              </button>
            ),
          },
          {
            cellAlign: 'left',
            header: 'Last Login',
            headerAlign: 'left',
            key: 'last_login',
            render: (user) => (
              <span className="text-secondary text-xs">
                {formatDate(user.last_login)}
              </span>
            ),
          },
        ]}
        emptyMessage={
          searchQuery || userFilter !== 'all' || statusFilter !== 'all'
            ? 'No users match your filters'
            : 'No users created yet'
        }
        getRowKey={(user) => user.email}
        onRowClick={(user) => handleViewClick(user)}
        rows={filteredUsers}
      />
    </AdminSection>
  )
}
