import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Power, Bot } from 'lucide-react'
import { Badge } from '../ui/badge'
import { AdminTable } from '@/components/ui/admin-table'
import { AdminSection } from './AdminSection'
import { ServiceAccountForm } from './service-accounts/ServiceAccountForm'
import { ServiceAccountDetail } from './service-accounts/ServiceAccountDetail'
import { useAdminNav } from '@/hooks/useAdminNav'
import { useAdminCrud } from '@/hooks/useAdminCrud'
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
  const {
    viewMode,
    slug: selectedAccountSlug,
    goToList,
    goToCreate,
    goToEdit,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')

  const {
    items: serviceAccounts,
    isLoading,
    error,
    createMutation,
    updateMutation,
    deleteMutation,
  } = useAdminCrud<
    ServiceAccount,
    ServiceAccountCreate,
    { slug: string; data: ServiceAccountUpdate },
    string
  >({
    queryKey: ['serviceAccounts'],
    listFn: (signal) => listServiceAccounts(undefined, signal),
    createFn: createServiceAccount,
    updateFn: ({ slug, data }) => updateServiceAccount(slug, data),
    deleteFn: deleteServiceAccount,
    onMutationSuccess: goToList,
    deleteErrorLabel: 'service account',
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
    queryFn: ({ signal }) => getServiceAccount(selectedAccountSlug!, signal),
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

  if (viewMode === 'detail' && selectedAccount) {
    return (
      <ServiceAccountDetail
        account={selectedAccount}
        onEdit={() => handleEditClick(selectedAccount)}
        onBack={handleCancel}
      />
    )
  }

  return (
    <AdminSection
      searchPlaceholder="Search service accounts..."
      search={searchQuery}
      onSearchChange={setSearchQuery}
      createLabel="New Service Account"
      onCreate={goToCreate}
      isLoading={isLoading}
      loadingLabel="Loading service accounts..."
      error={error}
      errorTitle="Failed to load service accounts"
      headerExtras={
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
          className="rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground"
        >
          <option value="all">All Status</option>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
        </select>
      }
    >
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
                  <Bot className="h-4 w-4 text-purple-600 dark:text-purple-400" />
                </div>
                <div>
                  <div className="text-sm font-medium text-primary">
                    {account.display_name}
                  </div>
                  {account.description && (
                    <div className="text-xs text-tertiary">
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
              <span className="text-xs text-secondary">
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
        <div className="text-sm text-secondary">
          Showing {filteredAccounts.length} of {serviceAccounts.length} service
          account(s)
        </div>
      )}
    </AdminSection>
  )
}
