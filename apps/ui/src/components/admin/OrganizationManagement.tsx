import { useMemo, useState } from 'react'

import { Building2 } from 'lucide-react'

import {
  createOrganization,
  deleteOrganization,
  listOrganizations,
  updateOrganization,
} from '@/api/endpoints'
import { AdminTable } from '@/components/ui/admin-table'
import type { CanDeleteResult } from '@/components/ui/admin-table'
import { EntityIcon } from '@/components/ui/entity-icon'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import { useAdminNav } from '@/hooks/useAdminNav'
import { formatRelativeDate } from '@/lib/formatDate'
import { buildDiffPatch } from '@/lib/json-patch'
import type { Organization, OrganizationCreate, PatchOperation } from '@/types'

import { AdminSection } from './AdminSection'
import { OrganizationDetail } from './organizations/OrganizationDetail'
import { OrganizationForm } from './organizations/OrganizationForm'

export function OrganizationManagement() {
  const {
    goToCreate,
    goToEdit,
    goToList,
    slug: selectedOrgSlug,
    viewMode,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')

  const {
    createMutation,
    deleteMutation,
    error,
    isLoading,
    items: organizations,
    updateMutation,
  } = useAdminCrud<
    Organization,
    OrganizationCreate,
    { operations: PatchOperation[]; slug: string },
    string
  >({
    createFn: createOrganization,
    deleteErrorLabel: 'organization',
    deleteFn: deleteOrganization,
    listFn: listOrganizations,
    onMutationSuccess: goToList,
    queryKey: ['organizations'],
    updateFn: ({ operations, slug }) => updateOrganization(slug, operations),
  })

  const canDeleteOrganization = (org: Organization): CanDeleteResult => {
    if (organizations.length <= 1) {
      return { allowed: false, reason: 'Cannot delete the only organization' }
    }
    const teamCount = org.relationships?.teams?.count ?? 0
    if (teamCount > 0) {
      return {
        allowed: false,
        blockedBy: [{ count: teamCount, href: '/admin/teams', label: 'team' }],
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
      updateMutation.mutate({ operations, slug: selectedOrgSlug })
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
      <div className="border-tertiary text-secondary rounded-lg border p-4">
        Organization not found. It may have been deleted.
      </div>
    )
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <OrganizationForm
        error={createMutation.error || updateMutation.error}
        isLoading={createMutation.isPending || updateMutation.isPending}
        onCancel={handleCancel}
        onSave={handleSave}
        organization={selectedOrg}
      />
    )
  }

  if (viewMode === 'detail' && selectedOrg) {
    return (
      <OrganizationDetail
        onBack={handleCancel}
        onEdit={() => goToEdit(selectedOrg.slug)}
        organization={selectedOrg}
      />
    )
  }

  return (
    <AdminSection
      createLabel="New Organization"
      error={error}
      errorTitle="Failed to load organizations"
      isLoading={isLoading}
      loadingLabel="Loading organizations..."
      onCreate={goToCreate}
      onSearchChange={setSearchQuery}
      search={searchQuery}
      searchPlaceholder="Search organizations..."
    >
      <AdminTable
        canDelete={canDeleteOrganization}
        columns={[
          {
            cellAlign: 'left',
            header: 'Organization',
            headerAlign: 'left',
            key: 'name',
            render: (org) => (
              <div className="flex items-center gap-3">
                <div
                  className={
                    'bg-info flex size-8 shrink-0 items-center justify-center rounded-lg'
                  }
                >
                  {org.icon ? (
                    <EntityIcon
                      className="size-5 rounded object-cover"
                      icon={org.icon}
                    />
                  ) : (
                    <Building2 className="text-info size-4" />
                  )}
                </div>
                <div>
                  <div className="text-primary">{org.name}</div>
                  {org.description && (
                    <div className="text-tertiary text-sm">
                      {org.description}
                    </div>
                  )}
                </div>
              </div>
            ),
          },
          {
            cellAlign: 'center',
            header: 'Slug',
            headerAlign: 'center',
            key: 'slug',
            render: (org) => (
              <code className="bg-secondary text-primary rounded px-2 py-1">
                {org.slug}
              </code>
            ),
          },
          {
            cellAlign: 'right',
            header: 'Teams',
            headerAlign: 'right',
            key: 'teams',
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
            cellAlign: 'right',
            header: 'Members',
            headerAlign: 'right',
            key: 'members',
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
            cellAlign: 'right',
            header: 'Projects',
            headerAlign: 'right',
            key: 'projects',
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
            cellAlign: 'center',
            header: 'Last Updated',
            headerAlign: 'center',
            key: 'updated',
            render: (org) =>
              formatRelativeDate(org.updated_at ?? org.created_at),
          },
        ]}
        emptyMessage={
          searchQuery
            ? 'No organizations match your search.'
            : 'No organizations created yet.'
        }
        getDeleteLabel={(org) => org.name}
        getRowKey={(org) => org.slug}
        isDeleting={deleteMutation.isPending}
        onDelete={handleDelete}
        onRowClick={(org) => goToEdit(org.slug)}
        rows={filteredOrgs}
      />
    </AdminSection>
  )
}
