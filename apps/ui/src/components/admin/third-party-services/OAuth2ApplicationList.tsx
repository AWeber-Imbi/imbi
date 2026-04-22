import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { extractApiErrorDetail } from '@/lib/apiError'
import { Plus, Trash2, Key, AlertCircle, ExternalLink } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  listServiceApplications,
  deleteServiceApplication,
  createServiceApplication,
  updateServiceApplication,
} from '@/api/endpoints'
import { OAuth2ApplicationForm } from './OAuth2ApplicationForm'
import { ApplicationSecretsPanel } from './ApplicationSecretsPanel'
import type {
  ServiceApplication,
  ServiceApplicationCreate,
  ServiceApplicationUpdate,
} from '@/types'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { statusBadgeVariant } from '@/lib/status-colors'
import { Badge } from '@/components/ui/badge'

type ViewMode = 'list' | 'create' | 'edit'

interface OAuth2ApplicationListProps {
  orgSlug: string
  serviceSlug: string
  onViewModeChange?: (mode: ViewMode) => void
}

export function OAuth2ApplicationList({
  orgSlug,
  serviceSlug,
  onViewModeChange,
}: OAuth2ApplicationListProps) {
  const queryClient = useQueryClient()
  const [viewMode, setViewModeInternal] = useState<ViewMode>('list')
  const [editingApp, setEditingApp] = useState<ServiceApplication | null>(null)
  const [confirm, setConfirm] = useState<{
    action: 'delete'
    appSlug: string
    appName: string
  } | null>(null)

  const setViewMode = (mode: ViewMode) => {
    setViewModeInternal(mode)
    onViewModeChange?.(mode)
  }

  const {
    data: applications = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ['service-applications', orgSlug, serviceSlug],
    queryFn: () => listServiceApplications(orgSlug, serviceSlug),
  })

  const createMutation = useMutation({
    mutationFn: (data: ServiceApplicationCreate) =>
      createServiceApplication(orgSlug, serviceSlug, data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['service-applications', orgSlug, serviceSlug],
      })
      setViewMode('list')
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({
      appSlug,
      data,
    }: {
      appSlug: string
      data: ServiceApplicationUpdate
    }) => updateServiceApplication(orgSlug, serviceSlug, appSlug, data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['service-applications', orgSlug, serviceSlug],
      })
      setViewMode('list')
      setEditingApp(null)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (appSlug: string) =>
      deleteServiceApplication(orgSlug, serviceSlug, appSlug),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['service-applications', orgSlug, serviceSlug],
      })
    },
    onError: (error: unknown) => {
      toast.error(
        `Failed to delete application: ${extractApiErrorDetail(error)}`,
      )
    },
  })

  const handleDelete = (app: ServiceApplication) => {
    setConfirm({ action: 'delete', appSlug: app.slug, appName: app.name })
  }

  const handleSave = (
    data: ServiceApplicationCreate | ServiceApplicationUpdate,
  ) => {
    if (viewMode === 'create') {
      createMutation.mutate(data as ServiceApplicationCreate)
    } else if (editingApp) {
      updateMutation.mutate({
        appSlug: editingApp.slug,
        data: data as ServiceApplicationUpdate,
      })
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
          isLoading={updateMutation.isPending}
          error={updateMutation.error}
        />
        <ApplicationSecretsPanel
          orgSlug={orgSlug}
          serviceSlug={serviceSlug}
          appSlug={editingApp.slug}
          appType={editingApp.app_type}
        />
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className="text-sm text-secondary">Loading applications...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-danger bg-danger p-4 text-danger">
        <AlertCircle className="h-5 w-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load applications</div>
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
        <div className="text-sm text-secondary">
          {applications.length} application
          {applications.length !== 1 ? 's' : ''}
        </div>
        <Button
          onClick={() => {
            setEditingApp(null)
            setViewMode('create')
          }}
          size="sm"
          className="bg-action text-action-foreground hover:bg-action-hover"
        >
          <Plus className="mr-2 h-4 w-4" />
          Add Application
        </Button>
      </div>

      {/* Table */}
      {applications.length === 0 ? (
        <div className="py-8 text-center text-tertiary">
          <Key className="mx-auto mb-2 h-8 w-8 opacity-50" />
          <div>No applications registered</div>
          <div className="mt-1 text-sm">
            Add an OAuth2 application to get started
          </div>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-border bg-card">
          <Table>
            <TableHeader className="border-b border-tertiary bg-secondary">
              <TableRow>
                <TableHead className="px-6 py-3 text-left text-xs uppercase tracking-wider text-tertiary">
                  Application
                </TableHead>
                <TableHead className="px-6 py-3 text-left text-xs uppercase tracking-wider text-tertiary">
                  Type
                </TableHead>
                <TableHead className="px-6 py-3 text-left text-xs uppercase tracking-wider text-tertiary">
                  Client ID
                </TableHead>
                <TableHead className="px-6 py-3 text-left text-xs uppercase tracking-wider text-tertiary">
                  Status
                </TableHead>
                <TableHead className="px-6 py-3 text-right text-xs uppercase tracking-wider text-tertiary">
                  Actions
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody className="divide-y divide-tertiary">
              {applications.map((app) => {
                const statusVariant = statusBadgeVariant(app.status)
                return (
                  <TableRow
                    key={app.slug}
                    className="hover:bg-secondary/50 cursor-pointer"
                    onClick={() => {
                      setEditingApp(app)
                      setViewMode('edit')
                    }}
                  >
                    <TableCell className="px-6 py-4">
                      <div className="font-medium text-primary">{app.name}</div>
                      <div className="text-sm text-tertiary">{app.slug}</div>
                    </TableCell>
                    <TableCell className="px-6 py-4">
                      <code className="rounded bg-secondary px-2 py-1 text-xs text-primary">
                        {app.app_type}
                      </code>
                    </TableCell>
                    <TableCell className="px-6 py-4 font-mono text-sm text-secondary">
                      {app.client_id}
                    </TableCell>
                    <TableCell className="px-6 py-4">
                      <Badge variant={statusVariant}>{app.status}</Badge>
                    </TableCell>
                    <TableCell
                      className="px-6 py-4 text-right"
                      onClick={(e) => e.stopPropagation()}
                      onKeyDown={(e) => e.stopPropagation()}
                    >
                      <div className="flex items-center justify-end gap-1">
                        {app.application_url && (
                          <TooltipProvider delayDuration={200}>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <a
                                  href={app.application_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  aria-label={`Open ${app.name} application`}
                                  className="inline-flex items-center rounded p-1.5 text-info hover:bg-info"
                                >
                                  <ExternalLink className="h-4 w-4" />
                                </a>
                              </TooltipTrigger>
                              <TooltipContent>
                                <p>Open application</p>
                              </TooltipContent>
                            </Tooltip>
                          </TooltipProvider>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Delete application ${app.name}`}
                          onClick={() => handleDelete(app)}
                          disabled={deleteMutation.isPending}
                          className="text-danger hover:bg-danger"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      )}
      <ConfirmDialog
        open={confirm?.action === 'delete'}
        title="Delete application"
        description={
          confirm?.action === 'delete'
            ? `Delete application "${confirm.appName}"? This cannot be undone.`
            : 'This action cannot be undone.'
        }
        confirmLabel="Delete"
        onConfirm={() => {
          if (confirm?.action === 'delete') {
            deleteMutation.mutate(confirm.appSlug)
          }
          setConfirm(null)
        }}
        onCancel={() => setConfirm(null)}
      />
    </div>
  )
}
