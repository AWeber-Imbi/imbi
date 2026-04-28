import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, ExternalLink, Key, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import {
  createServiceApplication,
  deleteServiceApplication,
  listServiceApplications,
  updateServiceApplication,
} from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
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
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { extractApiErrorDetail } from '@/lib/apiError'
import { buildDiffPatch } from '@/lib/json-patch'
import { statusBadgeVariant } from '@/lib/status-colors'
import type {
  PatchOperation,
  ServiceApplication,
  ServiceApplicationCreate,
  ServiceApplicationUpdate,
} from '@/types'

import { ApplicationSecretsPanel } from './ApplicationSecretsPanel'
import { OAuth2ApplicationForm } from './OAuth2ApplicationForm'

interface OAuth2ApplicationListProps {
  onViewModeChange?: (mode: ViewMode) => void
  orgSlug: string
  serviceSlug: string
}

type ViewMode = 'create' | 'edit' | 'list'

export function OAuth2ApplicationList({
  onViewModeChange,
  orgSlug,
  serviceSlug,
}: OAuth2ApplicationListProps) {
  const queryClient = useQueryClient()
  const [viewMode, setViewModeInternal] = useState<ViewMode>('list')
  const [editingApp, setEditingApp] = useState<null | ServiceApplication>(null)
  const [confirm, setConfirm] = useState<null | {
    action: 'delete'
    appName: string
    appSlug: string
  }>(null)

  const setViewMode = (mode: ViewMode) => {
    setViewModeInternal(mode)
    onViewModeChange?.(mode)
  }

  const {
    data: applications = [],
    error,
    isLoading,
  } = useQuery({
    queryFn: ({ signal }) =>
      listServiceApplications(orgSlug, serviceSlug, signal),
    queryKey: ['service-applications', orgSlug, serviceSlug],
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
      operations,
    }: {
      appSlug: string
      operations: PatchOperation[]
    }) => updateServiceApplication(orgSlug, serviceSlug, appSlug, operations),
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
    onError: (error: unknown) => {
      toast.error(
        `Failed to delete application: ${extractApiErrorDetail(error)}`,
      )
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['service-applications', orgSlug, serviceSlug],
      })
    },
  })

  const handleDelete = (app: ServiceApplication) => {
    setConfirm({ action: 'delete', appName: app.name, appSlug: app.slug })
  }

  const handleSave = (
    data: ServiceApplicationCreate | ServiceApplicationUpdate,
  ) => {
    if (viewMode === 'create') {
      createMutation.mutate(data as ServiceApplicationCreate)
    } else if (editingApp) {
      const updateData = data as ServiceApplicationUpdate
      const operations = buildDiffPatch(
        editingApp as unknown as Record<string, unknown>,
        updateData as unknown as Record<string, unknown>,
        { fields: Object.keys(updateData) },
      )
      if (operations.length === 0) {
        setViewMode('list')
        setEditingApp(null)
        return
      }
      updateMutation.mutate({ appSlug: editingApp.slug, operations })
    }
  }

  if (viewMode === 'create') {
    return (
      <OAuth2ApplicationForm
        application={null}
        error={createMutation.error}
        isLoading={createMutation.isPending}
        onCancel={() => {
          setViewMode('list')
          setEditingApp(null)
        }}
        onSave={handleSave}
      />
    )
  }

  if (viewMode === 'edit' && editingApp) {
    return (
      <div className="space-y-6">
        <OAuth2ApplicationForm
          application={editingApp}
          error={updateMutation.error}
          isLoading={updateMutation.isPending}
          onCancel={() => {
            setViewMode('list')
            setEditingApp(null)
          }}
          onSave={handleSave}
        />
        <ApplicationSecretsPanel
          appSlug={editingApp.slug}
          appType={editingApp.app_type}
          orgSlug={orgSlug}
          serviceSlug={serviceSlug}
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
          className="bg-action text-action-foreground hover:bg-action-hover"
          onClick={() => {
            setEditingApp(null)
            setViewMode('create')
          }}
          size="sm"
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
                    className="hover:bg-secondary/50 cursor-pointer"
                    key={app.slug}
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
                                  aria-label={`Open ${app.name} application`}
                                  className="inline-flex items-center rounded p-1.5 text-info hover:bg-info"
                                  href={app.application_url}
                                  rel="noopener noreferrer"
                                  target="_blank"
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
                          aria-label={`Delete application ${app.name}`}
                          className="text-danger hover:bg-danger"
                          disabled={deleteMutation.isPending}
                          onClick={() => handleDelete(app)}
                          size="sm"
                          variant="ghost"
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
        confirmLabel="Delete"
        description={
          confirm?.action === 'delete'
            ? `Delete application "${confirm.appName}"? This cannot be undone.`
            : 'This action cannot be undone.'
        }
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          if (confirm?.action === 'delete') {
            deleteMutation.mutate(confirm.appSlug)
          }
          setConfirm(null)
        }}
        open={confirm?.action === 'delete'}
        title="Delete application"
      />
    </div>
  )
}
