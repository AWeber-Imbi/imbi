import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { Bot, Power } from 'lucide-react'

import {
  createServiceAccount,
  deleteServiceAccount,
  getServiceAccount,
  listServiceAccounts,
  updateServiceAccount,
} from '@/api/endpoints'
import { AdminTable } from '@/components/ui/admin-table'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import { useAdminNav } from '@/hooks/useAdminNav'
import { buildDiffPatch } from '@/lib/json-patch'
import type {
  PatchOperation,
  ServiceAccount,
  ServiceAccountCreate,
} from '@/types'

import { Badge } from '../ui/badge'
import { AdminSection } from './AdminSection'
import { ServiceAccountDetail } from './service-accounts/ServiceAccountDetail'
import { ServiceAccountForm } from './service-accounts/ServiceAccountForm'

type StatusFilter = 'active' | 'all' | 'inactive'

export function ServiceAccountManagement() {
  const {
    goToCreate,
    goToEdit,
    goToList,
    slug: selectedAccountSlug,
    viewMode,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')

  const {
    createMutation,
    deleteMutation,
    error,
    isLoading,
    items: serviceAccounts,
    updateMutation,
  } = useAdminCrud<
    ServiceAccount,
    ServiceAccountCreate,
    { operations: PatchOperation[]; slug: string },
    string
  >({
    createFn: createServiceAccount,
    deleteErrorLabel: 'service account',
    deleteFn: deleteServiceAccount,
    listFn: (signal) => listServiceAccounts(undefined, signal),
    onMutationSuccess: goToList,
    queryKey: ['serviceAccounts'],
    updateFn: ({ operations, slug }) => updateServiceAccount(slug, operations),
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
    enabled:
      !!selectedAccountSlug && (viewMode === 'detail' || viewMode === 'edit'),
    queryFn: ({ signal }) => getServiceAccount(selectedAccountSlug!, signal),
    queryKey: ['serviceAccount', selectedAccountSlug],
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
      const operations = buildDiffPatch(
        selectedAccount as unknown as Record<string, unknown>,
        updateData as unknown as Record<string, unknown>,
        { fields: Object.keys(updateData) },
      )
      if (operations.length === 0) {
        goToList()
        return
      }
      updateMutation.mutate({ operations, slug: selectedAccount.slug })
    }
  }

  const handleCancel = () => {
    goToList()
  }

  const formatDate = (dateString?: null | string) => {
    if (!dateString) return 'Never'
    return new Date(dateString).toLocaleString('en-US', {
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      month: 'short',
      year: 'numeric',
    })
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <ServiceAccountForm
        account={selectedAccount}
        error={createMutation.error || updateMutation.error}
        isLoading={createMutation.isPending || updateMutation.isPending}
        onCancel={handleCancel}
        onSave={handleSave}
      />
    )
  }

  if (viewMode === 'detail' && selectedAccount) {
    return (
      <ServiceAccountDetail
        account={selectedAccount}
        onBack={handleCancel}
        onEdit={() => handleEditClick(selectedAccount)}
      />
    )
  }

  return (
    <AdminSection
      createLabel="New Service Account"
      error={error}
      errorTitle="Failed to load service accounts"
      headerExtras={
        <select
          className="rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground"
          onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
          value={statusFilter}
        >
          <option value="all">All Status</option>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
        </select>
      }
      isLoading={isLoading}
      loadingLabel="Loading service accounts..."
      onCreate={goToCreate}
      onSearchChange={setSearchQuery}
      search={searchQuery}
      searchPlaceholder="Search service accounts..."
    >
      {/* Service Accounts Table */}
      <AdminTable
        columns={[
          {
            cellAlign: 'left',
            header: 'Service Account',
            headerAlign: 'left',
            key: 'name',
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
            cellAlign: 'left',
            header: 'Slug',
            headerAlign: 'left',
            key: 'slug',
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
            cellAlign: 'center',
            header: 'Status',
            headerAlign: 'center',
            key: 'status',
            render: (account) => (
              <Badge
                className="gap-1.5"
                variant={account.is_active ? 'success' : 'neutral'}
              >
                <Power className="h-3 w-3" />
                {account.is_active ? 'Active' : 'Inactive'}
              </Badge>
            ),
          },
          {
            cellAlign: 'left',
            header: 'Last Authenticated',
            headerAlign: 'left',
            key: 'last_auth',
            render: (account) => (
              <span className="text-xs text-secondary">
                {formatDate(account.last_authenticated)}
              </span>
            ),
          },
        ]}
        emptyMessage={
          searchQuery || statusFilter !== 'all'
            ? 'No service accounts match your filters'
            : 'No service accounts created yet'
        }
        getDeleteLabel={(account) => account.display_name}
        getRowKey={(account) => account.slug}
        isDeleting={deleteMutation.isPending}
        onDelete={handleDelete}
        onRowClick={(account) => handleViewClick(account)}
        rows={filteredAccounts}
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
