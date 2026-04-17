import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '@/api/client'
import { Plus, Search, Power, Crown, AlertCircle } from 'lucide-react'
import { Button } from '../ui/button'
import { Badge } from '../ui/badge'
import { Input } from '../ui/input'
import { Gravatar } from '../ui/gravatar'
import { AdminTable } from '@/components/ui/admin-table'
import { UserForm } from './users/UserForm'
import { UserDetail } from './users/UserDetail'
import { useAdminNav } from '@/hooks/useAdminNav'
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

  // Fetch users from API
  const {
    data: users = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ['adminUsers'],
    queryFn: () => listAdminUsers(),
  })

  // Delete user mutation
  const deleteMutation = useMutation({
    mutationFn: deleteAdminUser,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      alert(
        `Failed to delete user: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  // Toggle active mutation
  const toggleActiveMutation = useMutation({
    mutationFn: ({ email, user }: { email: string; user: AdminUserUpdate }) =>
      updateAdminUser(email, user),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      alert(
        `Failed to update user: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  // Create user mutation
  const createMutation = useMutation({
    mutationFn: createAdminUser,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
      goToList()
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      // Error will be displayed in the UserForm component
      console.error('Failed to create user:', error)
    },
  })

  // Update user mutation
  const updateMutation = useMutation({
    mutationFn: ({ email, user }: { email: string; user: AdminUserUpdate }) =>
      updateAdminUser(email, user),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
      goToList()
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      // Error will be displayed in the UserForm component
      console.error('Failed to update user:', error)
    },
  })

  // Filter users locally - exclude service accounts (managed separately)
  const filteredUsers = users.filter((user) => {
    // Exclude service accounts - they have their own management section
    if (user.is_service_account) return false

    // Search filter
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      const matches =
        user.email.toLowerCase().includes(query) ||
        user.display_name.toLowerCase().includes(query)
      if (!matches) return false
    }

    // Type filter
    if (userFilter === 'admins' && !user.is_admin) return false
    if (userFilter === 'users' && user.is_admin) return false

    // Status filter
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
  const { data: selectedUser = null } = useQuery({
    queryKey: ['adminUser', selectedUserEmail],
    queryFn: () => getAdminUser(selectedUserEmail!),
    enabled:
      !!selectedUserEmail && (viewMode === 'detail' || viewMode === 'edit'),
  })

  // View handlers
  const handleCreateClick = () => {
    goToCreate()
  }

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

  // Loading state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className={'text-sm text-secondary'}>Loading users...</div>
      </div>
    )
  }

  // Error state
  if (error) {
    return (
      <div
        className={`flex items-center gap-3 rounded-lg border p-4 ${'border-danger bg-danger text-danger'}`}
      >
        <AlertCircle className="h-5 w-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load users</div>
          <div className="mt-1 text-sm">
            {error instanceof Error ? error.message : 'An error occurred'}
          </div>
        </div>
      </div>
    )
  }

  // Guard for invalid user email in URL
  if (
    (viewMode === 'edit' || viewMode === 'detail') &&
    !!selectedUserEmail &&
    !selectedUser
  ) {
    return (
      <div className={'rounded-lg border border-tertiary p-4 text-secondary'}>
        User not found. They may have been removed.
      </div>
    )
  }

  // View mode: Create or Edit
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

  // View mode: Detail
  if (viewMode === 'detail' && selectedUser) {
    return (
      <UserDetail
        user={selectedUser}
        onEdit={() => handleEditClick(selectedUser)}
        onBack={handleCancel}
      />
    )
  }

  // View mode: List (default)
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex flex-1 items-center gap-3">
          <div className="relative max-w-md flex-1">
            <Search
              className={`absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${'text-tertiary'}`}
            />
            <Input
              placeholder="Search users..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={'pl-10'}
            />
          </div>
          <select
            value={userFilter}
            onChange={(e) => setUserFilter(e.target.value as UserFilter)}
            className={`rounded-lg border px-3 py-2 text-sm ${'border-input bg-background text-foreground'}`}
          >
            <option value="all">All Types</option>
            <option value="users">Regular Users</option>
            <option value="admins">Administrators</option>
          </select>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
            className={`rounded-lg border px-3 py-2 text-sm ${'border-input bg-background text-foreground'}`}
          >
            <option value="all">All Status</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </div>
        <Button
          onClick={handleCreateClick}
          className="bg-action text-action-foreground hover:bg-action-hover"
        >
          <Plus className="mr-2 h-4 w-4" />
          New User
        </Button>
      </div>

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
                  <div className={'text-sm font-medium text-primary'}>
                    {user.display_name}
                  </div>
                  <div className={'text-xs text-secondary'}>
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
              <span className={'text-sm text-secondary'}>{user.email}</span>
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
              <span className={'text-xs text-secondary'}>
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
    </div>
  )
}
