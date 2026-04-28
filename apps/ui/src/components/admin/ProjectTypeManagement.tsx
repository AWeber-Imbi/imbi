import { useMemo, useState } from 'react'

import { Layers } from 'lucide-react'

import {
  createProjectType,
  deleteProjectType,
  listProjectTypes,
  updateProjectType,
} from '@/api/endpoints'
import { AdminTable } from '@/components/ui/admin-table'
import type { CanDeleteResult } from '@/components/ui/admin-table'
import { EntityIcon } from '@/components/ui/entity-icon'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import { useAdminNav } from '@/hooks/useAdminNav'
import { formatRelativeDate } from '@/lib/formatDate'
import { buildDiffPatch } from '@/lib/json-patch'
import type { PatchOperation, ProjectType, ProjectTypeCreate } from '@/types'

import { AdminSection } from './AdminSection'
import { ProjectTypeDetail } from './project-types/ProjectTypeDetail'
import { ProjectTypeForm } from './project-types/ProjectTypeForm'

export function ProjectTypeManagement() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug
  const {
    goToCreate,
    goToEdit,
    goToList,
    slug: selectedPtSlug,
    viewMode,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')

  const {
    createMutation,
    deleteMutation,
    error,
    isLoading,
    items: projectTypes,
    updateMutation,
  } = useAdminCrud<
    ProjectType,
    { orgSlug: string; pt: ProjectTypeCreate },
    { operations: PatchOperation[]; orgSlug: string; slug: string },
    { orgSlug: string; slug: string }
  >({
    createFn: ({ orgSlug, pt }) => createProjectType(orgSlug, pt),
    deleteErrorLabel: 'project type',
    deleteFn: ({ orgSlug, slug }) => deleteProjectType(orgSlug, slug),
    listFn: orgSlug ? (signal) => listProjectTypes(orgSlug, signal) : null,
    onMutationSuccess: goToList,
    queryKey: ['projectTypes', orgSlug],
    updateFn: ({ operations, orgSlug, slug }) =>
      updateProjectType(orgSlug, slug, operations),
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
      blockedBy: [{ count: projects, href: '/projects', label: 'project' }],
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
        operations,
        orgSlug: selectedProjectType.organization.slug || formOrgSlug,
        slug: selectedPtSlug,
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
        error={createMutation.error || updateMutation.error}
        isLoading={createMutation.isPending || updateMutation.isPending}
        onCancel={handleCancel}
        onSave={handleSave}
        projectType={selectedProjectType}
      />
    )
  }

  if (viewMode === 'detail' && selectedProjectType) {
    return (
      <ProjectTypeDetail
        onBack={handleCancel}
        onEdit={() => goToEdit(selectedProjectType.slug)}
        projectType={selectedProjectType}
      />
    )
  }

  return (
    <AdminSection
      createLabel="New Project Type"
      error={error}
      errorTitle="Failed to load project types"
      isLoading={isLoading}
      loadingLabel="Loading project types..."
      onCreate={goToCreate}
      onSearchChange={setSearchQuery}
      search={searchQuery}
      searchPlaceholder="Search project types..."
    >
      <AdminTable
        canDelete={canDeleteProjectType}
        columns={[
          {
            cellAlign: 'left',
            header: 'Project Type',
            headerAlign: 'left',
            key: 'name',
            render: (pt) => (
              <div className="flex items-center gap-3">
                <div
                  className={
                    'flex size-8 flex-shrink-0 items-center justify-center rounded-lg bg-purple-50 dark:bg-purple-900/30'
                  }
                >
                  {pt.icon ? (
                    <EntityIcon
                      className="size-5 rounded object-cover"
                      icon={pt.icon}
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
            cellAlign: 'center',
            header: 'Slug',
            headerAlign: 'center',
            key: 'slug',
            render: (pt) => (
              <code className="rounded bg-secondary px-2 py-1 text-primary">
                {pt.slug}
              </code>
            ),
          },
          {
            cellAlign: 'right',
            header: 'Projects',
            headerAlign: 'right',
            key: 'projects',
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
            cellAlign: 'center',
            header: 'Last Updated',
            headerAlign: 'center',
            key: 'updated',
            render: (pt) => formatRelativeDate(pt.updated_at ?? pt.created_at),
          },
        ]}
        emptyMessage={
          searchQuery
            ? 'No project types found matching your search.'
            : selectedOrganization
              ? `No project types in ${selectedOrganization.name} yet.`
              : 'No project types created yet.'
        }
        getDeleteLabel={(pt) => pt.name}
        getRowKey={(pt) => pt.slug}
        isDeleting={deleteMutation.isPending}
        onDelete={handleDelete}
        onRowClick={(pt) => goToEdit(pt.slug)}
        rows={filteredProjectTypes}
      />
    </AdminSection>
  )
}
