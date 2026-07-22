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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Sk } from '@/components/ui/skeleton'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import { useAdminNav } from '@/hooks/useAdminNav'
import { extractApiErrorDetail } from '@/lib/apiError'
import { formatDateTime } from '@/lib/formatDate'
import { buildDiffPatch, buildReplacePatch } from '@/lib/json-patch'
import type { AdminUser, AdminUserCreate, PatchOperation } from '@/types'

import { Badge } from '../ui/badge'
import { UserIdentity } from '../ui/user-identity'
import { AdminSection } from './AdminSection'
import { UserDetail } from './users/UserDetail'
import { UserForm } from './users/UserForm'

type StatusFilter = 'active' | 'all' | 'inactive'
type UserFilter = 'admins' | 'all' | 'users'

export function UserManagement() {
  const queryClient = useQueryClient()
  const {
    editPath,
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
      return <UserDetailSkeleton />
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
          <Select
            onValueChange={(v) => setUserFilter(v as UserFilter)}
            value={userFilter}
          >
            <SelectTrigger aria-label="Filter users by type" className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Types</SelectItem>
              <SelectItem value="users">Regular Users</SelectItem>
              <SelectItem value="admins">Administrators</SelectItem>
            </SelectContent>
          </Select>
          <Select
            onValueChange={(v) => setStatusFilter(v as StatusFilter)}
            value={statusFilter}
          >
            <SelectTrigger aria-label="Filter users by status" className="w-35">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Status</SelectItem>
              <SelectItem value="active">Active</SelectItem>
              <SelectItem value="inactive">Inactive</SelectItem>
            </SelectContent>
          </Select>
        </>
      }
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
              <UserIdentity
                displayName={user.display_name}
                email={user.email}
                linkToProfile={false}
                size="small"
              />
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
            interactive: true,
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
                {formatDateTime(user.last_login, { fallback: 'Never' })}
              </span>
            ),
          },
        ]}
        emptyMessage={
          searchQuery || userFilter !== 'all' || statusFilter !== 'all'
            ? 'No users match your filters'
            : 'No users created yet'
        }
        getRowHref={(user) => editPath(user.email)}
        getRowKey={(user) => user.email}
        loading={isLoading}
        rows={filteredUsers}
      />
    </AdminSection>
  )
}

function UserDetailSkeleton() {
  return (
    <div className="space-y-6">
      <Sk h={36} r={6} w={88} />
      <div className="border-tertiary rounded-lg border">
        <div className="flex items-center gap-3 border-b px-6 py-5">
          <Sk circle h={48} w={48} />
          <div className="flex flex-col gap-2">
            <Sk h={16} w={180} />
            <Sk line w={220} />
          </div>
        </div>
        <div className="border-tertiary border-b px-6 py-5">
          <Sk h={28} r={4} w={120} />
        </div>
        <div className="grid grid-cols-2 gap-6 p-6">
          {[0, 1, 2, 3].map((i) => (
            <div className="flex flex-col gap-2" key={i}>
              <Sk line w={100} />
              <Sk line w="60%" />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
