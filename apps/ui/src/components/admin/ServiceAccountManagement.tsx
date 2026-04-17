import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '@/api/client'
import { Plus, Search, Power, Bot, AlertCircle } from 'lucide-react'
import { Button } from '../ui/button'
import { Badge } from '../ui/badge'
import { Input } from '../ui/input'
import { AdminTable } from '@/components/ui/admin-table'
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

type StatusFilter = 'all' | 'active' | 'inactive'

export function ServiceAccountManagement() {
  const queryClient = useQueryClient()
  const {
    viewMode,
    slug: selectedAccountSlug,
    goToList,
    goToCreate,
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

  const handleDelete = (account: ServiceAccount) => {
    deleteMutation.mutate(account.slug)
  }

  const handleViewClick = (account: ServiceAccount) => {
    goToEdit(account.slug)
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
        <div className={'text-sm text-secondary'}>
          Loading service accounts...
        </div>
      </div>
    )
  }

  // Error state
  if (error) {
    return (
      <div
        className={`flex items-center gap-3 rounded-lg border p-4 ${'border-danger bg-danger text-danger'}`}
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
              className={`absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${'text-tertiary'}`}
            />
            <Input
              placeholder="Search service accounts..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={'pl-10'}
            />
          </div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
            className={`rounded-lg border px-3 py-2 text-sm ${'border-input bg-background text-foreground'}`}
          >
            <option value="all">All Status</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </div>
        <Button
          onClick={goToCreate}
          className="bg-action text-action-foreground hover:bg-action-hover"
        >
          <Plus className="mr-2 h-4 w-4" />
          New Service Account
        </Button>
      </div>

      {/* Service Accounts Table */}
      <AdminTable
        columns={[
          {
            key: 'name',
            header: 'Service Account',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (account) => (
              <div className="flex items-center gap-3">
                <div
                  className={
                    'flex size-8 items-center justify-center rounded-full bg-purple-100 dark:bg-purple-900/30'
                  }
                >
                  <Bot
                    className={'h-4 w-4 text-purple-600 dark:text-purple-400'}
                  />
                </div>
                <div>
                  <div className={'text-sm font-medium text-primary'}>
                    {account.display_name}
                  </div>
                  {account.description && (
                    <div className={'text-xs text-tertiary'}>
                      {account.description}
                    </div>
                  )}
                </div>
              </div>
            ),
          },
          {
            key: 'slug',
            header: 'Slug',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (account) => (
              <code
                className={
                  'rounded bg-secondary px-2 py-0.5 text-xs text-secondary'
                }
              >
                {account.slug}
              </code>
            ),
          },
          {
            key: 'status',
            header: 'Status',
            headerAlign: 'center',
            cellAlign: 'center',
            render: (account) => (
              <Badge
                variant={account.is_active ? 'success' : 'neutral'}
                className="gap-1.5"
              >
                <Power className="h-3 w-3" />
                {account.is_active ? 'Active' : 'Inactive'}
              </Badge>
            ),
          },
          {
            key: 'last_auth',
            header: 'Last Authenticated',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (account) => (
              <span className={'text-xs text-secondary'}>
                {formatDate(account.last_authenticated)}
              </span>
            ),
          },
        ]}
        rows={filteredAccounts}
        getRowKey={(account) => account.slug}
        getDeleteLabel={(account) => account.display_name}
        onRowClick={(account) => handleViewClick(account)}
        onDelete={handleDelete}
        isDeleting={deleteMutation.isPending}
        emptyMessage={
          searchQuery || statusFilter !== 'all'
            ? 'No service accounts match your filters'
            : 'No service accounts created yet'
        }
      />

      {/* Summary */}
      {filteredAccounts.length > 0 && (
        <div className={'text-sm text-secondary'}>
          Showing {filteredAccounts.length} of {serviceAccounts.length} service
          account(s)
        </div>
      )}
    </div>
  )
}
