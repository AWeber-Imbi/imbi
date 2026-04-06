import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '@/api/client'
import { Plus, Search, Trash2, Globe, AlertCircle } from 'lucide-react'
import { formatRelativeDate } from '@/lib/formatDate'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { EnvironmentForm } from './environments/EnvironmentForm'
import { EnvironmentDetail } from './environments/EnvironmentDetail'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAdminNav } from '@/hooks/useAdminNav'
import {
  listEnvironments,
  deleteEnvironment,
  createEnvironment,
  updateEnvironment,
} from '@/api/endpoints'
import type { EnvironmentCreate } from '@/types'

interface EnvironmentManagementProps {
  isDarkMode: boolean
}

export function EnvironmentManagement({
  isDarkMode,
}: EnvironmentManagementProps) {
  const queryClient = useQueryClient()
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug
  const {
    viewMode,
    slug: selectedEnvSlug,
    goToList,
    goToCreate,
    goToDetail,
    goToEdit,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')

  const {
    data: environments = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ['environments', orgSlug],
    queryFn: () => listEnvironments(orgSlug!),
    enabled: !!orgSlug,
  })

  const createMutation = useMutation({
    mutationFn: ({
      orgSlug,
      env,
    }: {
      orgSlug: string
      env: EnvironmentCreate
    }) => createEnvironment(orgSlug, env),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['environments', orgSlug] })
      goToList()
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({
      orgSlug,
      slug,
      env,
    }: {
      orgSlug: string
      slug: string
      env: EnvironmentCreate
    }) => updateEnvironment(orgSlug, slug, env),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['environments', orgSlug] })
      goToList()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: ({ orgSlug, slug }: { orgSlug: string; slug: string }) =>
      deleteEnvironment(orgSlug, slug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['environments', orgSlug] })
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      alert(
        `Failed to delete environment: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  const filteredEnvironments = environments.filter((env) => {
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      return (
        env.name.toLowerCase().includes(query) ||
        env.slug.toLowerCase().includes(query) ||
        (env.description?.toLowerCase().includes(query) ?? false)
      )
    }
    return true
  })

  const selectedEnvironment = useMemo(
    () => environments.find((e) => e.slug === selectedEnvSlug) || null,
    [environments, selectedEnvSlug],
  )

  const handleDelete = (slug: string) => {
    const env = environments.find((e) => e.slug === slug)
    if (
      env &&
      confirm(`Delete environment "${env.name}"? This action cannot be undone.`)
    ) {
      deleteMutation.mutate({ orgSlug: env.organization.slug, slug })
    }
  }

  const handleSave = (formOrgSlug: string, envData: EnvironmentCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate({ orgSlug: formOrgSlug, env: envData })
    } else if (selectedEnvSlug) {
      updateMutation.mutate({
        orgSlug: selectedEnvironment?.organization.slug || formOrgSlug,
        slug: selectedEnvSlug,
        env: envData,
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
          Loading environments...
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
          <div className="font-medium">Failed to load environments</div>
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
        Select an organization to manage environments.
      </div>
    )
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <EnvironmentForm
        environment={selectedEnvironment}
        onSave={handleSave}
        onCancel={handleCancel}
        isDarkMode={isDarkMode}
        isLoading={createMutation.isPending || updateMutation.isPending}
        error={createMutation.error || updateMutation.error}
      />
    )
  }

  if (viewMode === 'detail' && selectedEnvironment) {
    return (
      <EnvironmentDetail
        environment={selectedEnvironment}
        onEdit={() => goToEdit(selectedEnvironment.slug)}
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
              placeholder="Search environments..."
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
          New Environment
        </Button>
      </div>

      {/* Environments Table */}
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
                  Environment
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
                  Order
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
              {filteredEnvironments.map((env) => (
                <tr
                  key={env.slug}
                  onClick={() => goToDetail(env.slug)}
                  onKeyDown={(e) => {
                    if (e.currentTarget !== e.target) return
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      goToDetail(env.slug)
                    }
                  }}
                  tabIndex={0}
                  aria-label={`View environment ${env.name}`}
                  className={`cursor-pointer ${isDarkMode ? 'hover:bg-gray-700/50' : 'hover:bg-gray-50'}`}
                >
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div
                        className={`flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg ${
                          isDarkMode ? 'bg-green-900/30' : 'bg-green-50'
                        }`}
                      >
                        {env.icon ? (
                          <img
                            src={env.icon}
                            alt=""
                            className="rounded h-5 w-5 object-cover"
                          />
                        ) : (
                          <Globe
                            className={`h-4 w-4 ${isDarkMode ? 'text-green-400' : 'text-green-600'}`}
                          />
                        )}
                      </div>
                      <div>
                        <div
                          className={
                            isDarkMode ? 'text-white' : 'text-gray-900'
                          }
                        >
                          {env.name}
                        </div>
                        {env.description && (
                          <div
                            className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
                          >
                            {env.description}
                          </div>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-center text-sm">
                    {env.label_color ? (
                      <span
                        className="rounded px-2 py-1 text-xs font-medium"
                        style={{
                          backgroundColor: env.label_color + '20',
                          color: env.label_color,
                          border: `1px solid ${env.label_color}40`,
                        }}
                      >
                        {env.slug}
                      </span>
                    ) : (
                      <code
                        className={`rounded px-2 py-1 ${
                          isDarkMode
                            ? 'bg-gray-700 text-gray-300'
                            : 'bg-gray-100 text-gray-700'
                        }`}
                      >
                        {env.slug}
                      </code>
                    )}
                  </td>
                  <td
                    className={`whitespace-nowrap px-6 py-4 text-center text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}
                  >
                    {env.sort_order ?? 0}
                  </td>
                  <td
                    className={`whitespace-nowrap px-6 py-4 text-right text-sm ${
                      (env.relationships?.projects?.count ?? 0) === 0
                        ? isDarkMode
                          ? 'text-gray-600'
                          : 'text-gray-400'
                        : isDarkMode
                          ? 'text-gray-300'
                          : 'text-gray-600'
                    }`}
                  >
                    {env.relationships?.projects?.count ?? 0}
                  </td>
                  <td
                    className={`whitespace-nowrap px-6 py-4 text-center text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}
                  >
                    {formatRelativeDate(env.updated_at ?? env.created_at)}
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
                        aria-label={`Delete environment ${env.name}`}
                        onClick={() => handleDelete(env.slug)}
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

          {filteredEnvironments.length === 0 && (
            <div
              className={`py-12 text-center ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
            >
              {searchQuery
                ? 'No environments found matching your search.'
                : selectedOrganization
                  ? `No environments in ${selectedOrganization.name} yet.`
                  : 'No environments created yet.'}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
