import { useMemo, useState } from 'react'

import { StickyNote } from 'lucide-react'

import {
  createDocumentTemplate,
  deleteDocumentTemplate,
  listDocumentTemplates,
  updateDocumentTemplate,
} from '@/api/endpoints'
import { AdminTable } from '@/components/ui/admin-table'
import { EntityIcon } from '@/components/ui/entity-icon'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import { useAdminNav } from '@/hooks/useAdminNav'
import { formatRelativeDate } from '@/lib/formatDate'
import { buildDiffPatch } from '@/lib/json-patch'
import type {
  DocumentTemplate,
  DocumentTemplateCreate,
  PatchOperation,
} from '@/types'

import { AdminSection } from './AdminSection'
import { DocumentTemplateForm } from './document-templates/DocumentTemplateForm'

export function DocumentTemplateManagement() {
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
    items: documentTemplates,
    updateMutation,
  } = useAdminCrud<
    DocumentTemplate,
    { data: DocumentTemplateCreate; orgSlug: string },
    { operations: PatchOperation[]; orgSlug: string; slug: string },
    { orgSlug: string; slug: string }
  >({
    createFn: ({ data, orgSlug }) => createDocumentTemplate(orgSlug, data),
    deleteErrorLabel: 'document template',
    deleteFn: ({ orgSlug, slug }) => deleteDocumentTemplate(orgSlug, slug),
    listFn: orgSlug ? (signal) => listDocumentTemplates(orgSlug, signal) : null,
    onMutationSuccess: goToList,
    queryKey: ['documentTemplates', orgSlug],
    updateFn: ({ operations, orgSlug, slug }) =>
      updateDocumentTemplate(orgSlug, slug, operations),
  })

  const filteredDocumentTemplates = documentTemplates.filter((nt) => {
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      return (
        nt.name.toLowerCase().includes(query) ||
        nt.slug.toLowerCase().includes(query) ||
        (nt.description?.toLowerCase().includes(query) ?? false)
      )
    }
    return true
  })

  const selectedDocumentTemplate = useMemo(
    () => documentTemplates.find((nt) => nt.slug === selectedSlug) || null,
    [documentTemplates, selectedSlug],
  )

  const handleDelete = (nt: DocumentTemplate) => {
    deleteMutation.mutate({ orgSlug: nt.organization.slug, slug: nt.slug })
  }

  const handleSave = (formOrgSlug: string, data: DocumentTemplateCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate({ data, orgSlug: formOrgSlug })
    } else if (selectedSlug && selectedDocumentTemplate) {
      const beforeFields: Record<string, unknown> = {
        content: selectedDocumentTemplate.content ?? '',
        description: selectedDocumentTemplate.description ?? null,
        icon: selectedDocumentTemplate.icon ?? null,
        name: selectedDocumentTemplate.name,
        project_type_slugs: selectedDocumentTemplate.project_type_slugs ?? [],
        slug: selectedDocumentTemplate.slug,
        sort_order: selectedDocumentTemplate.sort_order ?? 0,
        tags: (selectedDocumentTemplate.tags ?? []).map((t) => t.slug),
        title: selectedDocumentTemplate.title ?? null,
      }
      const operations = buildDiffPatch(
        beforeFields,
        data as unknown as Record<string, unknown>,
        { fields: Object.keys(data) },
      )
      if (operations.length === 0) {
        goToList()
        return
      }
      updateMutation.mutate({
        operations,
        orgSlug: selectedDocumentTemplate.organization.slug || formOrgSlug,
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
        Select an organization to manage document templates.
      </div>
    )
  }

  if (viewMode === 'edit' && !selectedDocumentTemplate) {
    return (
      <div className="py-12 text-center text-tertiary">
        {isLoading
          ? 'Loading document template...'
          : 'Document template not found.'}
      </div>
    )
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <DocumentTemplateForm
        documentTemplate={selectedDocumentTemplate}
        error={createMutation.error || updateMutation.error}
        isLoading={createMutation.isPending || updateMutation.isPending}
        key={selectedSlug ?? 'create'}
        onCancel={handleCancel}
        onSave={handleSave}
      />
    )
  }

  if (viewMode === 'detail' && selectedDocumentTemplate) {
    return (
      <DocumentTemplateForm
        documentTemplate={selectedDocumentTemplate}
        error={updateMutation.error}
        isLoading={updateMutation.isPending}
        onCancel={handleCancel}
        onSave={handleSave}
      />
    )
  }

  return (
    <AdminSection
      createLabel="New Document Template"
      error={error}
      errorTitle="Failed to load document templates"
      isLoading={isLoading}
      loadingLabel="Loading document templates..."
      onCreate={goToCreate}
      onSearchChange={setSearchQuery}
      search={searchQuery}
      searchPlaceholder="Search document templates..."
    >
      <AdminTable
        columns={[
          {
            cellAlign: 'left',
            header: 'Name',
            headerAlign: 'left',
            key: 'name',
            render: (nt) => (
              <div className="flex items-center gap-3">
                <div className="flex size-8 flex-shrink-0 items-center justify-center rounded-lg bg-info">
                  {nt.icon ? (
                    <EntityIcon
                      className="size-5 object-cover"
                      icon={nt.icon}
                    />
                  ) : (
                    <StickyNote className="h-4 w-4 text-info" />
                  )}
                </div>
                <div>
                  <div className="text-primary">{nt.name}</div>
                  {nt.description && (
                    <div className="text-sm text-tertiary">
                      {nt.description}
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
            render: (nt) => (
              <code className="rounded bg-secondary px-2 py-1 text-primary">
                {nt.slug}
              </code>
            ),
          },
          {
            cellAlign: 'center',
            header: 'Project Types',
            headerAlign: 'center',
            key: 'project_types',
            render: (nt) => {
              const count = nt.project_type_slugs?.length ?? 0
              return (
                <span
                  className={count === 0 ? 'text-tertiary' : 'text-secondary'}
                >
                  {count === 0 ? 'All' : count}
                </span>
              )
            },
          },
          {
            cellAlign: 'center',
            header: 'Tags',
            headerAlign: 'center',
            key: 'tags',
            render: (nt) => {
              const count = nt.tags?.length ?? 0
              return (
                <span
                  className={count === 0 ? 'text-tertiary' : 'text-secondary'}
                >
                  {count}
                </span>
              )
            },
          },
          {
            cellAlign: 'center',
            header: 'Sort',
            headerAlign: 'center',
            key: 'sort_order',
            render: (nt) => (
              <span className="text-secondary">{nt.sort_order ?? 0}</span>
            ),
          },
          {
            cellAlign: 'center',
            header: 'Last Updated',
            headerAlign: 'center',
            key: 'updated',
            render: (nt) => formatRelativeDate(nt.updated_at ?? nt.created_at),
          },
        ]}
        emptyMessage={
          searchQuery
            ? 'No document templates found matching your search.'
            : selectedOrganization
              ? `No document templates in ${selectedOrganization.name} yet.`
              : 'No document templates created yet.'
        }
        getDeleteLabel={(nt) => nt.name}
        getRowKey={(nt) => nt.slug}
        isDeleting={deleteMutation.isPending}
        onDelete={handleDelete}
        onRowClick={(nt) => goToEdit(nt.slug)}
        rows={filteredDocumentTemplates}
      />
    </AdminSection>
  )
}
