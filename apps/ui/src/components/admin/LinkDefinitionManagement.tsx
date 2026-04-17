import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '@/api/client'
import { Plus, Search, Link2, AlertCircle } from 'lucide-react'
import { EntityIcon } from '@/components/ui/entity-icon'
import { formatRelativeDate } from '@/lib/formatDate'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { AdminTable, type CanDeleteResult } from '@/components/ui/admin-table'
import { LinkDefinitionForm } from './link-definitions/LinkDefinitionForm'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAdminNav } from '@/hooks/useAdminNav'
import {
  listLinkDefinitions,
  deleteLinkDefinition,
  createLinkDefinition,
  updateLinkDefinition,
} from '@/api/endpoints'
import type { LinkDefinitionCreate } from '@/types'

export function LinkDefinitionManagement() {
  const queryClient = useQueryClient()
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug
  const {
    viewMode,
    slug: selectedSlug,
    goToList,
    goToCreate,
    goToEdit,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')

  const {
    data: linkDefinitions = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ['linkDefinitions', orgSlug],
    queryFn: () => listLinkDefinitions(orgSlug!),
    enabled: !!orgSlug,
  })

  const createMutation = useMutation({
    mutationFn: ({
      orgSlug,
      data,
    }: {
      orgSlug: string
      data: LinkDefinitionCreate
    }) => createLinkDefinition(orgSlug, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['linkDefinitions', orgSlug] })
      goToList()
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({
      orgSlug,
      slug,
      data,
    }: {
      orgSlug: string
      slug: string
      data: LinkDefinitionCreate
    }) => updateLinkDefinition(orgSlug, slug, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['linkDefinitions', orgSlug] })
      goToList()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: ({ orgSlug, slug }: { orgSlug: string; slug: string }) =>
      deleteLinkDefinition(orgSlug, slug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['linkDefinitions', orgSlug] })
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      alert(
        `Failed to delete link definition: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  const filteredLinkDefinitions = linkDefinitions.filter((ld) => {
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      return (
        ld.name.toLowerCase().includes(query) ||
        ld.slug.toLowerCase().includes(query) ||
        (ld.description?.toLowerCase().includes(query) ?? false)
      )
    }
    return true
  })

  const selectedLinkDefinition = useMemo(
    () => linkDefinitions.find((ld) => ld.slug === selectedSlug) || null,
    [linkDefinitions, selectedSlug],
  )

  const handleDelete = (ld: (typeof linkDefinitions)[number]) => {
    deleteMutation.mutate({ orgSlug: ld.organization.slug, slug: ld.slug })
  }

  const canDeleteLinkDefinition = (
    ld: (typeof linkDefinitions)[number],
  ): CanDeleteResult => {
    const projects = ld.relationships?.projects?.count ?? 0
    if (projects === 0) return { allowed: true }
    return {
      allowed: false,
      blockedBy: [{ count: projects, label: 'project', href: '/projects' }],
    }
  }

  const handleSave = (formOrgSlug: string, data: LinkDefinitionCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate({ orgSlug: formOrgSlug, data })
    } else if (selectedSlug) {
      updateMutation.mutate({
        orgSlug: selectedLinkDefinition?.organization.slug || formOrgSlug,
        slug: selectedSlug,
        data,
      })
    }
  }

  const handleCancel = () => {
    goToList()
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className={'text-sm text-secondary'}>
          Loading link definitions...
        </div>
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
          <div className="font-medium">Failed to load link definitions</div>
          <div className="mt-1 text-sm">
            {error instanceof Error ? error.message : 'An error occurred'}
          </div>
        </div>
      </div>
    )
  }

  if (!orgSlug) {
    return (
      <div className={'py-12 text-center text-tertiary'}>
        Select an organization to manage link definitions.
      </div>
    )
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <LinkDefinitionForm
        linkDefinition={selectedLinkDefinition}
        onSave={handleSave}
        onCancel={handleCancel}
        isLoading={createMutation.isPending || updateMutation.isPending}
        error={createMutation.error || updateMutation.error}
      />
    )
  }

  if (viewMode === 'detail' && selectedLinkDefinition) {
    return (
      <LinkDefinitionForm
        linkDefinition={selectedLinkDefinition}
        onSave={handleSave}
        onCancel={handleCancel}
        isLoading={updateMutation.isPending}
        error={updateMutation.error}
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
              placeholder="Search link definitions..."
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
          New Link Definition
        </Button>
      </div>

      <AdminTable
        columns={[
          {
            key: 'name',
            header: 'Name',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (ld) => (
              <div className="flex items-center gap-3">
                <div
                  className={
                    'flex size-8 flex-shrink-0 items-center justify-center rounded-lg bg-info'
                  }
                >
                  {ld.icon ? (
                    <EntityIcon
                      icon={ld.icon}
                      className="size-5 object-cover"
                    />
                  ) : (
                    <Link2 className={'h-4 w-4 text-info'} />
                  )}
                </div>
                <div>
                  <div className={'text-primary'}>{ld.name}</div>
                  {ld.description && (
                    <div className={'text-sm text-tertiary'}>
                      {ld.description}
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
            render: (ld) => (
              <code className={'rounded bg-secondary px-2 py-1 text-primary'}>
                {ld.slug}
              </code>
            ),
          },
          {
            key: 'url_template',
            header: 'URL Template',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (ld) =>
              ld.url_template ? (
                <code
                  className={
                    'rounded bg-secondary px-2 py-1 text-xs text-primary'
                  }
                >
                  {ld.url_template}
                </code>
              ) : (
                <span className={'text-tertiary'}>--</span>
              ),
          },
          {
            key: 'projects',
            header: 'Projects',
            headerAlign: 'center',
            cellAlign: 'center',
            render: (ld) => (
              <span
                className={
                  (ld.relationships?.projects?.count ?? 0) === 0
                    ? 'text-tertiary'
                    : 'text-secondary'
                }
              >
                {ld.relationships?.projects?.count ?? 0}
              </span>
            ),
          },
          {
            key: 'updated',
            header: 'Last Updated',
            headerAlign: 'center',
            cellAlign: 'center',
            render: (ld) => formatRelativeDate(ld.updated_at ?? ld.created_at),
          },
        ]}
        rows={filteredLinkDefinitions}
        getRowKey={(ld) => ld.slug}
        getDeleteLabel={(ld) => ld.name}
        onRowClick={(ld) => goToEdit(ld.slug)}
        onDelete={handleDelete}
        canDelete={canDeleteLinkDefinition}
        isDeleting={deleteMutation.isPending}
        emptyMessage={
          searchQuery
            ? 'No link definitions found matching your search.'
            : selectedOrganization
              ? `No link definitions in ${selectedOrganization.name} yet.`
              : 'No link definitions created yet.'
        }
      />
    </div>
  )
}
