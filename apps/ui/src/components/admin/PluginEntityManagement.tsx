import { useEffect, useMemo, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import {
  createPluginEntity,
  deletePluginEntity,
  type DynamicFieldSchema,
  flattenNullableAnyOf,
  getPluginEntitySchema,
  listPluginEntities,
  updatePluginEntity,
} from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ErrorBanner } from '@/components/ui/error-banner'
import { Input } from '@/components/ui/input'
import { LoadingState } from '@/components/ui/loading-state'
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
import type {
  PluginEntity,
  PluginEntitySchema,
  PluginVertexLabel,
} from '@/types'

interface PluginEntityManagementProps {
  description?: string
  pluginName: string
  pluginSlug: string
  vertexLabel: PluginVertexLabel
}

const isScalarType = (type?: string) =>
  type === 'string' || type === 'integer' || type === 'number'

const editableProperties = (
  schema: PluginEntitySchema | undefined,
): { key: string; prop: DynamicFieldSchema; required: boolean }[] => {
  if (!schema?.properties) return []
  const required = new Set(schema.required ?? [])
  return Object.entries(schema.properties)
    .filter(([key]) => key !== 'id')
    .map(([key, raw]) => ({
      key,
      prop: flattenNullableAnyOf(raw),
      required: required.has(key),
    }))
    .filter(({ prop }) => isScalarType(prop.type) || prop.enum)
}

const toTitleCase = (key: string) =>
  key
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')

