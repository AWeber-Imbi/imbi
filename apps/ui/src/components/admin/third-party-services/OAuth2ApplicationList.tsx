import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  ExternalLink,
  Globe,
  Key,
  Plus,
  Trash2,
} from 'lucide-react'
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
      listServiceApplications(orgSlug, serviceSlug, 'integration', signal),
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
        <div className="text-secondary text-sm">Loading applications...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="border-danger bg-danger text-danger flex items-center gap-3 rounded-lg border p-4">
        <AlertCircle className="size-5 shrink-0" />
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
        <div className="text-secondary text-sm">
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
          <Plus className="mr-2 size-4" />
          Add Application
        </Button>
      </div>

      {/* Table */}
      {applications.length === 0 ? (
        <div className="text-tertiary py-8 text-center">
          <Key className="mx-auto mb-2 size-8 opacity-50" />
          <div>No applications registered</div>
          <div className="mt-1 text-sm">
            Add an OAuth2 application to get started
          </div>
        </div>
      ) : (
        <div className="border-border bg-card overflow-hidden rounded-lg border">
          <Table>
            <TableHeader className="border-tertiary bg-secondary border-b">
              <TableRow>
                <TableHead className="text-tertiary px-6 py-3 text-left text-xs tracking-wider uppercase">
                  Application
                </TableHead>
                <TableHead className="text-tertiary px-6 py-3 text-left text-xs tracking-wider uppercase">
                  Type
                </TableHead>
                <TableHead className="text-tertiary px-6 py-3 text-left text-xs tracking-wider uppercase">
                  Client ID
                </TableHead>
                <TableHead className="text-tertiary px-6 py-3 text-left text-xs tracking-wider uppercase">
                  Status
                </TableHead>
                <TableHead className="text-tertiary px-6 py-3 text-right text-xs tracking-wider uppercase">
                  Actions
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody className="divide-tertiary divide-y">
              {applications.map((app) => {
                const statusVariant = statusBadgeVariant(app.status)
                const isGlobal = app.is_global === true
                return (
                  <TableRow
                    className={`${isGlobal ? '' : 'cursor-pointer'} hover:bg-secondary/50`}
                    key={app.slug}
                    onClick={() => {
                      if (isGlobal) return
                      setEditingApp(app)
                      setViewMode('edit')
                    }}
                  >
                    <TableCell className="px-6 py-4">
                      <div className="text-primary flex items-center gap-2 font-medium">
                        {app.name}
                        {isGlobal && (
                          <TooltipProvider delayDuration={200}>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Badge
                                  className="inline-flex items-center gap-1"
                                  variant="info"
                                >
                                  <Globe className="size-3" />
                                  global
                                </Badge>
                              </TooltipTrigger>
                              <TooltipContent>
                                <p>Managed in Auth Providers</p>
                              </TooltipContent>
                            </Tooltip>
                          </TooltipProvider>
                        )}
                      </div>
                      <div className="text-tertiary text-sm">{app.slug}</div>
                    </TableCell>
                    <TableCell className="px-6 py-4">
                      <code className="bg-secondary text-primary rounded px-2 py-1 text-xs">
                        {app.app_type}
                      </code>
                    </TableCell>
                    <TableCell className="text-secondary px-6 py-4 font-mono text-sm">
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
                                  className="text-info hover:bg-info inline-flex items-center rounded p-1.5"
                                  href={app.application_url}
                                  rel="noopener noreferrer"
                                  target="_blank"
                                >
                                  <ExternalLink className="size-4" />
                                </a>
                              </TooltipTrigger>
                              <TooltipContent>
                                <p>Open application</p>
                              </TooltipContent>
                            </Tooltip>
                          </TooltipProvider>
                        )}
                        {isGlobal ? (
                          <TooltipProvider delayDuration={200}>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <span>
                                  <Button
                                    aria-label="Managed in Auth Providers"
                                    className="text-tertiary"
                                    disabled
                                    size="sm"
                                    variant="ghost"
                                  >
                                    <Trash2 className="size-4" />
                                  </Button>
                                </span>
                              </TooltipTrigger>
                              <TooltipContent>
                                <p>Managed in Auth Providers</p>
                              </TooltipContent>
                            </Tooltip>
                          </TooltipProvider>
                        ) : (
                          <Button
                            aria-label={`Delete application ${app.name}`}
                            className="text-danger hover:bg-danger"
                            disabled={deleteMutation.isPending}
                            onClick={() => handleDelete(app)}
                            size="sm"
                            variant="ghost"
                          >
                            <Trash2 className="size-4" />
                          </Button>
                        )}
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
