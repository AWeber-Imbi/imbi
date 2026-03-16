import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, Key, AlertCircle, ExternalLink } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { listServiceApplications, deleteServiceApplication, createServiceApplication, updateServiceApplication } from '@/api/endpoints'
import { OAuth2ApplicationForm } from './OAuth2ApplicationForm'
import { ApplicationSecretsPanel } from './ApplicationSecretsPanel'
import type { ServiceApplication, ServiceApplicationCreate, ServiceApplicationUpdate } from '@/types'

interface OAuth2ApplicationListProps {
  serviceSlug: string
  isDarkMode: boolean
}

const STATUS_COLORS: Record<string, { bg: string; text: string; darkBg: string; darkText: string }> = {
  active: { bg: 'bg-green-100', text: 'text-green-700', darkBg: 'bg-green-900/30', darkText: 'text-green-400' },
  inactive: { bg: 'bg-gray-100', text: 'text-gray-700', darkBg: 'bg-gray-700', darkText: 'text-gray-400' },
  revoked: { bg: 'bg-red-100', text: 'text-red-700', darkBg: 'bg-red-900/30', darkText: 'text-red-400' },
}

export function OAuth2ApplicationList({ serviceSlug, isDarkMode }: OAuth2ApplicationListProps) {
  const queryClient = useQueryClient()
  const [viewMode, setViewMode] = useState<'list' | 'create' | 'edit'>('list')
  const [editingApp, setEditingApp] = useState<ServiceApplication | null>(null)

  const { data: applications = [], isLoading, error } = useQuery({
    queryKey: ['service-applications', serviceSlug],
    queryFn: () => listServiceApplications(serviceSlug),
  })

  const createMutation = useMutation({
    mutationFn: (data: ServiceApplicationCreate) =>
      createServiceApplication(serviceSlug, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['service-applications', serviceSlug] })
      setViewMode('list')
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ appSlug, data }: { appSlug: string; data: ServiceApplicationUpdate }) =>
      updateServiceApplication(serviceSlug, appSlug, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['service-applications', serviceSlug] })
      setViewMode('list')
      setEditingApp(null)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (appSlug: string) => deleteServiceApplication(serviceSlug, appSlug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['service-applications', serviceSlug] })
    },
    onError: (error: any) => {
      alert(`Failed to delete application: ${error.response?.data?.detail || error.message}`)
    },
  })

  const handleDelete = (app: ServiceApplication) => {
    if (confirm(`Delete application "${app.name}"? This cannot be undone.`)) {
      deleteMutation.mutate(app.slug)
    }
  }

  const handleSave = (data: ServiceApplicationCreate | ServiceApplicationUpdate) => {
    if (viewMode === 'create') {
      createMutation.mutate(data as ServiceApplicationCreate)
    } else if (editingApp) {
      updateMutation.mutate({ appSlug: editingApp.slug, data: data as ServiceApplicationUpdate })
    }
  }

  if (viewMode === 'create') {
    return (
      <OAuth2ApplicationForm
        application={null}
        onSave={handleSave}
        onCancel={() => {
          setViewMode('list')
          setEditingApp(null)
        }}
        isDarkMode={isDarkMode}
        isLoading={createMutation.isPending}
        error={createMutation.error}
      />
    )
  }

  if (viewMode === 'edit' && editingApp) {
    return (
      <div className="space-y-6">
        <OAuth2ApplicationForm
          application={editingApp}
          onSave={handleSave}
          onCancel={() => {
            setViewMode('list')
            setEditingApp(null)
          }}
          isDarkMode={isDarkMode}
          isLoading={updateMutation.isPending}
          error={updateMutation.error}
        />
        <ApplicationSecretsPanel
          serviceSlug={serviceSlug}
          appSlug={editingApp.slug}
          appType={editingApp.app_type}
          isDarkMode={isDarkMode}
        />
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
          Loading applications...
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
          <div className="font-medium">Failed to load applications</div>
          <div className="text-sm mt-1">{error instanceof Error ? error.message : 'An error occurred'}</div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
          {applications.length} application{applications.length !== 1 ? 's' : ''}
        </div>
        <Button
          onClick={() => {
            setEditingApp(null)
            setViewMode('create')
          }}
          size="sm"
          className="bg-[#2A4DD0] hover:bg-blue-700 text-white"
        >
          <Plus className="w-4 h-4 mr-2" />
          Add Application
        </Button>
      </div>

      {/* Table */}
      {applications.length === 0 ? (
        <div className={`text-center py-8 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
          <Key className="w-8 h-8 mx-auto mb-2 opacity-50" />
          <div>No applications registered</div>
          <div className="text-sm mt-1">Add an OAuth2 application to get started</div>
        </div>
      ) : (
        <div className={`rounded-lg border overflow-hidden ${
          isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
        }`}>
          <table className="w-full">
            <thead className={`border-b ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}>
              <tr>
                <th className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}>Application</th>
                <th className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}>Type</th>
                <th className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}>Client ID</th>
                <th className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}>Status</th>
                <th className={`px-6 py-3 text-right text-xs uppercase tracking-wider ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}>Actions</th>
              </tr>
            </thead>
            <tbody className={`divide-y ${isDarkMode ? 'divide-gray-700' : 'divide-gray-200'}`}>
              {applications.map((app) => {
                const statusColor = STATUS_COLORS[app.status] || STATUS_COLORS.inactive
                return (
                  <tr
                    key={app.slug}
                    className={`cursor-pointer ${isDarkMode ? 'hover:bg-gray-700/50' : 'hover:bg-gray-50'}`}
                    onClick={() => {
                      setEditingApp(app)
                      setViewMode('edit')
                    }}
                  >
                    <td className="px-6 py-4">
                      <div className={`font-medium ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
                        {app.name}
                      </div>
                      <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                        {app.slug}
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <code className={`px-2 py-1 rounded text-xs ${
                        isDarkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-700'
                      }`}>
                        {app.app_type}
                      </code>
                    </td>
                    <td className={`px-6 py-4 text-sm font-mono ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}>
                      {app.client_id}
                    </td>
                    <td className="px-6 py-4">
                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                        isDarkMode
                          ? `${statusColor.darkBg} ${statusColor.darkText}`
                          : `${statusColor.bg} ${statusColor.text}`
                      }`}>
                        {app.status}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-right" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-1">
                        {app.application_url && (
                          <a
                            href={app.application_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className={`inline-flex items-center p-1.5 rounded ${
                              isDarkMode
                                ? 'text-blue-400 hover:text-blue-300 hover:bg-blue-900/20'
                                : 'text-blue-600 hover:text-blue-700 hover:bg-blue-50'
                            }`}
                            title="Open application"
                          >
                            <ExternalLink className="w-4 h-4" />
                          </a>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Delete application ${app.name}`}
                          onClick={() => handleDelete(app)}
                          disabled={deleteMutation.isPending}
                          className={isDarkMode ? 'text-red-400 hover:text-red-300 hover:bg-red-900/20' : 'text-red-600 hover:text-red-700 hover:bg-red-50'}
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
