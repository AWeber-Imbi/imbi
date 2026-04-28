import { useMemo, useState } from 'react'

import { Link2 } from 'lucide-react'

import {
  createLinkDefinition,
  deleteLinkDefinition,
  listLinkDefinitions,
  updateLinkDefinition,
} from '@/api/endpoints'
import { AdminTable, type CanDeleteResult } from '@/components/ui/admin-table'
import { EntityIcon } from '@/components/ui/entity-icon'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import { useAdminNav } from '@/hooks/useAdminNav'
import { formatRelativeDate } from '@/lib/formatDate'
import { buildDiffPatch } from '@/lib/json-patch'
import type {
  LinkDefinition,
  LinkDefinitionCreate,
  PatchOperation,
} from '@/types'

import { AdminSection } from './AdminSection'
import { LinkDefinitionForm } from './link-definitions/LinkDefinitionForm'

export function LinkDefinitionManagement() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug
  const {
    goToCreate,
    goToEdit,
    goToList,
    slug: selectedSlug,
    viewMode,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')

  const {
    createMutation,
    deleteMutation,
    error,
    isLoading,
    items: linkDefinitions,
    updateMutation,
  } = useAdminCrud<
    LinkDefinition,
    { data: LinkDefinitionCreate; orgSlug: string },
    { operations: PatchOperation[]; orgSlug: string; slug: string },
    { orgSlug: string; slug: string }
  >({
    createFn: ({ data, orgSlug }) => createLinkDefinition(orgSlug, data),
    deleteErrorLabel: 'link definition',
    deleteFn: ({ orgSlug, slug }) => deleteLinkDefinition(orgSlug, slug),
    listFn: orgSlug ? (signal) => listLinkDefinitions(orgSlug, signal) : null,
    onMutationSuccess: goToList,
    queryKey: ['linkDefinitions', orgSlug],
    updateFn: ({ operations, orgSlug, slug }) =>
      updateLinkDefinition(orgSlug, slug, operations),
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
      blockedBy: [{ count: projects, href: '/projects', label: 'project' }],
    }
  }

  const handleSave = (formOrgSlug: string, data: LinkDefinitionCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate({ data, orgSlug: formOrgSlug })
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
        operations,
        orgSlug: selectedLinkDefinition.organization.slug || formOrgSlug,
        slug: selectedSlug,
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
        error={createMutation.error || updateMutation.error}
        isLoading={createMutation.isPending || updateMutation.isPending}
        linkDefinition={selectedLinkDefinition}
        onCancel={handleCancel}
        onSave={handleSave}
      />
    )
  }

  if (viewMode === 'detail' && selectedLinkDefinition) {
    return (
      <LinkDefinitionForm
        error={updateMutation.error}
        isLoading={updateMutation.isPending}
        linkDefinition={selectedLinkDefinition}
        onCancel={handleCancel}
        onSave={handleSave}
      />
    )
  }

  return (
    <AdminSection
      createLabel="New Link Definition"
      error={error}
      errorTitle="Failed to load link definitions"
      isLoading={isLoading}
      loadingLabel="Loading link definitions..."
      onCreate={goToCreate}
      onSearchChange={setSearchQuery}
      search={searchQuery}
      searchPlaceholder="Search link definitions..."
    >
      <AdminTable
        canDelete={canDeleteLinkDefinition}
        columns={[
          {
            cellAlign: 'left',
            header: 'Name',
            headerAlign: 'left',
            key: 'name',
            render: (ld) => (
              <div className="flex items-center gap-3">
                <div
                  className={
                    'flex size-8 flex-shrink-0 items-center justify-center rounded-lg bg-info'
                  }
                >
                  {ld.icon ? (
                    <EntityIcon
                      className="size-5 object-cover"
                      icon={ld.icon}
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
            cellAlign: 'center',
            header: 'Slug',
            headerAlign: 'center',
            key: 'slug',
            render: (ld) => (
              <code className="rounded bg-secondary px-2 py-1 text-primary">
                {ld.slug}
              </code>
            ),
          },
          {
            cellAlign: 'left',
            header: 'URL Template',
            headerAlign: 'left',
            key: 'url_template',
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
            cellAlign: 'center',
            header: 'Projects',
            headerAlign: 'center',
            key: 'projects',
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
            cellAlign: 'center',
            header: 'Last Updated',
            headerAlign: 'center',
            key: 'updated',
            render: (ld) => formatRelativeDate(ld.updated_at ?? ld.created_at),
          },
        ]}
        emptyMessage={
          searchQuery
            ? 'No link definitions found matching your search.'
            : selectedOrganization
              ? `No link definitions in ${selectedOrganization.name} yet.`
              : 'No link definitions created yet.'
        }
        getDeleteLabel={(ld) => ld.name}
        getRowKey={(ld) => ld.slug}
        isDeleting={deleteMutation.isPending}
        onDelete={handleDelete}
        onRowClick={(ld) => goToEdit(ld.slug)}
        rows={filteredLinkDefinitions}
      />
    </AdminSection>
  )
}
