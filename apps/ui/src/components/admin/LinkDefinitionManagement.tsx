import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Search, Trash2, Link2, AlertCircle } from 'lucide-react'
import { formatRelativeDate } from '@/lib/formatDate'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
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
    onError: (error: any) => {
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

  const handleDelete = (slug: string) => {
    const ld = linkDefinitions.find((l) => l.slug === slug)
    if (
      ld &&
      confirm(
        `Delete link definition "${ld.name}"? This action cannot be undone.`,
      )
    ) {
      deleteMutation.mutate({ orgSlug: ld.organization.slug, slug })
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
          className="bg-[#2A4DD0] text-white hover:bg-blue-700"
        >
          <Plus className="mr-2 h-4 w-4" />
          New Link Definition
        </Button>
      </div>

      {/* Link Definitions Table */}
      <div
        className={`rounded-lg border ${
          isDarkMode
            ? 'border-gray-700 bg-gray-800'
            : 'border-gray-200 bg-white'
        }`}
      >
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead
              className={`border-b ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
            >
              <tr>
                <th
                  className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}
                >
                  Name
                </th>
                <th
                  className={`px-6 py-3 text-center text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}
                >
                  Slug
                </th>
                <th
                  className={`px-6 py-3 text-center text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}
                >
                  Icon
                </th>
                <th
                  className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}
                >
                  URL Template
                </th>
                <th
                  className={`whitespace-nowrap px-6 py-3 text-center text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}
                >
                  Last Updated
                </th>
                <th
                  className={`px-6 py-3 text-right text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}
                >
                  Actions
                </th>
              </tr>
            </thead>
            <tbody
              className={`divide-y ${isDarkMode ? 'divide-gray-700' : 'divide-gray-200'}`}
            >
              {filteredLinkDefinitions.map((ld) => (
                <tr
                  key={ld.slug}
                  onClick={() => goToEdit(ld.slug)}
                  onKeyDown={(e) => {
                    if (e.currentTarget !== e.target) return
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      goToEdit(ld.slug)
                    }
                  }}
                  tabIndex={0}
                  aria-label={`Edit link definition ${ld.name}`}
                  className={`cursor-pointer ${isDarkMode ? 'hover:bg-gray-700/50' : 'hover:bg-gray-50'}`}
                >
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div
                        className={`flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg ${
                          isDarkMode ? 'bg-blue-900/30' : 'bg-blue-50'
                        }`}
                      >
                        <Link2
                          className={`h-4 w-4 ${isDarkMode ? 'text-blue-400' : 'text-blue-600'}`}
                        />
                      </div>
                      <div>
                        <div
                          className={
                            isDarkMode ? 'text-white' : 'text-gray-900'
                          }
                        >
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
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-center text-sm">
                    <code
                      className={`rounded px-2 py-1 ${
                        isDarkMode
                          ? 'bg-gray-700 text-gray-300'
                          : 'bg-gray-100 text-gray-700'
                      }`}
                    >
                      {ld.slug}
                    </code>
                  </td>
                  <td
                    className={`whitespace-nowrap px-6 py-4 text-center text-sm ${
                      isDarkMode ? 'text-gray-300' : 'text-gray-600'
                    }`}
                  >
                    {ld.icon || '--'}
                  </td>
                  <td
                    className={`px-6 py-4 text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}
                  >
                    {ld.url_template ? (
                      <code
                        className={`rounded px-2 py-1 text-xs ${
                          isDarkMode
                            ? 'bg-gray-700 text-gray-300'
                            : 'bg-gray-100 text-gray-700'
                        }`}
                      >
                        {ld.url_template}
                      </code>
                    ) : (
                      <span
                        className={
                          isDarkMode ? 'text-gray-600' : 'text-gray-400'
                        }
                      >
                        --
                      </span>
                    )}
                  </td>
                  <td
                    className={`whitespace-nowrap px-6 py-4 text-center text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}
                  >
                    {formatRelativeDate(ld.updated_at ?? ld.created_at)}
                  </td>
                  <td
                    className="whitespace-nowrap px-6 py-4 text-right"
                    onClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => e.stopPropagation()}
                  >
                    <div className="flex items-center justify-end gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Delete link definition ${ld.name}`}
                        onClick={() => handleDelete(ld.slug)}
                        disabled={deleteMutation.isPending}
                        className={
                          isDarkMode
                            ? 'text-red-400 hover:bg-red-900/20 hover:text-red-300'
                            : 'text-red-600 hover:bg-red-50 hover:text-red-700'
                        }
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {filteredLinkDefinitions.length === 0 && (
            <div
              className={`py-12 text-center ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
            >
              {searchQuery
                ? 'No link definitions found matching your search.'
                : selectedOrganization
                  ? `No link definitions in ${selectedOrganization.name} yet.`
                  : 'No link definitions created yet.'}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
