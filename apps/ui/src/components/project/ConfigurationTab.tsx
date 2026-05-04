import { useEffect, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Eye, EyeOff, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import {
  deleteConfigurationKey,
  fetchConfigurationValues,
  listConfigurationKeys,
  listProjectPlugins,
  setConfigurationValue,
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
import type { ConfigKeyResponse } from '@/types'

interface ConfigurationTabProps {
  environment?: string
  orgSlug: string
  projectId: string
}

const DATA_TYPES = ['String', 'StringList', 'SecureString'] as const

type DataType = (typeof DATA_TYPES)[number]

interface SetValueForm {
  data_type: DataType
  key: string
  secret: boolean
  value: string
}

export function ConfigurationTab({
  environment,
  orgSlug,
  projectId,
}: ConfigurationTabProps) {
  const queryClient = useQueryClient()
  const [source, setSource] = useState<string | undefined>()
  const [revealedValues, setRevealedValues] = useState<Record<string, unknown>>(
    {},
  )
  const [showSetDialog, setShowSetDialog] = useState(false)
  const [confirmDeleteKey, setConfirmDeleteKey] = useState<null | string>(null)
  const [editingKey, setEditingKey] = useState<ConfigKeyResponse | null>(null)
  const [form, setForm] = useState<SetValueForm>({
    data_type: 'String',
    key: '',
    secret: false,
    value: '',
  })

  const { data: assignments } = useQuery({
    queryFn: ({ signal }) => listProjectPlugins(orgSlug, projectId, signal),
    queryKey: ['project-plugins', orgSlug, projectId],
    staleTime: 5 * 60 * 1000,
  })

  const configAssignments =
    assignments?.filter((a) => a.tab === 'configuration') ?? []
  const sources = configAssignments.map((a) => ({
    id: a.plugin_id,
    label: a.label,
  }))
  const activeSource = sources.some((s) => s.id === source)
    ? source
    : sources[0]?.id

  useEffect(() => {
    setRevealedValues({})
  }, [activeSource, environment])

  const {
    data: keys,
    error,
    isLoading,
  } = useQuery({
    enabled: sources.length > 0,
    queryFn: ({ signal }) =>
      listConfigurationKeys(
        orgSlug,
        projectId,
        {
          environment: environment ?? undefined,
          source: activeSource,
        },
        signal,
      ),
    queryKey: ['config-keys', orgSlug, projectId, activeSource, environment],
    staleTime: 60 * 1000,
  })

  const revealMutation = useMutation({
    mutationFn: async (keyNames: string[]) => {
      return fetchConfigurationValues(orgSlug, projectId, keyNames, {
        environment: environment ?? undefined,
        source: activeSource,
      })
    },
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to reveal values')
    },
    onSuccess: (values) => {
      setRevealedValues((prev) => {
        const next = { ...prev }
        for (const v of values) next[v.key] = v.value
        return next
      })
    },
  })

  const setMutation = useMutation({
    mutationFn: () =>
      setConfigurationValue(
        orgSlug,
        projectId,
        form.key,
        {
          data_type: form.data_type,
          secret: form.secret,
          value: form.value,
        },
        {
          environment: environment ?? undefined,
          source: activeSource,
        },
      ),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to save value')
    },
    onSuccess: () => {
      toast.success(`Key "${form.key}" saved`)
      setShowSetDialog(false)
      setEditingKey(null)
      void queryClient.invalidateQueries({
        queryKey: ['config-keys', orgSlug, projectId],
      })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (key: string) =>
      deleteConfigurationKey(orgSlug, projectId, key, {
        environment: environment ?? undefined,
        source: activeSource,
      }),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to delete key')
    },
    onSuccess: (_, key) => {
      toast.success(`Key "${key}" deleted`)
      setConfirmDeleteKey(null)
      void queryClient.invalidateQueries({
        queryKey: ['config-keys', orgSlug, projectId],
      })
    },
  })

  const openAdd = () => {
    setEditingKey(null)
    setForm({ data_type: 'String', key: '', secret: false, value: '' })
    setShowSetDialog(true)
  }

  const openEdit = (keyEntry: ConfigKeyResponse) => {
    setEditingKey(keyEntry)
    setForm({
      data_type: (keyEntry.data_type as DataType) ?? 'String',
      key: keyEntry.key,
      secret: keyEntry.secret,
      value: '',
    })
    setShowSetDialog(true)
  }

  const toggleReveal = (key: string) => {
    if (key in revealedValues) {
      setRevealedValues((prev) => {
        const next = { ...prev }
        delete next[key]
        return next
      })
    } else {
      revealMutation.mutate([key])
    }
  }

  const revealAll = () => {
    const secretKeys = (keys ?? [])
      .filter((k) => k.secret && !(k.key in revealedValues))
      .map((k) => k.key)
    if (secretKeys.length > 0) {
      revealMutation.mutate(secretKeys)
    }
  }

  if (sources.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <CardTitle className="mb-2">No Configuration Plugin</CardTitle>
          <p className="text-sm text-secondary">
            No configuration plugin is assigned to this project. Configure
            plugins on the project type or in project settings.
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      {/* Source picker when multiple plugins assigned */}
      {sources.length > 1 && (
        <div className="flex items-center gap-3">
          <span className="text-sm text-secondary">Source:</span>
          <div className="flex gap-2">
            {sources.map((s) => (
              <Button
                className={
                  activeSource === s.id
                    ? 'bg-amber-bg text-amber-text hover:bg-amber-bg'
                    : ''
                }
                key={s.id}
                onClick={() => setSource(s.id)}
                size="sm"
                variant="outline"
              >
                {s.label}
              </Button>
            ))}
          </div>
        </div>
      )}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between px-6 py-4">
          <CardTitle>Configuration Keys</CardTitle>
          <div className="flex gap-2">
            {(keys ?? []).some((k) => k.secret) && (
              <Button onClick={revealAll} size="sm" variant="outline">
                <Eye className="mr-1 h-3 w-3" />
                Reveal All Secrets
              </Button>
            )}
            <Button onClick={openAdd} size="sm">
              <Plus className="mr-1 h-3 w-3" />
              Add Key
            </Button>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <LoadingState label="Loading..." />
          ) : error ? (
            <div className="py-8 text-center text-sm text-destructive">
              Failed to load configuration keys
            </div>
          ) : (keys ?? []).length === 0 ? (
            <div className="py-8 text-center text-sm text-secondary">
              No configuration keys found
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Key</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Last Modified</TableHead>
                  <TableHead>Value</TableHead>
                  <TableHead className="w-20" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {(keys ?? []).map((entry) => (
                  <TableRow key={entry.key}>
                    <TableCell className="font-mono text-sm">
                      {entry.key}
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary">{entry.data_type}</Badge>
                    </TableCell>
                    <TableCell className="text-sm text-secondary">
                      {entry.last_modified
                        ? new Date(entry.last_modified).toLocaleString()
                        : '—'}
                    </TableCell>
                    <TableCell>
                      {entry.secret ? (
                        <div className="flex items-center gap-2">
                          {entry.key in revealedValues ? (
                            <span className="font-mono text-sm">
                              {String(revealedValues[entry.key] ?? '')}
                            </span>
                          ) : (
                            <span className="text-secondary">••••••••</span>
                          )}
                          <Button
                            onClick={() => toggleReveal(entry.key)}
                            size="icon"
                            variant="ghost"
                          >
                            {entry.key in revealedValues ? (
                              <EyeOff className="h-3 w-3" />
                            ) : (
                              <Eye className="h-3 w-3" />
                            )}
                          </Button>
                        </div>
                      ) : (
                        <span className="text-secondary">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button
                          onClick={() => openEdit(entry)}
                          size="sm"
                          variant="ghost"
                        >
                          Edit
                        </Button>
                        <Button
                          onClick={() => setConfirmDeleteKey(entry.key)}
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

      <Dialog onOpenChange={setShowSetDialog} open={showSetDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingKey
                ? `Edit Key: ${editingKey.key}`
                : 'Add Configuration Key'}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            {!editingKey && (
              <div className="space-y-2">
                <Label htmlFor="cfg-key">Key</Label>
                <Input
                  id="cfg-key"
                  onChange={(e) =>
                    setForm((f) => ({ ...f, key: e.target.value }))
                  }
                  placeholder="/myapp/parameter"
                  value={form.key}
                />
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="cfg-type">Data Type</Label>
              <Select
                onValueChange={(v) =>
                  setForm((f) => ({
                    ...f,
                    data_type: v as DataType,
                    secret: v === 'SecureString',
                  }))
                }
                value={form.data_type}
              >
                <SelectTrigger id="cfg-type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DATA_TYPES.map((t) => (
                    <SelectItem key={t} value={t}>
                      {t}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="cfg-value">Value</Label>
              <Input
                id="cfg-value"
                onChange={(e) =>
                  setForm((f) => ({ ...f, value: e.target.value }))
                }
                placeholder={form.secret ? '••••••••' : 'value'}
                type={form.secret ? 'password' : 'text'}
                value={form.value}
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button onClick={() => setShowSetDialog(false)} variant="outline">
                Cancel
              </Button>
              <Button
                disabled={setMutation.isPending || !form.key || !form.value}
                onClick={() => setMutation.mutate()}
              >
                {setMutation.isPending ? 'Saving...' : 'Save'}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        description={`Delete key "${confirmDeleteKey ?? ''}"? This cannot be undone.`}
        onCancel={() => setConfirmDeleteKey(null)}
        onConfirm={() => {
          if (confirmDeleteKey) deleteMutation.mutate(confirmDeleteKey)
        }}
        open={confirmDeleteKey !== null}
        title="Delete Configuration Key"
      />
    </div>
  )
}
