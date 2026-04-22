import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Shield, Lock } from 'lucide-react'
import { formatRelativeDate } from '@/lib/formatDate'
import { extractApiErrorDetail } from '@/lib/apiError'
import { Badge } from '@/components/ui/badge'
import { AdminTable } from '@/components/ui/admin-table'
import type { CanDeleteResult } from '@/components/ui/admin-table'
import { AdminSection } from './AdminSection'
import { RoleForm } from './roles/RoleForm'
import { RoleDetail } from './roles/RoleDetail'
import { useAdminNav } from '@/hooks/useAdminNav'
import { useAdminCrud } from '@/hooks/useAdminCrud'
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

function isSystemRole(
  role: Role,
): role is RoleDetailType & { is_system: true } {
  return 'is_system' in role && (role as RoleDetailType).is_system === true
}

// Sync permissions: grant new ones, revoke removed ones. The API has no
// atomic replace endpoint, so we run grants/revokes concurrently and report
// any partial failures so the UI reflects the true post-mutation state.
async function syncPermissions(slug: string, desired: string[]) {
  const current = await getRole(slug)
  const currentPerms = new Set(current.permissions?.map((p) => p.name) ?? [])
  const desiredPerms = new Set(desired)

  // Iterate the deduplicated set for grants so a duplicate entry in
  // `desired` doesn't queue two grant calls for the same permission (the
  // second would reject as "already granted" and trigger partial-failure).
  const toGrant = [...desiredPerms].filter((p) => !currentPerms.has(p))
  const toRevoke = [...currentPerms].filter((p) => !desiredPerms.has(p))

  const operations: Array<{ kind: 'grant' | 'revoke'; permission: string }> = [
    ...toGrant.map((p) => ({ kind: 'grant' as const, permission: p })),
    ...toRevoke.map((p) => ({ kind: 'revoke' as const, permission: p })),
  ]

  const results = await Promise.allSettled(
    operations.map((op) =>
      op.kind === 'grant'
        ? grantPermission(slug, op.permission)
        : revokePermission(slug, op.permission),
    ),
  )

  const failures = results
    .map((r, i) => ({ result: r, op: operations[i] }))
    .filter(({ result }) => result.status === 'rejected')

  if (failures.length > 0) {
    const detail = failures
      .map(({ result, op }) => {
        const reason =
          result.status === 'rejected'
            ? extractApiErrorDetail(result.reason, 'unknown')
            : 'unknown'
        return `${op.kind} ${op.permission}: ${reason}`
      })
      .join('; ')
    throw new Error(
      `Permission sync partially failed (${failures.length}/${operations.length}): ${detail}`,
    )
  }
}

export function RoleManagement() {
  const {
    viewMode,
    slug: selectedRoleSlug,
    goToList,
    goToCreate,
    goToEdit,
    goToDetail,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')
  const queryClient = useQueryClient()

  // When the role write succeeded but a subset of permission grants/revokes
  // failed, the server state is genuinely different from both the pre-mutation
  // and the requested post-mutation state. Invalidate the role caches so the
  // client refetches the true state and surface the sync failure as a
  // non-blocking toast — the role *did* commit, so we don't strand the user
  // on the create form (for a role that now exists) or on the old slug after
  // an edit-time rename.
  const invalidateRoleCaches = (slug: string) => {
    queryClient.invalidateQueries({ queryKey: ['roles'] })
    queryClient.invalidateQueries({ queryKey: ['role', slug] })
  }

  const reportPermissionSyncFailure = (err: unknown) => {
    toast.error(
      `Role saved, but some permission changes failed: ${extractApiErrorDetail(err)}`,
    )
  }

  const {
    items: roles,
    isLoading,
    error,
    createMutation,
    updateMutation,
    deleteMutation,
  } = useAdminCrud<
    Role,
    { role: RoleCreate; permissions: string[] },
    { slug: string; role: RoleCreate; permissions: string[] },
    string
  >({
    queryKey: ['roles'],
    listFn: getRoles,
    createFn: async ({ role, permissions }) => {
      const created = await createRole(role)
      if (permissions.length > 0) {
        try {
          await syncPermissions(created.slug, permissions)
        } catch (err) {
          // The role itself committed — don't strand the user on a "new role"
          // form for a role that already exists. Refetch and toast instead.
          invalidateRoleCaches(created.slug)
          reportPermissionSyncFailure(err)
        }
      }
    },
    updateFn: async ({ slug, role, permissions }) => {
      const updated = await updateRole(slug, role)
      try {
        await syncPermissions(updated.slug, permissions)
      } catch (err) {
        // The role write committed (the slug may even have changed). Let the
        // success path navigate away and surface the partial sync failure as
        // a non-blocking toast.
        invalidateRoleCaches(updated.slug)
        reportPermissionSyncFailure(err)
      }
    },
    deleteFn: deleteRole,
    onMutationSuccess: goToList,
    extraInvalidateKeys: [['role']],
    deleteErrorLabel: 'role',
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
    if (isSystemRole(role))
      return { allowed: false, reason: 'System roles cannot be deleted' }
    return { allowed: true }
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

  if (viewMode === 'create' || viewMode === 'edit') {
    const isCreate = viewMode === 'create'
    return (
      <RoleForm
        roleSlug={selectedRoleSlug}
        onSave={handleSave}
        onCancel={handleCancel}
        isLoading={
          isCreate ? createMutation.isPending : updateMutation.isPending
        }
        error={isCreate ? createMutation.error : updateMutation.error}
      />
    )
  }

  if (viewMode === 'detail' && selectedRoleSlug) {
    return (
      <RoleDetail
        slug={selectedRoleSlug}
        onEdit={() => goToEdit(selectedRoleSlug)}
        onBack={handleCancel}
      />
    )
  }

  return (
    <AdminSection
      searchPlaceholder="Search roles..."
      search={searchQuery}
      onSearchChange={setSearchQuery}
      createLabel="New Role"
      onCreate={goToCreate}
      isLoading={isLoading}
      loadingLabel="Loading roles..."
      error={error}
      errorTitle="Failed to load roles"
    >
      <AdminTable
        columns={[
          {
            key: 'name',
            header: 'Role',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (role) => (
              <div className="flex items-center gap-2">
                <Shield className="h-4 w-4 flex-shrink-0 text-info" />
                <span className="text-sm font-medium text-primary">
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
              <span className="font-mono text-sm text-secondary">
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
              <span className="text-sm text-secondary">
                {role.description || '-'}
              </span>
            ),
          },
          {
            key: 'type',
            header: 'Type',
            headerAlign: 'center',
            cellAlign: 'center',
            render: (role) =>
              isSystemRole(role) ? (
                <Badge variant="warning" className="gap-1">
                  <Lock className="h-3 w-3" />
                  System
                </Badge>
              ) : (
                <Badge variant="info">Custom</Badge>
              ),
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
        onRowClick={(role) =>
          isSystemRole(role) ? goToDetail(role.slug) : goToEdit(role.slug)
        }
        onDelete={handleDelete}
        canDelete={canDeleteRole}
        isDeleting={deleteMutation.isPending}
        emptyMessage={
          searchQuery ? 'No roles match your search' : 'No roles created yet'
        }
      />
    </AdminSection>
  )
}
