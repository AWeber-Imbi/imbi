import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '@/api/client'
import { Plus, Search, Trash2, Power, Bot, AlertCircle } from 'lucide-react'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { ServiceAccountForm } from './service-accounts/ServiceAccountForm'
import { ServiceAccountDetail } from './service-accounts/ServiceAccountDetail'
import { useAdminNav } from '@/hooks/useAdminNav'
import {
  listServiceAccounts,
  getServiceAccount,
  createServiceAccount,
  updateServiceAccount,
  deleteServiceAccount,
} from '@/api/endpoints'
import type {
  ServiceAccount,
  ServiceAccountCreate,
  ServiceAccountUpdate,
} from '@/types'

interface ServiceAccountManagementProps {
  isDarkMode: boolean
}

type StatusFilter = 'all' | 'active' | 'inactive'

export function ServiceAccountManagement({
  isDarkMode,
}: ServiceAccountManagementProps) {
  const queryClient = useQueryClient()
  const {
    viewMode,
    slug: selectedAccountSlug,
    goToList,
    goToCreate,
    goToDetail,
    goToEdit,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')

  // Fetch service accounts from dedicated endpoint
  const {
    data: serviceAccounts = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ['serviceAccounts'],
    queryFn: () => listServiceAccounts(),
  })

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: deleteServiceAccount,
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['serviceAccounts'],
      })
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      alert(
        `Failed to delete service account: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  // Create mutation
  const createMutation = useMutation({
    mutationFn: createServiceAccount,
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['serviceAccounts'],
      })
      goToList()
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      console.error('Failed to create service account:', error)
    },
  })

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: ({
      slug,
      data,
    }: {
      slug: string
      data: ServiceAccountUpdate
    }) => updateServiceAccount(slug, data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['serviceAccounts'],
      })
      goToList()
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      console.error('Failed to update service account:', error)
    },
  })

  // Filter service accounts
  const filteredAccounts = serviceAccounts.filter((account: ServiceAccount) => {
    if (statusFilter === 'active' && !account.is_active) return false
    if (statusFilter === 'inactive' && account.is_active) return false

    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      return (
        account.display_name.toLowerCase().includes(query) ||
        account.slug.toLowerCase().includes(query)
      )
    }

    return true
  })

  // Fetch full SA detail (with orgs) when viewing/editing a specific account
  const { data: selectedAccount = null } = useQuery({
    queryKey: ['serviceAccount', selectedAccountSlug],
    queryFn: () => getServiceAccount(selectedAccountSlug!),
    enabled:
      !!selectedAccountSlug && (viewMode === 'detail' || viewMode === 'edit'),
  })

  const handleDelete = (slug: string) => {
    const account = serviceAccounts.find((a: ServiceAccount) => a.slug === slug)
    if (
      confirm(
        `Are you sure you want to delete "${account?.display_name}"? This will revoke all API access and cannot be undone.`,
      )
    ) {
      deleteMutation.mutate(slug)
    }
  }

  const handleViewClick = (account: ServiceAccount) => {
    goToDetail(account.slug)
  }

  const handleEditClick = (account: ServiceAccount) => {
    goToEdit(account.slug)
  }

  const handleSave = (data: ServiceAccountCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate(data)
    } else if (selectedAccount) {
      // Strip org/role fields for update — they're only for creation
      const { organization_slug: _, role_slug: __, ...updateData } = data
      updateMutation.mutate({ slug: selectedAccount.slug, data: updateData })
    }
  }

  const handleCancel = () => {
    goToList()
  }

  const formatDate = (dateString?: string | null) => {
    if (!dateString) return 'Never'
    return new Date(dateString).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  // Loading state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div
          className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
        >
          Loading service accounts...
        </div>
      </div>
    )
  }

  // Error state
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
          <div className="font-medium">Failed to load service accounts</div>
          <div className="mt-1 text-sm">
            {error instanceof Error ? error.message : 'An error occurred'}
          </div>
        </div>
      </div>
    )
  }

  // View mode: Create or Edit
  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <ServiceAccountForm
        account={selectedAccount}
        onSave={handleSave}
        onCancel={handleCancel}
        isDarkMode={isDarkMode}
        isLoading={createMutation.isPending || updateMutation.isPending}
        error={createMutation.error || updateMutation.error}
      />
    )
  }

  // View mode: Detail
  if (viewMode === 'detail' && selectedAccount) {
    return (
      <ServiceAccountDetail
        account={selectedAccount}
        onEdit={() => handleEditClick(selectedAccount)}
        onBack={handleCancel}
        isDarkMode={isDarkMode}
      />
    )
  }

  // View mode: List (default)
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex flex-1 items-center gap-3">
          <div className="relative max-w-md flex-1">
            <Search
              className={`absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${
                isDarkMode ? 'text-gray-400' : 'text-gray-500'
              }`}
            />
            <Input
              placeholder="Search service accounts..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={`pl-10 ${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''}`}
            />
          </div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
            className={`rounded-lg border px-3 py-2 text-sm ${
              isDarkMode
                ? 'border-gray-600 bg-gray-700 text-white'
                : 'border-gray-300 bg-white text-gray-900'
            }`}
          >
            <option value="all">All Status</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </div>
        <Button
          onClick={goToCreate}
          className="bg-[#2A4DD0] text-white hover:bg-blue-700"
        >
          <Plus className="mr-2 h-4 w-4" />
          New Service Account
        </Button>
      </div>

      {/* Service Accounts Table */}
      <div
        className={`overflow-hidden rounded-lg border ${
          isDarkMode
            ? 'border-gray-700 bg-gray-800'
            : 'border-gray-200 bg-white'
        }`}
      >
        <table className="w-full">
          <thead className="border-b border-tertiary bg-secondary">
            <tr>
              <th
                className={`px-4 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Service Account
              </th>
              <th
                className={`px-4 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Slug
              </th>
              <th
                className={`px-4 py-3 text-center text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Status
              </th>
              <th
                className={`px-4 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Last Authenticated
              </th>
              <th
                className={`px-4 py-3 text-right text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Actions
              </th>
            </tr>
          </thead>
          <tbody
            className={
              isDarkMode
                ? 'divide-y divide-gray-700'
                : 'divide-y divide-gray-200'
            }
          >
            {filteredAccounts.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-12 text-center">
                  <div
                    className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
                  >
                    {searchQuery || statusFilter !== 'all'
                      ? 'No service accounts match your filters'
                      : 'No service accounts created yet'}
                  </div>
                  {!searchQuery && statusFilter === 'all' && (
                    <Button
                      onClick={goToCreate}
                      className="mt-4 bg-[#2A4DD0] text-white hover:bg-blue-700"
                    >
                      Create Your First Service Account
                    </Button>
                  )}
                </td>
              </tr>
            ) : (
              filteredAccounts.map((account: ServiceAccount) => (
                <tr
                  key={account.slug}
                  onClick={() => handleViewClick(account)}
                  className={`cursor-pointer ${isDarkMode ? 'hover:bg-gray-700' : 'hover:bg-gray-50'} ${
                    !account.is_active ? 'opacity-60' : ''
                  }`}
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <div
                        className={`flex h-8 w-8 items-center justify-center rounded-full ${
                          isDarkMode ? 'bg-purple-900/30' : 'bg-purple-100'
                        }`}
                      >
                        <Bot
                          className={`h-4 w-4 ${isDarkMode ? 'text-purple-400' : 'text-purple-600'}`}
                        />
                      </div>
                      <div>
                        <div
                          className={`text-sm font-medium ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
                        >
                          {account.display_name}
                        </div>
                        {account.description && (
                          <div
                            className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
                          >
                            {account.description}
                          </div>
                        )}
                      </div>
                    </div>
                  </td>
                  <td
                    className={`px-4 py-3 text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                  >
                    <code
                      className={`rounded px-2 py-0.5 text-xs ${
                        isDarkMode
                          ? 'bg-gray-700 text-gray-300'
                          : 'bg-gray-100 text-gray-600'
                      }`}
                    >
                      {account.slug}
                    </code>
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span
                      className={`inline-flex items-center gap-1.5 rounded px-2 py-1 text-xs font-medium ${
                        account.is_active
                          ? isDarkMode
                            ? 'bg-green-900/30 text-green-400'
                            : 'bg-green-100 text-green-700'
                          : isDarkMode
                            ? 'bg-gray-700 text-gray-400'
                            : 'bg-gray-100 text-gray-600'
                      }`}
                    >
                      <Power className="h-3 w-3" />
                      {account.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td
                    className={`px-4 py-3 text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                  >
                    {formatDate(account.last_authenticated)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          handleDelete(account.slug)
                        }}
                        disabled={deleteMutation.isPending}
                        className={`rounded p-1.5 ${
                          isDarkMode
                            ? 'text-red-400 hover:bg-gray-700 hover:text-red-300'
                            : 'text-red-600 hover:bg-gray-100 hover:text-red-700'
                        }`}
                        title="Delete"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Summary */}
      {filteredAccounts.length > 0 && (
        <div
          className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
        >
          Showing {filteredAccounts.length} of {serviceAccounts.length} service
          account(s)
        </div>
      )}
    </div>
  )
}
