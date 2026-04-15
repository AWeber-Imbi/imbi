import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '@/api/client'
import { Plus, Search, Link2, AlertCircle } from 'lucide-react'
import { getIcon } from '@/lib/icons'
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

interface LinkDefinitionManagementProps {
  isDarkMode: boolean
}

export function LinkDefinitionManagement({
  isDarkMode,
}: LinkDefinitionManagementProps) {
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
    return { allowed: false, reason: `Has ${projects} project(s)` }
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
        <div
          className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
        >
          Loading link definitions...
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
      <div
        className={`py-12 text-center ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
      >
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
        isDarkMode={isDarkMode}
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
        isDarkMode={isDarkMode}
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
              className={`absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${
                isDarkMode ? 'text-gray-400' : 'text-gray-500'
              }`}
            />
            <Input
              placeholder="Search link definitions..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={`pl-10 ${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''}`}
            />
          </div>
        </div>
        <Button
          onClick={goToCreate}
          className="bg-amber-border-strong text-white hover:brightness-125"
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
                  className={`flex size-8 flex-shrink-0 items-center justify-center rounded-lg ${isDarkMode ? 'bg-blue-900/30' : 'bg-blue-50'}`}
                >
                  <Link2
                    className={`h-4 w-4 ${isDarkMode ? 'text-blue-400' : 'text-blue-600'}`}
                  />
                </div>
                <div>
                  <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
                    {ld.name}
                  </div>
                  {ld.description && (
                    <div
                      className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
                    >
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
              <code
                className={`rounded px-2 py-1 ${isDarkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-700'}`}
              >
                {ld.slug}
              </code>
            ),
          },
          {
            key: 'icon',
            header: 'Icon',
            headerAlign: 'center',
            cellAlign: 'center',
            render: (ld) => {
              if (!ld.icon)
                return (
                  <span
                    className={isDarkMode ? 'text-gray-600' : 'text-gray-400'}
                  >
                    --
                  </span>
                )
              const Icon = getIcon(ld.icon, null)
              return Icon ? (
                <Icon
                  className={`mx-auto h-5 w-5 ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}
                />
              ) : (
                <span
                  className={`text-xs ${isDarkMode ? 'text-red-400' : 'text-red-600'}`}
                >
                  {ld.icon}
                </span>
              )
            },
          },
          {
            key: 'url_template',
            header: 'URL Template',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (ld) =>
              ld.url_template ? (
                <code
                  className={`rounded px-2 py-1 text-xs ${isDarkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-700'}`}
                >
                  {ld.url_template}
                </code>
              ) : (
                <span
                  className={isDarkMode ? 'text-gray-600' : 'text-gray-400'}
                >
                  --
                </span>
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
                    ? isDarkMode
                      ? 'text-gray-600'
                      : 'text-gray-400'
                    : isDarkMode
                      ? 'text-gray-300'
                      : 'text-gray-600'
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
