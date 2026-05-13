import { useState } from 'react'

import { useQueryClient } from '@tanstack/react-query'
import { Lock, Shield } from 'lucide-react'
import { toast } from 'sonner'

import {
  createRole,
  deleteRole,
  getRole,
  getRoles,
  grantPermission,
  revokePermission,
  updateRole,
} from '@/api/endpoints'
import { AdminTable } from '@/components/ui/admin-table'
import type { CanDeleteResult } from '@/components/ui/admin-table'
import { Badge } from '@/components/ui/badge'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import { useAdminNav } from '@/hooks/useAdminNav'
import { extractApiErrorDetail } from '@/lib/apiError'
import { formatRelativeDate } from '@/lib/formatDate'
import { buildDiffPatch } from '@/lib/json-patch'
import type { RoleCreate, RoleDetail as RoleDetailType } from '@/types'

import { AdminSection } from './AdminSection'
import { RoleDetail } from './roles/RoleDetail'
import { RoleForm } from './roles/RoleForm'

type Role = Awaited<ReturnType<typeof getRoles>>[number]

export function RoleManagement() {
  const {
    goToCreate,
    goToDetail,
    goToEdit,
    goToList,
    slug: selectedRoleSlug,
    viewMode,
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
    createMutation,
    deleteMutation,
    error,
    isLoading,
    items: roles,
    updateMutation,
  } = useAdminCrud<
    Role,
    { permissions: string[]; role: RoleCreate },
    { permissions: string[]; role: RoleCreate; slug: string },
    string
  >({
    createFn: async ({ permissions, role }) => {
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
    deleteErrorLabel: 'role',
    deleteFn: deleteRole,
    extraInvalidateKeys: [['role']],
    listFn: getRoles,
    onMutationSuccess: goToList,
    queryKey: ['roles'],
    updateFn: async ({ permissions, role, slug }) => {
      const existing = await getRole(slug)
      const operations = buildDiffPatch(
        existing as unknown as Record<string, unknown>,
        role as unknown as Record<string, unknown>,
        { fields: Object.keys(role) },
      )
      const updated =
        operations.length > 0 ? await updateRole(slug, operations) : existing
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
      createMutation.mutate({ permissions, role: roleData })
    } else if (selectedRoleSlug) {
      updateMutation.mutate({
        permissions,
        role: roleData,
        slug: selectedRoleSlug,
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
        error={isCreate ? createMutation.error : updateMutation.error}
        isLoading={
          isCreate ? createMutation.isPending : updateMutation.isPending
        }
        onCancel={handleCancel}
        onSave={handleSave}
        roleSlug={selectedRoleSlug}
      />
    )
  }

  if (viewMode === 'detail' && selectedRoleSlug) {
    return (
      <RoleDetail
        onBack={handleCancel}
        onEdit={() => goToEdit(selectedRoleSlug)}
        slug={selectedRoleSlug}
      />
    )
  }

  return (
    <AdminSection
      createLabel="New Role"
      error={error}
      errorTitle="Failed to load roles"
      isLoading={isLoading}
      loadingLabel="Loading roles..."
      onCreate={goToCreate}
      onSearchChange={setSearchQuery}
      search={searchQuery}
      searchPlaceholder="Search roles..."
    >
      <AdminTable
        canDelete={canDeleteRole}
        columns={[
          {
            cellAlign: 'left',
            header: 'Role',
            headerAlign: 'left',
            key: 'name',
            render: (role) => (
              <div className="flex items-center gap-2">
                <Shield className="text-info size-4 shrink-0" />
                <span className="text-primary text-sm font-medium">
                  {role.name}
                </span>
              </div>
            ),
          },
          {
            cellAlign: 'center',
            header: 'Slug',
            headerAlign: 'center',
            key: 'slug',
            render: (role) => (
              <span className="text-secondary font-mono text-sm">
                {role.slug}
              </span>
            ),
          },
          {
            cellAlign: 'left',
            header: 'Description',
            headerAlign: 'left',
            key: 'description',
            render: (role) => (
              <span className="text-secondary text-sm">
                {role.description || '-'}
              </span>
            ),
          },
          {
            cellAlign: 'center',
            header: 'Type',
            headerAlign: 'center',
            key: 'type',
            render: (role) =>
              isSystemRole(role) ? (
                <Badge className="gap-1" variant="warning">
                  <Lock className="size-3" />
                  System
                </Badge>
              ) : (
                <Badge variant="info">Custom</Badge>
              ),
          },
          {
            cellAlign: 'center',
            header: 'Last Updated',
            headerAlign: 'center',
            key: 'updated',
            render: (role) => formatRelativeDate(role.updated_at),
          },
        ]}
        emptyMessage={
          searchQuery ? 'No roles match your search' : 'No roles created yet'
        }
        getDeleteLabel={(role) => role.name}
        getRowKey={(role) => role.slug}
        isDeleting={deleteMutation.isPending}
        onDelete={handleDelete}
        onRowClick={(role) =>
          isSystemRole(role) ? goToDetail(role.slug) : goToEdit(role.slug)
        }
        rows={filteredRoles}
      />
    </AdminSection>
  )
}

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
    .map((r, i) => ({ op: operations[i], result: r }))
    .filter(({ result }) => result.status === 'rejected')

  if (failures.length > 0) {
    const detail = failures
      .map(({ op, result }) => {
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