const formatCellValue = (value: unknown): string => {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export function PluginEntityManagement({
  description,
  pluginName,
  pluginSlug,
  vertexLabel,
}: PluginEntityManagementProps) {
  const queryClient = useQueryClient()
  const label = vertexLabel.name
  const queryKey = useMemo(
    () => queryKeys.pluginEntities(pluginSlug, label),
    [pluginSlug, label],
  )
  const schemaKey = useMemo(
    () => queryKeys.pluginEntitySchema(pluginSlug, label),
    [pluginSlug, label],
  )

  const entitiesQuery = useQuery<PluginEntity[]>({
    queryFn: ({ signal }) => listPluginEntities(pluginSlug, label, signal),
    queryKey,
    staleTime: 30 * 1000,
  })
  const schemaQuery = useQuery<PluginEntitySchema>({
    queryFn: ({ signal }) => getPluginEntitySchema(pluginSlug, label, signal),
    queryKey: schemaKey,
    staleTime: 5 * 60 * 1000,
  })

  const properties = editableProperties(schemaQuery.data)

  const [editing, setEditing] = useState<null | PluginEntity>(null)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState<Record<string, string>>({})
  const [pendingDelete, setPendingDelete] = useState<null | PluginEntity>(null)

  useEffect(() => {
    if (editing) {
      const next: Record<string, string> = {}
      for (const { key } of properties) {
        const value = editing[key]
        next[key] = value === null || value === undefined ? '' : String(value)
      }
      setForm(next)
    } else if (!creating) {
      setForm({})
    } else {
      const next: Record<string, string> = {}
      for (const { key } of properties) next[key] = ''
      setForm(next)
    }
  }, [creating, editing, properties])

  const createMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      createPluginEntity(pluginSlug, label, body),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? `Failed to create ${label}`)
    },
    onSuccess: () => {
      toast.success(`${label} added`)
      setCreating(false)
      void queryClient.invalidateQueries({ queryKey })
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ body, id }: { body: Record<string, unknown>; id: string }) =>
      updatePluginEntity(pluginSlug, label, id, body),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? `Failed to update ${label}`)
    },
    onSuccess: () => {
      toast.success(`${label} updated`)
      setEditing(null)
      void queryClient.invalidateQueries({ queryKey })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deletePluginEntity(pluginSlug, label, id),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? `Failed to delete ${label}`)
    },
    onSuccess: () => {
      toast.success(`${label} removed`)
      setPendingDelete(null)
      void queryClient.invalidateQueries({ queryKey })
    },
  })

  if (entitiesQuery.isLoading || schemaQuery.isLoading) {
    return <LoadingState label={`Loading ${label}…`} />
  }
  if (entitiesQuery.isError) {
    return (
      <ErrorBanner
        message={
          extractApiErrorDetail(entitiesQuery.error) ??
          `Failed to load ${label}`
        }
        title={`Couldn't load ${label}`}
      />
    )
  }
  if (schemaQuery.isError) {
    return (
      <ErrorBanner
        message={
          extractApiErrorDetail(schemaQuery.error) ??
          `Failed to load ${label} schema`
        }
        title={`Couldn't load ${label} schema`}
      />
    )
  }

  const entities = entitiesQuery.data ?? []
  const dialogOpen = creating || editing !== null
  const submitting = createMutation.isPending || updateMutation.isPending
  const headerProps = properties.slice(0, 4)

  const submit = () => {
    const body: Record<string, unknown> = {}
    for (const { key, prop, required } of properties) {
      const raw = form[key] ?? ''
      const trimmed = raw.trim()
      if (trimmed === '') {
        if (required) {
          toast.error(`${prop.title || toTitleCase(key)} is required`)
          return
        }
        body[key] = null
        continue
      }
      if (prop.type === 'integer') {
        const parsed = Number.parseInt(trimmed, 10)
        if (Number.isNaN(parsed)) {
          toast.error(`${prop.title || toTitleCase(key)} must be an integer`)
          return
        }
        body[key] = parsed
      } else if (prop.type === 'number') {
        const parsed = Number.parseFloat(trimmed)
        if (Number.isNaN(parsed)) {
          toast.error(`${prop.title || toTitleCase(key)} must be a number`)
          return
        }
        body[key] = parsed
      } else {
        body[key] = trimmed
      }
    }
    if (editing) {
      updateMutation.mutate({ body, id: editing.id })
    } else {
      createMutation.mutate(body)
    }
  }

  const displayName = vertexLabel.display_name || label
  const headerSubtitle =
    vertexLabel.description ?? description ?? `${pluginName}: ${label}`

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-medium text-primary">{displayName}</h2>
          {headerSubtitle && (
            <p className="mt-1 text-sm text-secondary">{headerSubtitle}</p>
          )}
        </div>
        <Button onClick={() => setCreating(true)}>
          <Plus className="mr-2 h-4 w-4" />
          Add {displayName}
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                {headerProps.map(({ key, prop }) => (
                  <TableHead key={key}>
                    {prop.title || toTitleCase(key)}
                  </TableHead>
                ))}
                <TableHead className="w-32 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {entities.length === 0 ? (
                <TableRow>
                  <TableCell
                    className="py-8 text-center text-sm text-secondary"
                    colSpan={headerProps.length + 1}
                  >
                    No {label} records yet.
                  </TableCell>
                </TableRow>
              ) : (
                entities.map((entity) => (
                  <TableRow key={entity.id}>
                    {headerProps.map(({ key }) => (
                      <TableCell className="text-sm" key={key}>
                        {formatCellValue(entity[key])}
                      </TableCell>
                    ))}
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          aria-label={`Edit ${label}`}
                          onClick={() => setEditing(entity)}
                          size="sm"
                          variant="ghost"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          aria-label={`Delete ${label}`}
                          onClick={() => setPendingDelete(entity)}
                          size="sm"
                          variant="ghost"
                        >
                          <Trash2 className="h-3.5 w-3.5 text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog
        onOpenChange={(next) => {
          if (!next) {
            setCreating(false)
            setEditing(null)
          }
        }}
        open={dialogOpen}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {editing ? `Edit ${label}` : `Add ${label}`}
            </DialogTitle>
            <DialogDescription>
              {editing
                ? `Update this ${label} record.`
                : `Create a new ${label}.`}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            {properties.map(({ key, prop, required }) => (
              <label className="block text-sm" key={key}>
                <span className="text-secondary">
                  {prop.title || toTitleCase(key)}
                  {required && <span className="text-red-500"> *</span>}
                </span>
                <Input
                  onChange={(e) =>
                    setForm((f) => ({ ...f, [key]: e.target.value }))
                  }
                  value={form[key] ?? ''}
                />
                {prop.description && (
                  <p className="mt-1 text-xs text-tertiary">
                    {prop.description}
                  </p>
                )}
              </label>
            ))}
          </div>

          <DialogFooter>
            <Button
              onClick={() => {
                setCreating(false)
                setEditing(null)
              }}
              variant="outline"
            >
              Cancel
            </Button>
            <Button disabled={submitting} onClick={submit}>
              {editing ? 'Save changes' : `Add ${label}`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        confirmLabel="Delete"
        description={
          pendingDelete
            ? `Delete this ${label}? Any edges into it will be removed.`
            : ''
        }
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => {
          if (pendingDelete) deleteMutation.mutate(pendingDelete.id)
        }}
        open={pendingDelete !== null}
        title={`Delete ${label}?`}
      />
    </div>
  )
}
