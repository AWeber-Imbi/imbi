import { useState, useMemo } from 'react'
import { Link2 } from 'lucide-react'
import { EntityIcon } from '@/components/ui/entity-icon'
import { formatRelativeDate } from '@/lib/formatDate'
import { AdminTable, type CanDeleteResult } from '@/components/ui/admin-table'
import { AdminSection } from './AdminSection'
import { LinkDefinitionForm } from './link-definitions/LinkDefinitionForm'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAdminNav } from '@/hooks/useAdminNav'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import {
  listLinkDefinitions,
  deleteLinkDefinition,
  createLinkDefinition,
  updateLinkDefinition,
} from '@/api/endpoints'
import { buildDiffPatch } from '@/lib/json-patch'
import type {
  LinkDefinition,
  LinkDefinitionCreate,
  PatchOperation,
} from '@/types'

export function LinkDefinitionManagement() {
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
    items: linkDefinitions,
    isLoading,
    error,
    createMutation,
    updateMutation,
    deleteMutation,
  } = useAdminCrud<
    LinkDefinition,
    { orgSlug: string; data: LinkDefinitionCreate },
    { orgSlug: string; slug: string; operations: PatchOperation[] },
    { orgSlug: string; slug: string }
  >({
    queryKey: ['linkDefinitions', orgSlug],
    listFn: orgSlug ? (signal) => listLinkDefinitions(orgSlug, signal) : null,
    createFn: ({ orgSlug, data }) => createLinkDefinition(orgSlug, data),
    updateFn: ({ orgSlug, slug, operations }) =>
      updateLinkDefinition(orgSlug, slug, operations),
    deleteFn: ({ orgSlug, slug }) => deleteLinkDefinition(orgSlug, slug),
    onMutationSuccess: goToList,
    deleteErrorLabel: 'link definition',
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

  const handleDelete = (ld: LinkDefinition) => {
    deleteMutation.mutate({ orgSlug: ld.organization.slug, slug: ld.slug })
  }

  const canDeleteLinkDefinition = (ld: LinkDefinition): CanDeleteResult => {
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
    } else if (selectedSlug && selectedLinkDefinition) {
      const operations = buildDiffPatch(
        selectedLinkDefinition as unknown as Record<string, unknown>,
        data as unknown as Record<string, unknown>,
        { fields: Object.keys(data) },
      )
      if (operations.length === 0) {
        goToList()
        return
      }
      updateMutation.mutate({
        orgSlug: selectedLinkDefinition.organization.slug || formOrgSlug,
        slug: selectedSlug,
        operations,
      })
    }
  }

  const handleCancel = () => {
    goToList()
  }

  if (!orgSlug && !isLoading && !error) {
    return (
      <div className="py-12 text-center text-tertiary">
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
    <AdminSection
      searchPlaceholder="Search link definitions..."
      search={searchQuery}
      onSearchChange={setSearchQuery}
      createLabel="New Link Definition"
      onCreate={goToCreate}
      isLoading={isLoading}
      loadingLabel="Loading link definitions..."
      error={error}
      errorTitle="Failed to load link definitions"
    >
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
                    <Link2 className="h-4 w-4 text-info" />
                  )}
                </div>
                <div>
                  <div className="text-primary">{ld.name}</div>
                  {ld.description && (
                    <div className="text-sm text-tertiary">
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
              <code className="rounded bg-secondary px-2 py-1 text-primary">
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
                <span className="text-tertiary">--</span>
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
    </AdminSection>
  )
}
