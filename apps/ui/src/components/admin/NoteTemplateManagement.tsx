import { useState, useMemo } from 'react'
import { StickyNote } from 'lucide-react'
import { EntityIcon } from '@/components/ui/entity-icon'
import { formatRelativeDate } from '@/lib/formatDate'
import { AdminTable } from '@/components/ui/admin-table'
import { AdminSection } from './AdminSection'
import { NoteTemplateForm } from './note-templates/NoteTemplateForm'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAdminNav } from '@/hooks/useAdminNav'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import {
  listNoteTemplates,
  deleteNoteTemplate,
  createNoteTemplate,
  updateNoteTemplate,
} from '@/api/endpoints'
import { buildDiffPatch } from '@/lib/json-patch'
import type { NoteTemplate, NoteTemplateCreate, PatchOperation } from '@/types'

export function NoteTemplateManagement() {
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
    items: noteTemplates,
    isLoading,
    error,
    createMutation,
    updateMutation,
    deleteMutation,
  } = useAdminCrud<
    NoteTemplate,
    { orgSlug: string; data: NoteTemplateCreate },
    { orgSlug: string; slug: string; operations: PatchOperation[] },
    { orgSlug: string; slug: string }
  >({
    queryKey: ['noteTemplates', orgSlug],
    listFn: orgSlug ? (signal) => listNoteTemplates(orgSlug, signal) : null,
    createFn: ({ orgSlug, data }) => createNoteTemplate(orgSlug, data),
    updateFn: ({ orgSlug, slug, operations }) =>
      updateNoteTemplate(orgSlug, slug, operations),
    deleteFn: ({ orgSlug, slug }) => deleteNoteTemplate(orgSlug, slug),
    onMutationSuccess: goToList,
    deleteErrorLabel: 'note template',
  })

  const filteredNoteTemplates = noteTemplates.filter((nt) => {
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

  const selectedNoteTemplate = useMemo(
    () => noteTemplates.find((nt) => nt.slug === selectedSlug) || null,
    [noteTemplates, selectedSlug],
  )

  const handleDelete = (nt: NoteTemplate) => {
    deleteMutation.mutate({ orgSlug: nt.organization.slug, slug: nt.slug })
  }

  const handleSave = (formOrgSlug: string, data: NoteTemplateCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate({ orgSlug: formOrgSlug, data })
    } else if (selectedSlug && selectedNoteTemplate) {
      const beforeFields: Record<string, unknown> = {
        name: selectedNoteTemplate.name,
        slug: selectedNoteTemplate.slug,
        description: selectedNoteTemplate.description ?? null,
        icon: selectedNoteTemplate.icon ?? null,
        title: selectedNoteTemplate.title ?? null,
        content: selectedNoteTemplate.content ?? '',
        tags: (selectedNoteTemplate.tags ?? []).map((t) => t.slug),
        project_type_slugs: selectedNoteTemplate.project_type_slugs ?? [],
        sort_order: selectedNoteTemplate.sort_order ?? 0,
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
        orgSlug: selectedNoteTemplate.organization.slug || formOrgSlug,
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
        Select an organization to manage note templates.
      </div>
    )
  }

  if (viewMode === 'edit' && !selectedNoteTemplate) {
    return (
      <div className="py-12 text-center text-tertiary">
        {isLoading ? 'Loading note template...' : 'Note template not found.'}
      </div>
    )
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <NoteTemplateForm
        key={selectedSlug ?? 'create'}
        noteTemplate={selectedNoteTemplate}
        onSave={handleSave}
        onCancel={handleCancel}
        isLoading={createMutation.isPending || updateMutation.isPending}
        error={createMutation.error || updateMutation.error}
      />
    )
  }

  if (viewMode === 'detail' && selectedNoteTemplate) {
    return (
      <NoteTemplateForm
        noteTemplate={selectedNoteTemplate}
        onSave={handleSave}
        onCancel={handleCancel}
        isLoading={updateMutation.isPending}
        error={updateMutation.error}
      />
    )
  }

  return (
    <AdminSection
      searchPlaceholder="Search note templates..."
      search={searchQuery}
      onSearchChange={setSearchQuery}
      createLabel="New Note Template"
      onCreate={goToCreate}
      isLoading={isLoading}
      loadingLabel="Loading note templates..."
      error={error}
      errorTitle="Failed to load note templates"
    >
      <AdminTable
        columns={[
          {
            key: 'name',
            header: 'Name',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (nt) => (
              <div className="flex items-center gap-3">
                <div className="flex size-8 flex-shrink-0 items-center justify-center rounded-lg bg-info">
                  {nt.icon ? (
                    <EntityIcon
                      icon={nt.icon}
                      className="size-5 object-cover"
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
            key: 'slug',
            header: 'Slug',
            headerAlign: 'center',
            cellAlign: 'center',
            render: (nt) => (
              <code className="rounded bg-secondary px-2 py-1 text-primary">
                {nt.slug}
              </code>
            ),
          },
          {
            key: 'project_types',
            header: 'Project Types',
            headerAlign: 'center',
            cellAlign: 'center',
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
            key: 'tags',
            header: 'Tags',
            headerAlign: 'center',
            cellAlign: 'center',
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
            key: 'sort_order',
            header: 'Sort',
            headerAlign: 'center',
            cellAlign: 'center',
            render: (nt) => (
              <span className="text-secondary">{nt.sort_order ?? 0}</span>
            ),
          },
          {
            key: 'updated',
            header: 'Last Updated',
            headerAlign: 'center',
            cellAlign: 'center',
            render: (nt) => formatRelativeDate(nt.updated_at ?? nt.created_at),
          },
        ]}
        rows={filteredNoteTemplates}
        getRowKey={(nt) => nt.slug}
        getDeleteLabel={(nt) => nt.name}
        onRowClick={(nt) => goToEdit(nt.slug)}
        onDelete={handleDelete}
        isDeleting={deleteMutation.isPending}
        emptyMessage={
          searchQuery
            ? 'No note templates found matching your search.'
            : selectedOrganization
              ? `No note templates in ${selectedOrganization.name} yet.`
              : 'No note templates created yet.'
        }
      />
    </AdminSection>
  )
}
