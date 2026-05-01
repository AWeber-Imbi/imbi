import { useMemo, useState } from 'react'

import { Webhook as WebhookIcon } from 'lucide-react'

import {
  createWebhook,
  deleteWebhook,
  listWebhooks,
  updateWebhook,
} from '@/api/endpoints'
import { AdminTable } from '@/components/ui/admin-table'
import { Card, CardContent, CardDescription } from '@/components/ui/card'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import { useAdminNav } from '@/hooks/useAdminNav'
import { buildDiffPatch } from '@/lib/json-patch'
import type { PatchOperation, Webhook, WebhookCreate } from '@/types'

import { AdminSection } from './AdminSection'
import { WebhookDetail } from './webhooks/WebhookDetail'
import { WebhookForm, type WebhookSaveData } from './webhooks/WebhookForm'

export function WebhookManagement() {
  const { selectedOrganization } = useOrganization()
  const {
    goToCreate,
    goToEdit,
    goToList,
    slug: selectedSlug,
    viewMode,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')

  const orgSlug = selectedOrganization?.slug

  const {
    createMutation,
    deleteMutation,
    error,
    isLoading,
    items: webhooks,
    updateMutation,
  } = useAdminCrud<
    Webhook,
    WebhookCreate,
    { operations: PatchOperation[]; slug: string },
    string
  >({
    createFn: (data) => {
      if (!orgSlug) throw new Error('No organization selected')
      return createWebhook(orgSlug, data)
    },
    deleteErrorLabel: 'webhook',
    deleteFn: (webhookSlug) => {
      if (!orgSlug) throw new Error('No organization selected')
      return deleteWebhook(orgSlug, webhookSlug)
    },
    listFn: orgSlug ? (signal) => listWebhooks(orgSlug, signal) : null,
    onMutationSuccess: goToList,
    queryKey: ['webhooks', orgSlug],
    updateFn: ({ operations, slug: webhookSlug }) => {
      if (!orgSlug) throw new Error('No organization selected')
      return updateWebhook(orgSlug, webhookSlug, operations)
    },
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

  const handleSave = (data: WebhookSaveData) => {
    if (viewMode === 'create') {
      // slug is not included in create payload — it's system-generated.
      const { slug: _slug, ...createData } = data
      createMutation.mutate(createData)
    } else if (selectedSlug && selectedWebhook) {
      // diff against all editable fields, including slug.
      const fields = Object.keys(data).filter(
        (k) => k !== 'id' && k !== 'notification_path',
      )
      const operations = buildDiffPatch(
        selectedWebhook as unknown as Record<string, unknown>,
        data as unknown as Record<string, unknown>,
        { fields },
      )
      if (operations.length === 0) {
        goToList()
        return
      }
      updateMutation.mutate({ operations, slug: selectedSlug })
    }
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <WebhookForm
        error={createMutation.error || updateMutation.error}
        isLoading={createMutation.isPending || updateMutation.isPending}
        onCancel={goToList}
        onSave={handleSave}
        webhook={viewMode === 'edit' ? selectedWebhook : null}
      />
    )
  }

  if (viewMode === 'detail' && selectedWebhook) {
    return (
      <WebhookDetail
        onBack={goToList}
        onEdit={() => goToEdit(selectedWebhook.slug)}
        webhook={selectedWebhook}
      />
    )
  }

  return (
    <AdminSection
      createLabel="New Webhook"
      error={error}
      errorTitle="Failed to load webhooks"
      isLoading={isLoading}
      loadingLabel="Loading webhooks..."
      onCreate={goToCreate}
      onSearchChange={setSearchQuery}
      search={searchQuery}
      searchPlaceholder="Search webhooks..."
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
            cellAlign: 'left',
            header: 'Webhook',
            headerAlign: 'left',
            key: 'name',
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
            cellAlign: 'left',
            header: 'Path',
            headerAlign: 'left',
            key: 'path',
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
            cellAlign: 'left',
            header: 'Service',
            headerAlign: 'left',
            key: 'service',
            render: (wh) =>
              (wh.third_party_service?.name as string | undefined) || (
                <span className="text-tertiary">--</span>
              ),
          },
          {
            cellAlign: 'left',
            header: 'Rules',
            headerAlign: 'left',
            key: 'rules',
            render: (wh) => (
              <span className="text-secondary">{wh.rules.length}</span>
            ),
          },
        ]}
        emptyMessage={
          searchQuery
            ? 'No webhooks found matching your search.'
            : selectedOrganization
              ? `No webhooks in ${selectedOrganization.name} yet.`
              : 'No webhooks created yet.'
        }
        getDeleteLabel={(wh) => wh.name}
        getRowKey={(wh) => wh.slug}
        isDeleting={deleteMutation.isPending}
        onDelete={handleDelete}
        onRowClick={(wh) => goToEdit(wh.slug)}
        rows={filteredWebhooks}
      />
    </AdminSection>
  )
}
