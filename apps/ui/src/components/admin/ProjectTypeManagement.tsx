import { useState, useMemo } from 'react'
import { Layers } from 'lucide-react'
import { formatRelativeDate } from '@/lib/formatDate'
import { EntityIcon } from '@/components/ui/entity-icon'
import { AdminTable } from '@/components/ui/admin-table'
import type { CanDeleteResult } from '@/components/ui/admin-table'
import { AdminSection } from './AdminSection'
import { ProjectTypeForm } from './project-types/ProjectTypeForm'
import { ProjectTypeDetail } from './project-types/ProjectTypeDetail'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAdminNav } from '@/hooks/useAdminNav'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import {
  listProjectTypes,
  deleteProjectType,
  createProjectType,
  updateProjectType,
} from '@/api/endpoints'
import { buildDiffPatch } from '@/lib/json-patch'
import type { ProjectType, ProjectTypeCreate, PatchOperation } from '@/types'

export function ProjectTypeManagement() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug
  const {
    viewMode,
    slug: selectedPtSlug,
    goToList,
    goToCreate,
    goToEdit,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')

  const {
    items: projectTypes,
    isLoading,
    error,
    createMutation,
    updateMutation,
    deleteMutation,
  } = useAdminCrud<
    ProjectType,
    { orgSlug: string; pt: ProjectTypeCreate },
    { orgSlug: string; slug: string; operations: PatchOperation[] },
    { orgSlug: string; slug: string }
  >({
    queryKey: ['projectTypes', orgSlug],
    listFn: orgSlug ? (signal) => listProjectTypes(orgSlug, signal) : null,
    createFn: ({ orgSlug, pt }) => createProjectType(orgSlug, pt),
    updateFn: ({ orgSlug, slug, operations }) =>
      updateProjectType(orgSlug, slug, operations),
    deleteFn: ({ orgSlug, slug }) => deleteProjectType(orgSlug, slug),
    onMutationSuccess: goToList,
    deleteErrorLabel: 'project type',
  })

  const filteredProjectTypes = projectTypes.filter((pt) => {
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      return (
        pt.name.toLowerCase().includes(query) ||
        pt.slug.toLowerCase().includes(query) ||
        (pt.description?.toLowerCase().includes(query) ?? false)
      )
    }
    return true
  })

  const selectedProjectType = useMemo(
    () => projectTypes.find((pt) => pt.slug === selectedPtSlug) || null,
    [projectTypes, selectedPtSlug],
  )

  const handleDelete = (pt: ProjectType) => {
    deleteMutation.mutate({ orgSlug: pt.organization.slug, slug: pt.slug })
  }

  const canDeleteProjectType = (pt: ProjectType): CanDeleteResult => {
    const projects = pt.relationships?.projects?.count ?? 0
    if (projects === 0) return { allowed: true }
    return {
      allowed: false,
      blockedBy: [{ count: projects, label: 'project', href: '/projects' }],
    }
  }

  const handleSave = (formOrgSlug: string, ptData: ProjectTypeCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate({ orgSlug: formOrgSlug, pt: ptData })
    } else if (selectedPtSlug && selectedProjectType) {
      const operations = buildDiffPatch(
        selectedProjectType as unknown as Record<string, unknown>,
        ptData as unknown as Record<string, unknown>,
        { fields: Object.keys(ptData) },
      )
      if (operations.length === 0) {
        goToList()
        return
      }
      updateMutation.mutate({
        orgSlug: selectedProjectType.organization.slug || formOrgSlug,
        slug: selectedPtSlug,
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
        Select an organization to manage project types.
      </div>
    )
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <ProjectTypeForm
        projectType={selectedProjectType}
        onSave={handleSave}
        onCancel={handleCancel}
        isLoading={createMutation.isPending || updateMutation.isPending}
        error={createMutation.error || updateMutation.error}
      />
    )
  }

  if (viewMode === 'detail' && selectedProjectType) {
    return (
      <ProjectTypeDetail
        projectType={selectedProjectType}
        onEdit={() => goToEdit(selectedProjectType.slug)}
        onBack={handleCancel}
      />
    )
  }

  return (
    <AdminSection
      searchPlaceholder="Search project types..."
      search={searchQuery}
      onSearchChange={setSearchQuery}
      createLabel="New Project Type"
      onCreate={goToCreate}
      isLoading={isLoading}
      loadingLabel="Loading project types..."
      error={error}
      errorTitle="Failed to load project types"
    >
      <AdminTable
        columns={[
          {
            key: 'name',
            header: 'Project Type',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (pt) => (
              <div className="flex items-center gap-3">
                <div
                  className={
                    'flex size-8 flex-shrink-0 items-center justify-center rounded-lg bg-purple-50 dark:bg-purple-900/30'
                  }
                >
                  {pt.icon ? (
                    <EntityIcon
                      icon={pt.icon}
                      className="size-5 rounded object-cover"
                    />
                  ) : (
                    <Layers className="h-4 w-4 text-purple-600 dark:text-purple-400" />
                  )}
                </div>
                <div>
                  <div className="text-primary">{pt.name}</div>
                  {pt.description && (
                    <div className="text-sm text-tertiary">
                      {pt.description}
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
            render: (pt) => (
              <code className="rounded bg-secondary px-2 py-1 text-primary">
                {pt.slug}
              </code>
            ),
          },
          {
            key: 'projects',
            header: 'Projects',
            headerAlign: 'right',
            cellAlign: 'right',
            render: (pt) => (
              <span
                className={
                  (pt.relationships?.projects?.count ?? 0) === 0
                    ? 'text-tertiary'
                    : 'text-secondary'
                }
              >
                {pt.relationships?.projects?.count ?? 0}
              </span>
            ),
          },
          {
            key: 'updated',
            header: 'Last Updated',
            headerAlign: 'center',
            cellAlign: 'center',
            render: (pt) => formatRelativeDate(pt.updated_at ?? pt.created_at),
          },
        ]}
        rows={filteredProjectTypes}
        getRowKey={(pt) => pt.slug}
        getDeleteLabel={(pt) => pt.name}
        onRowClick={(pt) => goToEdit(pt.slug)}
        onDelete={handleDelete}
        canDelete={canDeleteProjectType}
        isDeleting={deleteMutation.isPending}
        emptyMessage={
          searchQuery
            ? 'No project types found matching your search.'
            : selectedOrganization
              ? `No project types in ${selectedOrganization.name} yet.`
              : 'No project types created yet.'
        }
      />
    </AdminSection>
  )
}
