import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '@/api/client'
import { Plus, Search, Webhook, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardDescription } from '@/components/ui/card'
import { AdminTable } from '@/components/ui/admin-table'
import { WebhookForm } from './webhooks/WebhookForm'
import { WebhookDetail } from './webhooks/WebhookDetail'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAdminNav } from '@/hooks/useAdminNav'
import {
  listWebhooks,
  deleteWebhook,
  createWebhook,
  updateWebhook,
} from '@/api/endpoints'
import type { WebhookCreate } from '@/types'

export function WebhookManagement() {
  const queryClient = useQueryClient()
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
    data: webhooks = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ['webhooks', orgSlug],
    queryFn: () => listWebhooks(orgSlug!),
    enabled: !!orgSlug,
  })

  const createMutation = useMutation({
    mutationFn: (data: WebhookCreate) => createWebhook(orgSlug!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['webhooks', orgSlug] })
      goToList()
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ slug, data }: { slug: string; data: WebhookCreate }) =>
      updateWebhook(orgSlug!, slug, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['webhooks', orgSlug] })
      goToList()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (slug: string) => deleteWebhook(orgSlug!, slug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['webhooks', orgSlug] })
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      alert(
        `Failed to delete webhook: ${error.response?.data?.detail || error.message}`,
      )
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

  const handleDelete = (wh: (typeof webhooks)[number]) => {
    deleteMutation.mutate(wh.slug)
  }

  const handleSave = (data: WebhookCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate(data)
    } else if (selectedSlug) {
      updateMutation.mutate({ slug: selectedSlug, data })
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className={'text-sm text-secondary'}>Loading webhooks...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div
        className={`flex items-center gap-3 rounded-lg border p-4 ${'border-danger bg-danger text-danger'}`}
      >
        <AlertCircle className="h-5 w-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load webhooks</div>
          <div className="mt-1 text-sm">
            {error instanceof Error ? error.message : 'An error occurred'}
          </div>
        </div>
      </div>
    )
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
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex-1">
          <div className="relative max-w-md">
            <Search
              className={`absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${'text-tertiary'}`}
            />
            <Input
              placeholder="Search webhooks..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={'pl-10'}
            />
          </div>
        </div>
        <Button
          onClick={goToCreate}
          className="bg-action text-action-foreground hover:bg-action-hover"
        >
          <Plus className="mr-2 h-4 w-4" />
          New Webhook
        </Button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
        <Card>
          <CardContent className="p-4">
            <CardDescription className={'text-secondary'}>
              Total Webhooks
            </CardDescription>
            <div className={'mt-1 text-2xl text-primary'}>
              {filteredWebhooks.length}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <CardDescription className={'text-secondary'}>
              With Service
            </CardDescription>
            <div className={'mt-1 text-2xl text-info'}>
              {filteredWebhooks.filter((w) => w.third_party_service).length}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <CardDescription className={'text-secondary'}>
              Total Rules
            </CardDescription>
            <div
              className={'mt-1 text-2xl text-purple-600 dark:text-purple-400'}
            >
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
                  <Webhook
                    className={'h-4 w-4 text-indigo-600 dark:text-indigo-400'}
                  />
                </div>
                <div>
                  <div className={'text-primary'}>{wh.name}</div>
                  {wh.description && (
                    <div className={'max-w-xs truncate text-sm text-tertiary'}>
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
              wh.third_party_service?.name || (
                <span className={'text-tertiary'}>--</span>
              ),
          },
          {
            key: 'rules',
            header: 'Rules',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (wh) => (
              <span className={'text-secondary'}>{wh.rules.length}</span>
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
    </div>
  )
}
