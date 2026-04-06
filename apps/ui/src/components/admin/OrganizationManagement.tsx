import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '@/api/client'
import { Plus, Search, Trash2, Building2, AlertCircle } from 'lucide-react'
import { formatRelativeDate } from '@/lib/formatDate'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { OrganizationForm } from './organizations/OrganizationForm'
import { OrganizationDetail } from './organizations/OrganizationDetail'
import { useAdminNav } from '@/hooks/useAdminNav'
import {
  listOrganizations,
  deleteOrganization,
  createOrganization,
  updateOrganization,
} from '@/api/endpoints'
import type { OrganizationCreate } from '@/types'

interface OrganizationManagementProps {
  isDarkMode: boolean
}

export function OrganizationManagement({
  isDarkMode,
}: OrganizationManagementProps) {
  const queryClient = useQueryClient()
  const {
    viewMode,
    slug: selectedOrgSlug,
    goToList,
    goToCreate,
    goToDetail,
    goToEdit,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')

  const {
    data: organizations = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ['organizations'],
    queryFn: listOrganizations,
  })

  const canDeleteOrg = (
    slug: string,
  ): { allowed: boolean; reason?: string } => {
    if (organizations.length <= 1) {
      return { allowed: false, reason: 'Cannot delete the only organization' }
    }
    const org = organizations.find((o) => o.slug === slug)
    const teamCount = org?.relationships?.teams?.count ?? 0
    if (teamCount > 0) {
      return {
        allowed: false,
        reason: `Has ${teamCount} team(s)`,
      }
    }
    return { allowed: true }
  }

  const createMutation = useMutation({
    mutationFn: createOrganization,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['organizations'] })
      goToList()
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ slug, org }: { slug: string; org: OrganizationCreate }) =>
      updateOrganization(slug, org),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['organizations'] })
      goToList()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: deleteOrganization,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['organizations'] })
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      alert(
        `Failed to delete organization: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  const filteredOrgs = organizations.filter((org) => {
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      return (
        org.name.toLowerCase().includes(query) ||
        org.slug.toLowerCase().includes(query) ||
        (org.description?.toLowerCase().includes(query) ?? false)
      )
    }
    return true
  })

  const selectedOrg = useMemo(
    () => organizations.find((o) => o.slug === selectedOrgSlug) || null,
    [organizations, selectedOrgSlug],
  )

  const handleDelete = (slug: string) => {
    const check = canDeleteOrg(slug)
    if (!check.allowed) return

    const org = organizations.find((o) => o.slug === slug)
    if (
      org &&
      confirm(
        `Delete organization "${org.name}"? This action cannot be undone.`,
      )
    ) {
      deleteMutation.mutate(slug)
    }
  }

  const handleSave = (orgData: OrganizationCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate(orgData)
    } else if (selectedOrgSlug) {
      updateMutation.mutate({ slug: selectedOrgSlug, org: orgData })
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
          Loading organizations...
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
          <div className="font-medium">Failed to load organizations</div>
          <div className="mt-1 text-sm">
            {error instanceof Error ? error.message : 'An error occurred'}
          </div>
        </div>
      </div>
    )
  }

  // Guard for invalid organization slug in URL
  if (
    (viewMode === 'edit' || viewMode === 'detail') &&
    !!selectedOrgSlug &&
    !selectedOrg
  ) {
    return (
      <div
        className={`rounded-lg border p-4 ${isDarkMode ? 'border-gray-700 text-gray-300' : 'border-gray-200 text-gray-700'}`}
      >
        Organization not found. It may have been deleted.
      </div>
    )
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <OrganizationForm
        organization={selectedOrg}
        onSave={handleSave}
        onCancel={handleCancel}
        isDarkMode={isDarkMode}
        isLoading={createMutation.isPending || updateMutation.isPending}
        error={createMutation.error || updateMutation.error}
      />
    )
  }

  if (viewMode === 'detail' && selectedOrg) {
    return (
      <OrganizationDetail
        organization={selectedOrg}
        onEdit={() => goToEdit(selectedOrg.slug)}
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
              placeholder="Search organizations..."
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
          New Organization
        </Button>
      </div>

      {/* Organizations Table */}
      <div
        className={`rounded-lg border ${
          isDarkMode
            ? 'border-gray-700 bg-gray-800'
            : 'border-gray-200 bg-white'
        }`}
      >
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="border-b border-tertiary bg-secondary">
              <tr>
                <th
                  className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}
                >
                  Organization
                </th>
                <th
                  className={`px-6 py-3 text-center text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}
                >
                  Slug
                </th>
                <th
                  className={`px-6 py-3 text-right text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}
                >
                  Teams
                </th>
                <th
                  className={`px-6 py-3 text-right text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}
                >
                  Members
                </th>
                <th
                  className={`px-6 py-3 text-right text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}
                >
                  Projects
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
              {filteredOrgs.map((org) => {
                const deleteCheck = canDeleteOrg(org.slug)
                return (
                  <tr
                    key={org.slug}
                    onClick={() => goToDetail(org.slug)}
                    className={`cursor-pointer ${isDarkMode ? 'hover:bg-gray-700/50' : 'hover:bg-gray-50'}`}
                  >
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <div
                          className={`flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg ${
                            isDarkMode ? 'bg-blue-900/30' : 'bg-blue-50'
                          }`}
                        >
                          {org.icon ? (
                            <img
                              src={org.icon}
                              alt=""
                              className="rounded h-5 w-5 object-cover"
                            />
                          ) : (
                            <Building2
                              className={`h-4 w-4 ${isDarkMode ? 'text-blue-400' : 'text-blue-600'}`}
                            />
                          )}
                        </div>
                        <div>
                          <div
                            className={
                              isDarkMode ? 'text-white' : 'text-gray-900'
                            }
                          >
                            {org.name}
                          </div>
                          {org.description && (
                            <div
                              className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
                            >
                              {org.description}
                            </div>
                          )}
                        </div>
                      </div>
                    </td>
                    <td
                      className={`whitespace-nowrap px-6 py-4 text-center text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}
                    >
                      <code
                        className={`rounded px-2 py-1 ${
                          isDarkMode
                            ? 'bg-gray-700 text-gray-300'
                            : 'bg-gray-100 text-gray-700'
                        }`}
                      >
                        {org.slug}
                      </code>
                    </td>
                    <td
                      className={`whitespace-nowrap px-6 py-4 text-right text-sm ${
                        (org.relationships?.teams?.count ?? 0) === 0
                          ? isDarkMode
                            ? 'text-gray-600'
                            : 'text-gray-400'
                          : isDarkMode
                            ? 'text-gray-300'
                            : 'text-gray-600'
                      }`}
                    >
                      {org.relationships?.teams?.count ?? 0}
                    </td>
                    <td
                      className={`whitespace-nowrap px-6 py-4 text-right text-sm ${
                        (org.relationships?.members?.count ?? 0) === 0
                          ? isDarkMode
                            ? 'text-gray-600'
                            : 'text-gray-400'
                          : isDarkMode
                            ? 'text-gray-300'
                            : 'text-gray-600'
                      }`}
                    >
                      {org.relationships?.members?.count ?? 0}
                    </td>
                    <td
                      className={`whitespace-nowrap px-6 py-4 text-right text-sm ${
                        (org.relationships?.projects?.count ?? 0) === 0
                          ? isDarkMode
                            ? 'text-gray-600'
                            : 'text-gray-400'
                          : isDarkMode
                            ? 'text-gray-300'
                            : 'text-gray-600'
                      }`}
                    >
                      {org.relationships?.projects?.count ?? 0}
                    </td>
                    <td
                      className={`whitespace-nowrap px-6 py-4 text-center text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}
                    >
                      {formatRelativeDate(org.updated_at ?? org.created_at)}
                    </td>
                    <td
                      className="whitespace-nowrap px-6 py-4 text-right"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <div className="flex items-center justify-end gap-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleDelete(org.slug)}
                          disabled={
                            !deleteCheck.allowed || deleteMutation.isPending
                          }
                          title={deleteCheck.reason}
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
                )
              })}
            </tbody>
          </table>

          {filteredOrgs.length === 0 && (
            <div
              className={`py-12 text-center ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
            >
              {searchQuery
                ? 'No organizations match your search.'
                : 'No organizations created yet.'}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
