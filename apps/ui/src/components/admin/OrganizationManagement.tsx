import { useState, useMemo } from 'react'
import { Building2 } from 'lucide-react'
import { formatRelativeDate } from '@/lib/formatDate'
import { EntityIcon } from '@/components/ui/entity-icon'
import { AdminTable } from '@/components/ui/admin-table'
import type { CanDeleteResult } from '@/components/ui/admin-table'
import { AdminSection } from './AdminSection'
import { OrganizationForm } from './organizations/OrganizationForm'
import { OrganizationDetail } from './organizations/OrganizationDetail'
import { useAdminNav } from '@/hooks/useAdminNav'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import {
  listOrganizations,
  deleteOrganization,
  createOrganization,
  updateOrganization,
} from '@/api/endpoints'
import { buildDiffPatch } from '@/lib/json-patch'
import type { Organization, OrganizationCreate, PatchOperation } from '@/types'

export function OrganizationManagement() {
  const {
    viewMode,
    slug: selectedOrgSlug,
    goToList,
    goToCreate,
    goToEdit,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')

  const {
    items: organizations,
    isLoading,
    error,
    createMutation,
    updateMutation,
    deleteMutation,
  } = useAdminCrud<
    Organization,
    OrganizationCreate,
    { slug: string; operations: PatchOperation[] },
    string
  >({
    queryKey: ['organizations'],
    listFn: listOrganizations,
    createFn: createOrganization,
    updateFn: ({ slug, operations }) => updateOrganization(slug, operations),
    deleteFn: deleteOrganization,
    onMutationSuccess: goToList,
    deleteErrorLabel: 'organization',
  })

  const canDeleteOrganization = (org: Organization): CanDeleteResult => {
    if (organizations.length <= 1) {
      return { allowed: false, reason: 'Cannot delete the only organization' }
    }
    const teamCount = org.relationships?.teams?.count ?? 0
    if (teamCount > 0) {
      return {
        allowed: false,
        blockedBy: [{ count: teamCount, label: 'team', href: '/admin/teams' }],
      }
    }
    return { allowed: true }
  }

  const filteredOrgs = organizations.filter((org) => {
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      return (
        org.name.toLowerCase().includes(query) ||
        org.slug.toLowerCase().includes(query) ||
        (org.description?.toLowerCase().includes(query) ?? false)
      )
    }
    return true
  })

  const selectedOrg = useMemo(
    () => organizations.find((o) => o.slug === selectedOrgSlug) || null,
    [organizations, selectedOrgSlug],
  )

  const handleDelete = (org: Organization) => {
    deleteMutation.mutate(org.slug)
  }

  const handleSave = (orgData: OrganizationCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate(orgData)
    } else if (selectedOrgSlug && selectedOrg) {
      const operations = buildDiffPatch(
        selectedOrg as unknown as Record<string, unknown>,
        orgData as unknown as Record<string, unknown>,
        { fields: Object.keys(orgData) },
      )
      if (operations.length === 0) {
        goToList()
        return
      }
      updateMutation.mutate({ slug: selectedOrgSlug, operations })
    }
  }

  const handleCancel = () => {
    goToList()
  }

  // Guard for invalid organization slug in URL
  if (
    !isLoading &&
    !error &&
    (viewMode === 'edit' || viewMode === 'detail') &&
    !!selectedOrgSlug &&
    !selectedOrg
  ) {
    return (
      <div className="rounded-lg border border-tertiary p-4 text-secondary">
        Organization not found. It may have been deleted.
      </div>
    )
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <OrganizationForm
        organization={selectedOrg}
        onSave={handleSave}
        onCancel={handleCancel}
        isLoading={createMutation.isPending || updateMutation.isPending}
        error={createMutation.error || updateMutation.error}
      />
    )
  }

  if (viewMode === 'detail' && selectedOrg) {
    return (
      <OrganizationDetail
        organization={selectedOrg}
        onEdit={() => goToEdit(selectedOrg.slug)}
        onBack={handleCancel}
      />
    )
  }

  return (
    <AdminSection
      searchPlaceholder="Search organizations..."
      search={searchQuery}
      onSearchChange={setSearchQuery}
      createLabel="New Organization"
      onCreate={goToCreate}
      isLoading={isLoading}
      loadingLabel="Loading organizations..."
      error={error}
      errorTitle="Failed to load organizations"
    >
      <AdminTable
        columns={[
          {
            key: 'name',
            header: 'Organization',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (org) => (
              <div className="flex items-center gap-3">
                <div
                  className={
                    'flex size-8 flex-shrink-0 items-center justify-center rounded-lg bg-info'
                  }
                >
                  {org.icon ? (
                    <EntityIcon
                      icon={org.icon}
                      className="size-5 rounded object-cover"
                    />
                  ) : (
                    <Building2 className="h-4 w-4 text-info" />
                  )}
                </div>
                <div>
                  <div className="text-primary">{org.name}</div>
                  {org.description && (
                    <div className="text-sm text-tertiary">
                      {org.description}
                    </div>
                  )}
                </div>
              </div>
            ),
          },
          {
            key: 'slug',
            header: 'Slug',
            headerAlign: 'center',
            cellAlign: 'center',
            render: (org) => (
              <code className="rounded bg-secondary px-2 py-1 text-primary">
                {org.slug}
              </code>
            ),
          },
          {
            key: 'teams',
            header: 'Teams',
            headerAlign: 'right',
            cellAlign: 'right',
            render: (org) => (
              <span
                className={
                  (org.relationships?.teams?.count ?? 0) === 0
                    ? 'text-tertiary'
                    : 'text-secondary'
                }
              >
                {org.relationships?.teams?.count ?? 0}
              </span>
            ),
          },
          {
            key: 'members',
            header: 'Members',
            headerAlign: 'right',
            cellAlign: 'right',
            render: (org) => (
              <span
                className={
                  (org.relationships?.members?.count ?? 0) === 0
                    ? 'text-tertiary'
                    : 'text-secondary'
                }
              >
                {org.relationships?.members?.count ?? 0}
              </span>
            ),
          },
          {
            key: 'projects',
            header: 'Projects',
            headerAlign: 'right',
            cellAlign: 'right',
            render: (org) => (
              <span
                className={
                  (org.relationships?.projects?.count ?? 0) === 0
                    ? 'text-tertiary'
                    : 'text-secondary'
                }
              >
                {org.relationships?.projects?.count ?? 0}
              </span>
            ),
          },
          {
            key: 'updated',
            header: 'Last Updated',
            headerAlign: 'center',
            cellAlign: 'center',
            render: (org) =>
              formatRelativeDate(org.updated_at ?? org.created_at),
          },
        ]}
        rows={filteredOrgs}
        getRowKey={(org) => org.slug}
        getDeleteLabel={(org) => org.name}
        onRowClick={(org) => goToEdit(org.slug)}
        onDelete={handleDelete}
        canDelete={canDeleteOrganization}
        isDeleting={deleteMutation.isPending}
        emptyMessage={
          searchQuery
            ? 'No organizations match your search.'
            : 'No organizations created yet.'
        }
      />
    </AdminSection>
  )
}
