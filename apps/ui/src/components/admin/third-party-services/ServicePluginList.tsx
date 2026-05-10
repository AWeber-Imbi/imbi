import { useEffect, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ChevronRight, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import {
  createServicePlugin,
  deleteServicePlugin,
  getAdminPlugins,
  listServicePlugins,
} from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { LoadingState } from '@/components/ui/loading-state'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { extractApiErrorDetail } from '@/lib/apiError'
import { queryKeys } from '@/lib/queryKeys'

import { ServicePluginConfiguration } from './ServicePluginConfiguration'

interface PluginForm {
  label: string
  plugin_slug: string
}

interface ServicePluginListProps {
  onViewModeChange?: (mode: 'configure' | 'list') => void
  orgSlug: string
  serviceSlug: string
}

export function ServicePluginList({
  onViewModeChange,
  orgSlug,
  serviceSlug,
}: ServicePluginListProps) {
  const queryClient = useQueryClient()
  const [showDialog, setShowDialog] = useState(false)
  const [confirmDeleteId, setConfirmDeleteId] = useState<null | string>(null)
  const [form, setForm] = useState<PluginForm>({
    label: '',
    plugin_slug: '',
  })

  const {
    data: plugins,
    error: pluginsError,
    isError: isPluginsError,
    isLoading,
  } = useQuery({
    queryFn: ({ signal }) => listServicePlugins(orgSlug, serviceSlug, signal),
    queryKey: ['service-plugins', orgSlug, serviceSlug],
    staleTime: 60 * 1000,
  })

  const {
    data: adminPlugins,
    error: adminPluginsError,
    isError: isAdminPluginsError,
  } = useQuery({
    queryFn: ({ signal }) => getAdminPlugins(signal),
    queryKey: queryKeys.adminPlugins(),
    staleTime: 5 * 60 * 1000,
  })

  // Only enabled plugins should be assignable to a service.
  const installedPlugins = (adminPlugins?.installed ?? []).filter(
    (p) => p.enabled,
  )
  const [configurePluginId, setConfigurePluginId] = useState<null | string>(
    null,
  )
  const configurePlugin =
    (plugins ?? []).find((p) => p.id === configurePluginId) ?? null

  useEffect(() => {
    onViewModeChange?.(configurePluginId ? 'configure' : 'list')
  }, [configurePluginId, onViewModeChange])

  const createMutation = useMutation({
    mutationFn: (input: {
      label: string
      options: Record<string, unknown>
      plugin_slug: string
    }) => createServicePlugin(orgSlug, serviceSlug, input),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to create plugin')
    },
    onSuccess: () => {
      toast.success('Plugin created')
      setShowDialog(false)
      void queryClient.invalidateQueries({
        queryKey: ['service-plugins', orgSlug, serviceSlug],
      })
      void queryClient.invalidateQueries({
        queryKey: ['project-plugins', orgSlug],
      })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (pluginId: string) =>
      deleteServicePlugin(orgSlug, serviceSlug, pluginId),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to delete plugin')
    },
    onSuccess: () => {
      toast.success('Plugin removed')
      setConfirmDeleteId(null)
      void queryClient.invalidateQueries({
        queryKey: ['service-plugins', orgSlug, serviceSlug],
      })
      void queryClient.invalidateQueries({
        queryKey: ['project-plugins', orgSlug],
      })
    },
  })

  const openAdd = () => {
    setForm({ label: '', plugin_slug: '' })
    setShowDialog(true)
  }

  const handleSubmit = () => {
    createMutation.mutate({
      label: form.label,
      options: {},
      plugin_slug: form.plugin_slug,
    })
  }

  const isPending = createMutation.isPending

  if (configurePlugin) {
    return (
      <ServicePluginConfiguration
        onBack={() => setConfigurePluginId(null)}
        orgSlug={orgSlug}
        plugin={configurePlugin}
        serviceSlug={serviceSlug}
      />
    )
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between px-6 py-4">
          <CardTitle>Plugins</CardTitle>
          <Button
            disabled={installedPlugins.length === 0}
            onClick={openAdd}
            size="sm"
          >
            <Plus className="mr-1 h-3 w-3" />
            Add Plugin
          </Button>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <LoadingState label="Loading..." />
          ) : isPluginsError ? (
            <div className="py-8 text-center text-sm text-destructive">
              {extractApiErrorDetail(pluginsError) ?? 'Failed to load plugins'}
            </div>
          ) : (plugins ?? []).length === 0 ? (
            <div className="py-8 text-center text-sm text-secondary">
              No plugins configured. Add a plugin to enable configuration or log
              access for projects using this service.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Label</TableHead>
                  <TableHead>Plugin</TableHead>
                  <TableHead>Version</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-12" />
                  <TableHead className="w-12" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {(plugins ?? []).map((plugin) => (
                  <TableRow
                    className="hover:bg-secondary/40 cursor-pointer"
                    key={plugin.id}
                    onClick={() => setConfigurePluginId(plugin.id)}
                  >
                    <TableCell className="font-medium">
                      {plugin.label}
                    </TableCell>
                    <TableCell>
                      <code className="rounded bg-secondary px-1.5 py-0.5 text-xs">
                        {plugin.plugin_slug}
                      </code>
                    </TableCell>
                    <TableCell className="text-sm text-secondary">
                      v{plugin.api_version}
                    </TableCell>
                    <TableCell>
                      {plugin.status === 'unavailable' ? (
                        <Badge
                          className="flex w-fit items-center gap-1"
                          variant="destructive"
                        >
                          <AlertTriangle className="h-3 w-3" />
                          Unavailable
                        </Badge>
                      ) : (
                        <Badge variant="secondary">Active</Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      <Button
                        aria-label={`Remove ${plugin.label}`}
                        onClick={(e) => {
                          e.stopPropagation()
                          setConfirmDeleteId(plugin.id)
                        }}
                        size="icon"
                        variant="ghost"
                      >
                        <Trash2 className="h-3 w-3 text-destructive" />
                      </Button>
                    </TableCell>
                    <TableCell>
                      <ChevronRight className="h-4 w-4 text-tertiary" />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog onOpenChange={setShowDialog} open={showDialog}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Add Plugin</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            {isAdminPluginsError && (
              <div className="text-sm text-destructive">
                {extractApiErrorDetail(adminPluginsError) ??
                  'Failed to load installed plugins'}
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="plugin-slug">Plugin</Label>
              <Select
                onValueChange={(v) =>
                  setForm((f) => ({ ...f, plugin_slug: v }))
                }
                value={form.plugin_slug}
              >
                <SelectTrigger id="plugin-slug">
                  <SelectValue placeholder="Select installed plugin…" />
                </SelectTrigger>
                <SelectContent>
                  {installedPlugins.map((p) => (
                    <SelectItem key={p.slug} value={p.slug}>
                      {p.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="plugin-label">Label</Label>
              <Input
                id="plugin-label"
                onChange={(e) =>
                  setForm((f) => ({ ...f, label: e.target.value }))
                }
                placeholder="Production SSM"
                value={form.label}
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button onClick={() => setShowDialog(false)} variant="outline">
                Cancel
              </Button>
              <Button
                disabled={isPending || !form.label || !form.plugin_slug}
                onClick={handleSubmit}
              >
                {isPending ? 'Saving...' : 'Save'}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        description={`Remove this plugin? Projects assigned to it will lose access.`}
        onCancel={() => setConfirmDeleteId(null)}
        onConfirm={() => {
          if (confirmDeleteId) deleteMutation.mutate(confirmDeleteId)
        }}
        open={confirmDeleteId !== null}
        title="Remove Plugin"
      />
    </div>
  )
}
