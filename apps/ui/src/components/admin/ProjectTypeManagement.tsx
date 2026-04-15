import { useState, useMemo } from 'react'
import { AdminTable } from '@/components/ui/admin-table'
import type { CanDeleteResult } from '@/components/ui/admin-table'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '@/api/client'
import { Plus, Search, Layers, AlertCircle } from 'lucide-react'
import { formatRelativeDate } from '@/lib/formatDate'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { EntityIcon } from '@/components/ui/entity-icon'
import { ProjectTypeForm } from './project-types/ProjectTypeForm'
import { ProjectTypeDetail } from './project-types/ProjectTypeDetail'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAdminNav } from '@/hooks/useAdminNav'
import {
  listProjectTypes,
  deleteProjectType,
  createProjectType,
  updateProjectType,
} from '@/api/endpoints'
import type { ProjectTypeCreate } from '@/types'

interface ProjectTypeManagementProps {
  isDarkMode: boolean
}

export function ProjectTypeManagement({
  isDarkMode,
}: ProjectTypeManagementProps) {
  const queryClient = useQueryClient()
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
    data: projectTypes = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ['projectTypes', orgSlug],
    queryFn: () => listProjectTypes(orgSlug!),
    enabled: !!orgSlug,
  })

  const createMutation = useMutation({
    mutationFn: ({ orgSlug, pt }: { orgSlug: string; pt: ProjectTypeCreate }) =>
      createProjectType(orgSlug, pt),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projectTypes', orgSlug] })
      goToList()
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({
      orgSlug,
      slug,
      pt,
    }: {
      orgSlug: string
      slug: string
      pt: ProjectTypeCreate
    }) => updateProjectType(orgSlug, slug, pt),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projectTypes', orgSlug] })
      goToList()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: ({ orgSlug, slug }: { orgSlug: string; slug: string }) =>
      deleteProjectType(orgSlug, slug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projectTypes', orgSlug] })
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      alert(
        `Failed to delete project type: ${error.response?.data?.detail || error.message}`,
      )
    },
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

  const handleDelete = (pt: (typeof projectTypes)[number]) => {
    deleteMutation.mutate({ orgSlug: pt.organization.slug, slug: pt.slug })
  }

  const canDeleteProjectType = (
    pt: (typeof projectTypes)[number],
  ): CanDeleteResult => {
    const projects = pt.relationships?.projects?.count ?? 0
    if (projects === 0) return { allowed: true }
    return { allowed: false, reason: `Has ${projects} project(s)` }
  }

  const handleSave = (formOrgSlug: string, ptData: ProjectTypeCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate({ orgSlug: formOrgSlug, pt: ptData })
    } else if (selectedPtSlug) {
      updateMutation.mutate({
        orgSlug: selectedProjectType?.organization.slug || formOrgSlug,
        slug: selectedPtSlug,
        pt: ptData,
      })
    }
  }

  const handleCancel = () => {
    goToList()
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div
          className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
        >
          Loading project types...
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div
        className={`flex items-center gap-3 rounded-lg border p-4 ${
          isDarkMode
            ? 'border-red-700 bg-red-900/20 text-red-400'
            : 'border-red-200 bg-red-50 text-red-700'
        }`}
      >
        <AlertCircle className="h-5 w-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load project types</div>
          <div className="mt-1 text-sm">
            {error instanceof Error ? error.message : 'An error occurred'}
          </div>
        </div>
      </div>
    )
  }

  if (!orgSlug) {
    return (
      <div
        className={`py-12 text-center ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
      >
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
        isDarkMode={isDarkMode}
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
        isDarkMode={isDarkMode}
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
              className={`absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${
                isDarkMode ? 'text-gray-400' : 'text-gray-500'
              }`}
            />
            <Input
              placeholder="Search project types..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={`pl-10 ${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''}`}
            />
          </div>
        </div>
        <Button
          onClick={goToCreate}
          className="bg-amber-border text-white hover:bg-amber-border-strong"
        >
          <Plus className="mr-2 h-4 w-4" />
          New Project Type
        </Button>
      </div>

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
                  className={`flex size-8 flex-shrink-0 items-center justify-center rounded-lg ${isDarkMode ? 'bg-purple-900/30' : 'bg-purple-50'}`}
                >
                  {pt.icon ? (
                    <EntityIcon
                      icon={pt.icon}
                      className="size-5 rounded object-cover"
                    />
                  ) : (
                    <Layers
                      className={`h-4 w-4 ${isDarkMode ? 'text-purple-400' : 'text-purple-600'}`}
                    />
                  )}
                </div>
                <div>
                  <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
                    {pt.name}
                  </div>
                  {pt.description && (
                    <div
                      className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
                    >
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
              <code
                className={`rounded px-2 py-1 ${isDarkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-700'}`}
              >
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
                    ? isDarkMode
                      ? 'text-gray-600'
                      : 'text-gray-400'
                    : isDarkMode
                      ? 'text-gray-300'
                      : 'text-gray-600'
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
    </div>
  )
}
