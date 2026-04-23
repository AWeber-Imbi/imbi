import { useState, useMemo } from 'react'
import { Webhook as WebhookIcon } from 'lucide-react'
import { Card, CardContent, CardDescription } from '@/components/ui/card'
import { AdminTable } from '@/components/ui/admin-table'
import { AdminSection } from './AdminSection'
import { WebhookForm } from './webhooks/WebhookForm'
import { WebhookDetail } from './webhooks/WebhookDetail'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAdminNav } from '@/hooks/useAdminNav'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import {
  listWebhooks,
  deleteWebhook,
  createWebhook,
  updateWebhook,
} from '@/api/endpoints'
import type { Webhook, WebhookCreate } from '@/types'

export function WebhookManagement() {
  const { selectedOrganization } = useOrganization()
  const {
    viewMode,
    slug: selectedSlug,
    goToList,
    goToCreate,
    goToEdit,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')

  const orgSlug = selectedOrganization?.slug

  const {
    items: webhooks,
    isLoading,
    error,
    createMutation,
    updateMutation,
    deleteMutation,
  } = useAdminCrud<
    Webhook,
    WebhookCreate,
    { slug: string; data: WebhookCreate },
    string
  >({
    queryKey: ['webhooks', orgSlug],
    listFn: orgSlug ? (signal) => listWebhooks(orgSlug, signal) : null,
    createFn: (data) => {
      if (!orgSlug) throw new Error('No organization selected')
      return createWebhook(orgSlug, data)
    },
    updateFn: ({ slug, data }) => {
      if (!orgSlug) throw new Error('No organization selected')
      return updateWebhook(orgSlug, slug, data)
    },
    deleteFn: (slug) => {
      if (!orgSlug) throw new Error('No organization selected')
      return deleteWebhook(orgSlug, slug)
    },
    onMutationSuccess: goToList,
    deleteErrorLabel: 'webhook',
  })

  const filteredWebhooks = webhooks.filter((wh) => {
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      return (
        wh.name.toLowerCase().includes(query) ||
        wh.slug.toLowerCase().includes(query) ||
        wh.notification_path.toLowerCase().includes(query) ||
        (wh.description?.toLowerCase().includes(query) ?? false)
      )
    }
    return true
  })

  const selectedWebhook = useMemo(
    () => webhooks.find((w) => w.slug === selectedSlug) || null,
    [webhooks, selectedSlug],
  )

  const handleDelete = (wh: Webhook) => {
    deleteMutation.mutate(wh.slug)
  }

  const handleSave = (data: WebhookCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate(data)
    } else if (selectedSlug) {
      updateMutation.mutate({ slug: selectedSlug, data })
    }
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <WebhookForm
        webhook={viewMode === 'edit' ? selectedWebhook : null}
        onSave={handleSave}
        onCancel={goToList}
        isLoading={createMutation.isPending || updateMutation.isPending}
        error={createMutation.error || updateMutation.error}
      />
    )
  }

  if (viewMode === 'detail' && selectedWebhook) {
    return (
      <WebhookDetail
        webhook={selectedWebhook}
        onEdit={() => goToEdit(selectedWebhook.slug)}
        onBack={goToList}
      />
    )
  }

  return (
    <AdminSection
      searchPlaceholder="Search webhooks..."
      search={searchQuery}
      onSearchChange={setSearchQuery}
      createLabel="New Webhook"
      onCreate={goToCreate}
      isLoading={isLoading}
      loadingLabel="Loading webhooks..."
      error={error}
      errorTitle="Failed to load webhooks"
    >
      {/* Stats */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
        <Card>
          <CardContent className="p-4">
            <CardDescription className="text-secondary">
              Total Webhooks
            </CardDescription>
            <div className="mt-1 text-2xl text-primary">
              {filteredWebhooks.length}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <CardDescription className="text-secondary">
              With Service
            </CardDescription>
            <div className="mt-1 text-2xl text-info">
              {filteredWebhooks.filter((w) => w.third_party_service).length}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <CardDescription className="text-secondary">
              Total Rules
            </CardDescription>
            <div className="mt-1 text-2xl text-purple-600 dark:text-purple-400">
              {filteredWebhooks.reduce((sum, w) => sum + w.rules.length, 0)}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Webhooks Table */}
      <AdminTable
        columns={[
          {
            key: 'name',
            header: 'Webhook',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (wh) => (
              <div className="flex items-center gap-3">
                <div
                  className={
                    'flex size-8 flex-shrink-0 items-center justify-center rounded-lg bg-indigo-50 dark:bg-indigo-900/30'
                  }
                >
                  <WebhookIcon className="h-4 w-4 text-indigo-600 dark:text-indigo-400" />
                </div>
                <div>
                  <div className="text-primary">{wh.name}</div>
                  {wh.description && (
                    <div className="max-w-xs truncate text-sm text-tertiary">
                      {wh.description}
                    </div>
                  )}
                </div>
              </div>
            ),
          },
          {
            key: 'path',
            header: 'Path',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (wh) => (
              <code
                className={
                  'rounded bg-secondary px-2 py-1 text-xs text-primary'
                }
              >
                {wh.notification_path}
              </code>
            ),
          },
          {
            key: 'service',
            header: 'Service',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (wh) =>
              (wh.third_party_service?.name as string | undefined) || (
                <span className="text-tertiary">--</span>
              ),
          },
          {
            key: 'rules',
            header: 'Rules',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (wh) => (
              <span className="text-secondary">{wh.rules.length}</span>
            ),
          },
        ]}
        rows={filteredWebhooks}
        getRowKey={(wh) => wh.slug}
        getDeleteLabel={(wh) => wh.name}
        onRowClick={(wh) => goToEdit(wh.slug)}
        onDelete={handleDelete}
        isDeleting={deleteMutation.isPending}
        emptyMessage={
          searchQuery
            ? 'No webhooks found matching your search.'
            : selectedOrganization
              ? `No webhooks in ${selectedOrganization.name} yet.`
              : 'No webhooks created yet.'
        }
      />
    </AdminSection>
  )
}
