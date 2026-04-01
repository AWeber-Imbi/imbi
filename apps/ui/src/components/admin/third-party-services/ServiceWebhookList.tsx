import { useState, useMemo, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { AxiosError } from 'axios'
import { Plus, Search, Trash2, Webhook, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { WebhookForm } from '../webhooks/WebhookForm'
import { WebhookDetail } from '../webhooks/WebhookDetail'
import {
  listServiceWebhooks,
  createWebhook,
  updateWebhook,
  deleteWebhook,
} from '@/api/endpoints'
import type { WebhookCreate } from '@/types'
import type { ViewMode } from '@/hooks/useAdminNav'

interface ServiceWebhookListProps {
  orgSlug: string
  serviceSlug: string
  isDarkMode: boolean
  onViewModeChange?: (mode: ViewMode) => void
}

export function ServiceWebhookList({
  orgSlug,
  serviceSlug,
  isDarkMode,
  onViewModeChange,
}: ServiceWebhookListProps) {
  const queryClient = useQueryClient()
  const [viewMode, _setViewMode] = useState<ViewMode>('list')
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  const setViewMode = useCallback(
    (mode: ViewMode) => {
      _setViewMode(mode)
      onViewModeChange?.(mode)
    },
    [onViewModeChange],
  )

  const {
    data: webhooks = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ['service-webhooks', orgSlug, serviceSlug],
    queryFn: () => listServiceWebhooks(orgSlug, serviceSlug),
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
    mutationFn: ({ slug, data }: { slug: string; data: WebhookCreate }) =>
      updateWebhook(orgSlug, slug, data),
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
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['service-webhooks', orgSlug, serviceSlug],
      })
      queryClient.invalidateQueries({
        queryKey: ['webhooks', orgSlug],
      })
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
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

  const handleDelete = (slug: string) => {
    const wh = webhooks.find((w) => w.slug === slug)
    if (
      wh &&
      confirm(`Delete webhook "${wh.name}"? This action cannot be undone.`)
    ) {
      deleteMutation.mutate(slug)
    }
  }

  const handleSave = (data: WebhookCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate({
        ...data,
        third_party_service_slug: serviceSlug,
      })
    } else if (selectedSlug) {
      updateMutation.mutate({ slug: selectedSlug, data })
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
        webhook={viewMode === 'edit' ? selectedWebhook : null}
        onSave={handleSave}
        onCancel={
          viewMode === 'edit' ? handleCancelToDetail : handleCancelToList
        }
        isDarkMode={isDarkMode}
        isLoading={createMutation.isPending || updateMutation.isPending}
        error={createMutation.error || updateMutation.error}
        defaultServiceSlug={serviceSlug}
      />
    )
  }

  if (viewMode === 'detail' && selectedWebhook) {
    return (
      <WebhookDetail
        webhook={selectedWebhook}
        onEdit={() => {
          setSelectedSlug(selectedWebhook.slug)
          setViewMode('edit')
        }}
        onBack={handleCancelToList}
        isDarkMode={isDarkMode}
      />
    )
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <div
          className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
        >
          Loading webhooks...
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
          <div
            className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
          >
            {filteredWebhooks.length} webhook
            {filteredWebhooks.length !== 1 ? 's' : ''}
          </div>
          {webhooks.length > 0 && (
            <div className="relative max-w-xs">
              <Search
                className={`absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}
              />
              <Input
                placeholder="Search webhooks..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className={`pl-10 ${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''}`}
              />
            </div>
          )}
        </div>
        <Button
          onClick={() => {
            setSelectedSlug(null)
            setViewMode('create')
          }}
          size="sm"
          className="bg-[#2A4DD0] text-white hover:bg-blue-700"
        >
          <Plus className="mr-2 h-4 w-4" />
          New Webhook
        </Button>
      </div>

      {/* Table */}
      {filteredWebhooks.length === 0 ? (
        <div
          className={`py-8 text-center ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
        >
          <Webhook className="mx-auto mb-2 h-8 w-8 opacity-50" />
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
        <div
          className={`overflow-hidden rounded-lg border ${
            isDarkMode
              ? 'border-gray-700 bg-gray-800'
              : 'border-gray-200 bg-white'
          }`}
        >
          <table className="w-full">
            <thead
              className={`border-b ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
            >
              <tr>
                <th
                  className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}
                >
                  Webhook
                </th>
                <th
                  className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}
                >
                  Path
                </th>
                <th
                  className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}
                >
                  Rules
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
              {filteredWebhooks.map((wh) => (
                <tr
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
                  aria-label={`View webhook ${wh.name}`}
                  className={`cursor-pointer ${isDarkMode ? 'hover:bg-gray-700/50' : 'hover:bg-gray-50'}`}
                >
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div
                        className={`flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg ${
                          isDarkMode ? 'bg-indigo-900/30' : 'bg-indigo-50'
                        }`}
                      >
                        <Webhook
                          className={`h-4 w-4 ${isDarkMode ? 'text-indigo-400' : 'text-indigo-600'}`}
                        />
                      </div>
                      <div>
                        <div
                          className={
                            isDarkMode ? 'text-white' : 'text-gray-900'
                          }
                        >
                          {wh.name}
                        </div>
                        {wh.description && (
                          <div
                            className={`max-w-xs truncate text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
                          >
                            {wh.description}
                          </div>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <code
                      className={`rounded px-2 py-1 text-xs ${
                        isDarkMode
                          ? 'bg-gray-700 text-gray-300'
                          : 'bg-gray-100 text-gray-700'
                      }`}
                    >
                      {wh.notification_path}
                    </code>
                  </td>
                  <td
                    className={`px-6 py-4 text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}
                  >
                    {wh.rules.length}
                  </td>
                  <td
                    className="px-6 py-4 text-right"
                    onClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => e.stopPropagation()}
                  >
                    <div className="flex items-center justify-end gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Delete webhook ${wh.name}`}
                        onClick={() => handleDelete(wh.slug)}
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
        </div>
      )}
    </div>
  )
}
