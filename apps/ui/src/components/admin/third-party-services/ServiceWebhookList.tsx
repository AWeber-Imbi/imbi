import { useCallback, useMemo, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, Plus, Search, Trash2, Webhook } from 'lucide-react'
import { toast } from 'sonner'

import {
  createWebhook,
  deleteWebhook,
  listServiceWebhooks,
  updateWebhook,
} from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { ViewMode } from '@/hooks/useAdminNav'
import { extractApiErrorDetail } from '@/lib/apiError'
import { buildDiffPatch } from '@/lib/json-patch'
import type { PatchOperation, WebhookCreate } from '@/types'

import { WebhookDetail } from '../webhooks/WebhookDetail'
import { WebhookForm, type WebhookSaveData } from '../webhooks/WebhookForm'

interface ServiceWebhookListProps {
  onViewModeChange?: (mode: ViewMode) => void
  orgSlug: string
  serviceSlug: string
}

export function ServiceWebhookList({
  onViewModeChange,
  orgSlug,
  serviceSlug,
}: ServiceWebhookListProps) {
  const queryClient = useQueryClient()
  const [viewMode, _setViewMode] = useState<ViewMode>('list')
  const [selectedSlug, setSelectedSlug] = useState<null | string>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [confirm, setConfirm] = useState<null | {
    action: 'delete'
    name: string
    slug: string
  }>(null)

  const setViewMode = useCallback(
    (mode: ViewMode) => {
      _setViewMode(mode)
      onViewModeChange?.(mode)
    },
    [onViewModeChange],
  )

  const {
    data: webhooks = [],
    error,
    isLoading,
  } = useQuery({
    queryFn: ({ signal }) => listServiceWebhooks(orgSlug, serviceSlug, signal),
    queryKey: ['service-webhooks', orgSlug, serviceSlug],
  })

  const createMutation = useMutation({
    mutationFn: (data: WebhookCreate) => createWebhook(orgSlug, data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['service-webhooks', orgSlug, serviceSlug],
      })
      queryClient.invalidateQueries({
        queryKey: ['webhooks', orgSlug],
      })
      setViewMode('list')
      setSelectedSlug(null)
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({
      operations,
      slug,
    }: {
      operations: PatchOperation[]
      slug: string
    }) => updateWebhook(orgSlug, slug, operations),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['service-webhooks', orgSlug, serviceSlug],
      })
      queryClient.invalidateQueries({
        queryKey: ['webhooks', orgSlug],
      })
      setViewMode('list')
      setSelectedSlug(null)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (slug: string) => deleteWebhook(orgSlug, slug),
    onError: (error: unknown) => {
      toast.error(`Failed to delete webhook: ${extractApiErrorDetail(error)}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['service-webhooks', orgSlug, serviceSlug],
      })
      queryClient.invalidateQueries({
        queryKey: ['webhooks', orgSlug],
      })
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

  const handleDelete = (slug: string) => {
    const wh = webhooks.find((w) => w.slug === slug)
    if (wh) {
      setConfirm({ action: 'delete', name: wh.name, slug })
    }
  }

  const handleSave = (data: WebhookSaveData) => {
    if (viewMode === 'create') {
      // slug is system-generated on create; third_party_service_slug is forced.
      const { slug: _slug, ...createData } = data
      createMutation.mutate({
        ...createData,
        third_party_service_slug: serviceSlug,
      })
    } else if (selectedSlug && selectedWebhook) {
      const fields = Object.keys(data).filter(
        (k) => k !== 'id' && k !== 'notification_path',
      )
      const operations = buildDiffPatch(
        selectedWebhook as unknown as Record<string, unknown>,
        data as unknown as Record<string, unknown>,
        { fields },
      )
      if (operations.length === 0) {
        setViewMode('list')
        setSelectedSlug(null)
        return
      }
      updateMutation.mutate({ operations, slug: selectedSlug })
    }
  }

  const handleCancelToList = () => {
    setViewMode('list')
    setSelectedSlug(null)
  }

  const handleCancelToDetail = () => {
    setViewMode('detail')
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <WebhookForm
        defaultServiceSlug={serviceSlug}
        error={createMutation.error || updateMutation.error}
        isLoading={createMutation.isPending || updateMutation.isPending}
        onCancel={
          viewMode === 'edit' ? handleCancelToDetail : handleCancelToList
        }
        onSave={handleSave}
        webhook={viewMode === 'edit' ? selectedWebhook : null}
      />
    )
  }

  if (viewMode === 'detail' && selectedWebhook) {
    return (
      <WebhookDetail
        onBack={handleCancelToList}
        onEdit={() => {
          setSelectedSlug(selectedWebhook.slug)
          setViewMode('edit')
        }}
        webhook={selectedWebhook}
      />
    )
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className="text-secondary text-sm">Loading webhooks...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="border-danger bg-danger text-danger flex items-center gap-3 rounded-lg border p-4">
        <AlertCircle className="size-5 shrink-0" />
        <div>
          <div className="font-medium">Failed to load webhooks</div>
          <div className="mt-1 text-sm">
            {error instanceof Error ? error.message : 'An error occurred'}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="text-secondary text-sm">
            {filteredWebhooks.length} webhook
            {filteredWebhooks.length !== 1 ? 's' : ''}
          </div>
          {webhooks.length > 0 && (
            <div className="relative max-w-xs">
              <Search className="text-tertiary absolute top-1/2 left-3 size-4 -translate-y-1/2" />
              <Input
                className="pl-10"
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search webhooks..."
                value={searchQuery}
              />
            </div>
          )}
        </div>
        <Button
          className="bg-action text-action-foreground hover:bg-action-hover"
          onClick={() => {
            setSelectedSlug(null)
            setViewMode('create')
          }}
          size="sm"
        >
          <Plus className="mr-2 size-4" />
          New Webhook
        </Button>
      </div>

      {/* Table */}
      {filteredWebhooks.length === 0 ? (
        <div className="text-tertiary py-8 text-center">
          <Webhook className="mx-auto mb-2 size-8 opacity-50" />
          <div>
            {searchQuery
              ? 'No webhooks found matching your search.'
              : 'No webhooks linked to this service'}
          </div>
          <div className="mt-1 text-sm">
            {searchQuery
              ? ''
              : 'Create a webhook to start receiving events for this service.'}
          </div>
        </div>
      ) : (
        <div className="border-border bg-card overflow-hidden rounded-lg border">
          <Table>
            <TableHeader className="border-tertiary border-b">
              <TableRow>
                <TableHead className="text-tertiary px-6 py-3 text-left text-xs tracking-wider uppercase">
                  Webhook
                </TableHead>
                <TableHead className="text-tertiary px-6 py-3 text-left text-xs tracking-wider uppercase">
                  Path
                </TableHead>
                <TableHead className="text-tertiary px-6 py-3 text-left text-xs tracking-wider uppercase">
                  Rules
                </TableHead>
                <TableHead className="text-tertiary px-6 py-3 text-right text-xs tracking-wider uppercase">
                  Actions
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody className="divide-tertiary divide-y">
              {filteredWebhooks.map((wh) => (
                <TableRow
                  aria-label={`View webhook ${wh.name}`}
                  className="hover:bg-secondary/50 cursor-pointer"
                  key={wh.slug}
                  onClick={() => {
                    setSelectedSlug(wh.slug)
                    setViewMode('detail')
                  }}
                  onKeyDown={(e) => {
                    if (e.currentTarget !== e.target) return
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      setSelectedSlug(wh.slug)
                      setViewMode('detail')
                    }
                  }}
                  tabIndex={0}
                >
                  <TableCell className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-indigo-50 dark:bg-indigo-900/30">
                        <Webhook
                          className={
                            'size-4 text-indigo-600 dark:text-indigo-400'
                          }
                        />
                      </div>
                      <div>
                        <div className="text-primary">{wh.name}</div>
                        {wh.description && (
                          <div
                            className={
                              'text-tertiary max-w-xs truncate text-sm'
                            }
                          >
                            {wh.description}
                          </div>
                        )}
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className="px-6 py-4">
                    <code className="bg-secondary text-primary rounded px-2 py-1 text-xs">
                      {wh.notification_path}
                    </code>
                  </TableCell>
                  <TableCell className="text-secondary px-6 py-4 text-sm">
                    {wh.rules.length}
                  </TableCell>
                  <TableCell
                    className="px-6 py-4 text-right"
                    onClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => e.stopPropagation()}
                  >
                    <div className="flex items-center justify-end gap-2">
                      <Button
                        aria-label={`Delete webhook ${wh.name}`}
                        className="text-danger hover:bg-danger"
                        disabled={deleteMutation.isPending}
                        onClick={() => handleDelete(wh.slug)}
                        size="sm"
                        variant="ghost"
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      <ConfirmDialog
        confirmLabel="Delete"
        description={
          confirm?.action === 'delete'
            ? `Delete webhook "${confirm.name}"? This action cannot be undone.`
            : 'This action cannot be undone.'
        }
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          if (confirm?.action === 'delete') {
            deleteMutation.mutate(confirm.slug)
          }
          setConfirm(null)
        }}
        open={confirm?.action === 'delete'}
        title="Delete webhook"
      />
    </div>
  )
}
