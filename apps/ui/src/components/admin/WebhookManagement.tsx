import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Search, Trash2, Webhook, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { WebhookForm } from './webhooks/WebhookForm'
import { WebhookDetail } from './webhooks/WebhookDetail'
import { useOrganization } from '@/contexts/OrganizationContext'
import { listWebhooks, deleteWebhook, createWebhook, updateWebhook } from '@/api/endpoints'
import type { WebhookCreate } from '@/types'

interface WebhookManagementProps {
  isDarkMode: boolean
}

type ViewMode = 'list' | 'create' | 'edit' | 'detail'

export function WebhookManagement({ isDarkMode }: WebhookManagementProps) {
  const queryClient = useQueryClient()
  const { selectedOrganization } = useOrganization()
  const [viewMode, setViewMode] = useState<ViewMode>('list')
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  const orgSlug = selectedOrganization?.slug

  const { data: webhooks = [], isLoading, error } = useQuery({
    queryKey: ['webhooks', orgSlug],
    queryFn: () => listWebhooks(orgSlug!),
    enabled: !!orgSlug,
  })

  const createMutation = useMutation({
    mutationFn: (data: WebhookCreate) => createWebhook(orgSlug!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['webhooks', orgSlug] })
      setViewMode('list')
      setSelectedSlug(null)
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ slug, data }: { slug: string; data: WebhookCreate }) =>
      updateWebhook(orgSlug!, slug, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['webhooks', orgSlug] })
      setViewMode('list')
      setSelectedSlug(null)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (slug: string) => deleteWebhook(orgSlug!, slug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['webhooks', orgSlug] })
    },
    onError: (error: any) => {
      alert(`Failed to delete webhook: ${error.response?.data?.detail || error.message}`)
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
    if (wh && confirm(`Delete webhook "${wh.name}"? This action cannot be undone.`)) {
      deleteMutation.mutate(slug)
    }
  }

  const handleSave = (data: WebhookCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate(data)
    } else if (selectedSlug) {
      updateMutation.mutate({ slug: selectedSlug, data })
    }
  }

  const handleCancel = () => {
    setViewMode('list')
    setSelectedSlug(null)
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
          Loading webhooks...
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className={`flex items-center gap-3 p-4 rounded-lg border ${
        isDarkMode ? 'bg-red-900/20 border-red-700 text-red-400' : 'bg-red-50 border-red-200 text-red-700'
      }`}>
        <AlertCircle className="w-5 h-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load webhooks</div>
          <div className="text-sm mt-1">{error instanceof Error ? error.message : 'An error occurred'}</div>
        </div>
      </div>
    )
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <WebhookForm
        webhook={selectedWebhook}
        onSave={handleSave}
        onCancel={handleCancel}
        isDarkMode={isDarkMode}
        isLoading={createMutation.isPending || updateMutation.isPending}
        error={createMutation.error || updateMutation.error}
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
            <Search className={`absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 ${
              isDarkMode ? 'text-gray-400' : 'text-gray-500'
            }`} />
            <Input
              placeholder="Search webhooks..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={`pl-10 ${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}`}
            />
          </div>
        </div>
        <Button
          onClick={() => {
            setSelectedSlug(null)
            setViewMode('create')
          }}
          className="bg-[#2A4DD0] hover:bg-blue-700 text-white"
        >
          <Plus className="w-4 h-4 mr-2" />
          New Webhook
        </Button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <div className={`p-4 rounded-lg border ${
          isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
        }`}>
          <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            Total Webhooks
          </div>
          <div className={`mt-1 text-2xl ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
            {filteredWebhooks.length}
          </div>
        </div>
        <div className={`p-4 rounded-lg border ${
          isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
        }`}>
          <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>With Service</div>
          <div className={`mt-1 text-2xl ${isDarkMode ? 'text-blue-400' : 'text-blue-600'}`}>
            {filteredWebhooks.filter((w) => w.third_party_service).length}
          </div>
        </div>
        <div className={`p-4 rounded-lg border ${
          isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
        }`}>
          <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>Total Rules</div>
          <div className={`mt-1 text-2xl ${isDarkMode ? 'text-purple-400' : 'text-purple-600'}`}>
            {filteredWebhooks.reduce((sum, w) => sum + w.rules.length, 0)}
          </div>
        </div>
      </div>

      {/* Webhooks Table */}
      <div className={`rounded-lg border ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className={`border-b ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}>
              <tr>
                <th className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}>Webhook</th>
                <th className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}>Path</th>
                <th className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}>Service</th>
                <th className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}>Rules</th>
                <th className={`px-6 py-3 text-right text-xs uppercase tracking-wider ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}>Actions</th>
              </tr>
            </thead>
            <tbody className={`divide-y ${isDarkMode ? 'divide-gray-700' : 'divide-gray-200'}`}>
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
                      <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
                        isDarkMode ? 'bg-indigo-900/30' : 'bg-indigo-50'
                      }`}>
                        <Webhook className={`w-4 h-4 ${isDarkMode ? 'text-indigo-400' : 'text-indigo-600'}`} />
                      </div>
                      <div>
                        <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
                          {wh.name}
                        </div>
                        {wh.description && (
                          <div className={`text-sm truncate max-w-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                            {wh.description}
                          </div>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className={`px-6 py-4`}>
                    <code className={`px-2 py-1 rounded text-xs ${
                      isDarkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-700'
                    }`}>
                      {wh.notification_path}
                    </code>
                  </td>
                  <td className={`px-6 py-4 text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}>
                    {wh.third_party_service?.name || (
                      <span className={isDarkMode ? 'text-gray-500' : 'text-gray-400'}>--</span>
                    )}
                  </td>
                  <td className={`px-6 py-4 text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}>
                    {wh.rules.length}
                  </td>
                  <td className="px-6 py-4 text-right" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
                    <div className="flex items-center justify-end gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Delete webhook ${wh.name}`}
                        onClick={() => handleDelete(wh.slug)}
                        disabled={deleteMutation.isPending}
                        className={isDarkMode ? 'text-red-400 hover:text-red-300 hover:bg-red-900/20' : 'text-red-600 hover:text-red-700 hover:bg-red-50'}
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {filteredWebhooks.length === 0 && (
            <div className={`text-center py-12 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
              {searchQuery
                ? 'No webhooks found matching your search.'
                : selectedOrganization
                  ? `No webhooks in ${selectedOrganization.name} yet.`
                  : 'No webhooks created yet.'}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
