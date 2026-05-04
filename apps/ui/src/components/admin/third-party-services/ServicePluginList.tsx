import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import {
  createServicePlugin,
  deleteServicePlugin,
  getAdminPlugins,
  listServicePlugins,
  updateServicePlugin,
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
import { Textarea } from '@/components/ui/textarea'
import { extractApiErrorDetail } from '@/lib/apiError'
import type { PluginResponse } from '@/types'

interface PluginForm {
  label: string
  options: string
  plugin_slug: string
}

interface ServicePluginListProps {
  orgSlug: string
  serviceSlug: string
}

export function ServicePluginList({
  orgSlug,
  serviceSlug,
}: ServicePluginListProps) {
  const queryClient = useQueryClient()
  const [showDialog, setShowDialog] = useState(false)
  const [confirmDeleteId, setConfirmDeleteId] = useState<null | string>(null)
  const [editingPlugin, setEditingPlugin] = useState<null | PluginResponse>(
    null,
  )
  const [form, setForm] = useState<PluginForm>({
    label: '',
    options: '{}',
    plugin_slug: '',
  })
  const [optionsError, setOptionsError] = useState('')

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
    queryKey: ['admin-plugins'],
    staleTime: 5 * 60 * 1000,
  })

  const installedPlugins = adminPlugins?.installed ?? []

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

  const updateMutation = useMutation({
    mutationFn: (input: {
      id: string
      label: string
      options: Record<string, unknown>
    }) =>
      updateServicePlugin(orgSlug, serviceSlug, input.id, {
        label: input.label,
        options: input.options,
      }),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to update plugin')
    },
    onSuccess: () => {
      toast.success('Plugin updated')
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
    setEditingPlugin(null)
    setForm({ label: '', options: '{}', plugin_slug: '' })
    setOptionsError('')
    setShowDialog(true)
  }

  const openEdit = (plugin: PluginResponse) => {
    setEditingPlugin(plugin)
    setForm({
      label: plugin.label,
      options: JSON.stringify(plugin.options, null, 2),
      plugin_slug: plugin.plugin_slug,
    })
    setOptionsError('')
    setShowDialog(true)
  }

  const handleSubmit = () => {
    let options: Record<string, unknown>
    try {
      const parsed: unknown = JSON.parse(form.options)
      if (
        parsed === null ||
        typeof parsed !== 'object' ||
        Array.isArray(parsed)
      ) {
        setOptionsError('Options must be a JSON object')
        return
      }
      options = parsed as Record<string, unknown>
      setOptionsError('')
    } catch {
      setOptionsError('Invalid JSON')
      return
    }
    if (editingPlugin) {
      updateMutation.mutate({
        id: editingPlugin.id,
        label: form.label,
        options,
      })
    } else {
      createMutation.mutate({
        label: form.label,
        options,
        plugin_slug: form.plugin_slug,
      })
    }
  }

  const isPending = createMutation.isPending || updateMutation.isPending

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
                  <TableHead className="w-20" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {(plugins ?? []).map((plugin) => (
                  <TableRow key={plugin.id}>
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
                      <div className="flex justify-end gap-1">
                        <Button
                          onClick={() => openEdit(plugin)}
                          size="sm"
                          variant="ghost"
                        >
                          Edit
                        </Button>
                        <Button
                          aria-label={`Remove ${plugin.label}`}
                          onClick={() => setConfirmDeleteId(plugin.id)}
                          size="icon"
                          variant="ghost"
                        >
                          <Trash2 className="h-3 w-3 text-destructive" />
                        </Button>
                      </div>
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
            <DialogTitle>
              {editingPlugin
                ? `Edit Plugin: ${editingPlugin.label}`
                : 'Add Plugin'}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            {!editingPlugin && isAdminPluginsError && (
              <div className="text-sm text-destructive">
                {extractApiErrorDetail(adminPluginsError) ??
                  'Failed to load installed plugins'}
              </div>
            )}
            {!editingPlugin && (
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
            )}
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
            <div className="space-y-2">
              <Label htmlFor="plugin-options">Options (JSON)</Label>
              <Textarea
                className="font-mono"
                id="plugin-options"
                onChange={(e) =>
                  setForm((f) => ({ ...f, options: e.target.value }))
                }
                rows={4}
                value={form.options}
              />
              {optionsError && (
                <p className="text-xs text-destructive">{optionsError}</p>
              )}
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button onClick={() => setShowDialog(false)} variant="outline">
                Cancel
              </Button>
              <Button
                disabled={
                  isPending ||
                  !form.label ||
                  (!editingPlugin && !form.plugin_slug)
                }
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
