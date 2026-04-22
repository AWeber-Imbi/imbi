import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { extractApiErrorDetail } from '@/lib/apiError'
import { Power, Crown } from 'lucide-react'
import { Badge } from '../ui/badge'
import { Gravatar } from '../ui/gravatar'
import { AdminTable } from '@/components/ui/admin-table'
import { ErrorBanner } from '@/components/ui/error-banner'
import { LoadingState } from '@/components/ui/loading-state'
import { AdminSection } from './AdminSection'
import { UserForm } from './users/UserForm'
import { UserDetail } from './users/UserDetail'
import { useAdminNav } from '@/hooks/useAdminNav'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import {
  listAdminUsers,
  getAdminUser,
  deleteAdminUser,
  updateAdminUser,
  createAdminUser,
} from '@/api/endpoints'
import type { AdminUser, AdminUserCreate, AdminUserUpdate } from '@/types'

type UserFilter = 'all' | 'users' | 'admins'
type StatusFilter = 'all' | 'active' | 'inactive'

export function UserManagement() {
  const queryClient = useQueryClient()
  const {
    viewMode,
    slug: selectedUserEmail,
    goToList,
    goToCreate,
    goToEdit,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')
  const [userFilter, setUserFilter] = useState<UserFilter>('all')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')

  const {
    items: users,
    isLoading,
    error,
    createMutation,
    updateMutation,
    deleteMutation,
  } = useAdminCrud<
    AdminUser,
    AdminUserCreate,
    { email: string; user: AdminUserUpdate },
    string
  >({
    queryKey: ['adminUsers'],
    listFn: listAdminUsers,
    createFn: createAdminUser,
    updateFn: ({ email, user }) => updateAdminUser(email, user),
    deleteFn: deleteAdminUser,
    onMutationSuccess: goToList,
    deleteErrorLabel: 'user',
  })

  // Toggle-active is a bespoke mutation: it fires in the list view, mustn't
  // navigate, and toasts on failure but not via useAdminCrud's update flow.
  const toggleActiveMutation = useMutation({
    mutationFn: ({ email, user }: { email: string; user: AdminUserUpdate }) =>
      updateAdminUser(email, user),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
    },
    onError: (error: unknown) => {
      toast.error(`Failed to update user: ${extractApiErrorDetail(error)}`)
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
      user: {
        email: user.email,
        display_name: user.display_name,
        is_active: !user.is_active,
        is_admin: user.is_admin,
        is_service_account: user.is_service_account,
      },
    })
  }

  const handleDelete = (user: AdminUser) => {
    deleteMutation.mutate(user.email)
  }

  const formatDate = (dateString?: string | null) => {
    if (!dateString) return 'Never'
    return new Date(dateString).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const getGroupNames = (user: AdminUser): string => {
    if (!user.groups || user.groups.length === 0) return '-'
    return user.groups.map((g) => g.name).join(', ')
  }

  // Fetch full user detail (with orgs) when viewing/editing a specific user
  const {
    data: selectedUser = null,
    isLoading: selectedUserLoading,
    error: selectedUserError,
  } = useQuery({
    queryKey: ['adminUser', selectedUserEmail],
    queryFn: () => getAdminUser(selectedUserEmail!),
    enabled:
      !!selectedUserEmail && (viewMode === 'detail' || viewMode === 'edit'),
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
      // Strip org/role fields for update — they're only for creation
      const { organization_slug: _, role_slug: __, ...updateData } = userData
      updateMutation.mutate({ email: selectedUser.email, user: updateData })
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
        <ErrorBanner title="Failed to load user" error={selectedUserError} />
      )
    }
    if (!selectedUser) {
      return (
        <div className="rounded-lg border border-tertiary p-4 text-secondary">
          User not found. They may have been removed.
        </div>
      )
    }
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <UserForm
        user={selectedUser}
        onSave={handleSave}
        onCancel={handleCancel}
        isLoading={createMutation.isPending || updateMutation.isPending}
        error={createMutation.error || updateMutation.error}
      />
    )
  }

  if (viewMode === 'detail' && selectedUser) {
    return (
      <UserDetail
        user={selectedUser}
        onEdit={() => handleEditClick(selectedUser)}
        onBack={handleCancel}
      />
    )
  }

  return (
    <AdminSection
      searchPlaceholder="Search users..."
      search={searchQuery}
      onSearchChange={setSearchQuery}
      createLabel="New User"
      onCreate={goToCreate}
      isLoading={isLoading}
      loadingLabel="Loading users..."
      error={error}
      errorTitle="Failed to load users"
      headerExtras={
        <>
          <select
            aria-label="Filter users by type"
            value={userFilter}
            onChange={(e) => setUserFilter(e.target.value as UserFilter)}
            className={`rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground`}
          >
            <option value="all">All Types</option>
            <option value="users">Regular Users</option>
            <option value="admins">Administrators</option>
          </select>
          <select
            aria-label="Filter users by status"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
            className={`rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground`}
          >
            <option value="all">All Status</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </>
      }
    >
      <AdminTable
        columns={[
          {
            key: 'user',
            header: 'User',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (user) => (
              <div className="flex items-center gap-3">
                <Gravatar
                  email={user.email}
                  size={32}
                  alt={user.display_name}
                  className="size-8 rounded-full"
                />
                <div>
                  <div className="text-sm font-medium text-primary">
                    {user.display_name}
                  </div>
                  <div className="text-xs text-secondary">
                    {getGroupNames(user)}
                  </div>
                </div>
              </div>
            ),
          },
          {
            key: 'email',
            header: 'Email',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (user) => (
              <span className="text-sm text-secondary">{user.email}</span>
            ),
          },
          {
            key: 'type',
            header: 'Type',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (user) =>
              user.is_admin ? (
                <Badge variant="danger" className="gap-1">
                  <Crown className="h-3 w-3" />
                  Admin
                </Badge>
              ) : (
                <Badge variant="info">User</Badge>
              ),
          },
          {
            key: 'status',
            header: 'Status',
            headerAlign: 'center',
            cellAlign: 'center',
            render: (user) => (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  handleToggleActive(user)
                }}
                disabled={toggleActiveMutation.isPending}
                className={`inline-flex items-center gap-1.5 rounded px-2 py-1 text-xs font-medium ${
                  user.is_active
                    ? 'bg-success text-success'
                    : 'bg-secondary text-secondary'
                }`}
              >
                <Power className="h-3 w-3" />
                {user.is_active ? 'Active' : 'Inactive'}
              </button>
            ),
          },
          {
            key: 'last_login',
            header: 'Last Login',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (user) => (
              <span className="text-xs text-secondary">
                {formatDate(user.last_login)}
              </span>
            ),
          },
        ]}
        rows={filteredUsers}
        getRowKey={(user) => user.email}
        getDeleteLabel={(user) => user.display_name}
        onRowClick={(user) => handleViewClick(user)}
        onDelete={handleDelete}
        isDeleting={deleteMutation.isPending}
        emptyMessage={
          searchQuery || userFilter !== 'all' || statusFilter !== 'all'
            ? 'No users match your filters'
            : 'No users created yet'
        }
      />
    </AdminSection>
  )
}
