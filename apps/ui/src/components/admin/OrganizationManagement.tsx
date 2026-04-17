import { useState, useMemo } from 'react'
import { AdminTable } from '@/components/ui/admin-table'
import type { CanDeleteResult } from '@/components/ui/admin-table'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '@/api/client'
import { Plus, Search, Building2, AlertCircle } from 'lucide-react'
import { formatRelativeDate } from '@/lib/formatDate'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { EntityIcon } from '@/components/ui/entity-icon'
import { OrganizationForm } from './organizations/OrganizationForm'
import { OrganizationDetail } from './organizations/OrganizationDetail'
import { useAdminNav } from '@/hooks/useAdminNav'
import {
  listOrganizations,
  deleteOrganization,
  createOrganization,
  updateOrganization,
} from '@/api/endpoints'
import type { OrganizationCreate } from '@/types'

export function OrganizationManagement() {
  const queryClient = useQueryClient()
  const {
    viewMode,
    slug: selectedOrgSlug,
    goToList,
    goToCreate,
    goToEdit,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')

  const {
    data: organizations = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ['organizations'],
    queryFn: listOrganizations,
  })

  type Organization = (typeof organizations)[number]

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

  const createMutation = useMutation({
    mutationFn: createOrganization,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['organizations'] })
      goToList()
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ slug, org }: { slug: string; org: OrganizationCreate }) =>
      updateOrganization(slug, org),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['organizations'] })
      goToList()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: deleteOrganization,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['organizations'] })
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      alert(
        `Failed to delete organization: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

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
    } else if (selectedOrgSlug) {
      updateMutation.mutate({ slug: selectedOrgSlug, org: orgData })
    }
  }

  const handleCancel = () => {
    goToList()
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className={'text-sm text-secondary'}>Loading organizations...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div
        className={`flex items-center gap-3 rounded-lg border p-4 ${'border-danger bg-danger text-danger'}`}
      >
        <AlertCircle className="h-5 w-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load organizations</div>
          <div className="mt-1 text-sm">
            {error instanceof Error ? error.message : 'An error occurred'}
          </div>
        </div>
      </div>
    )
  }

  // Guard for invalid organization slug in URL
  if (
    (viewMode === 'edit' || viewMode === 'detail') &&
    !!selectedOrgSlug &&
    !selectedOrg
  ) {
    return (
      <div className={'rounded-lg border border-tertiary p-4 text-secondary'}>
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
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex-1">
          <div className="relative max-w-md">
            <Search
              className={`absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${'text-tertiary'}`}
            />
            <Input
              placeholder="Search organizations..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={'pl-10'}
            />
          </div>
        </div>
        <Button
          onClick={goToCreate}
          className="bg-action text-action-foreground hover:bg-action-hover"
        >
          <Plus className="mr-2 h-4 w-4" />
          New Organization
        </Button>
      </div>

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
                    <Building2 className={'h-4 w-4 text-info'} />
                  )}
                </div>
                <div>
                  <div className={'text-primary'}>{org.name}</div>
                  {org.description && (
                    <div className={'text-sm text-tertiary'}>
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
              <code className={'rounded bg-secondary px-2 py-1 text-primary'}>
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
    </div>
  )
}
