import { useEffect, useMemo, useRef, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, CirclePlay, PowerOff, RotateCcw } from 'lucide-react'
import { toast } from 'sonner'

import {
  type AdminPluginPatch,
  getAdminPlugin,
  setAdminPluginEnabled,
  updateAdminPlugin,
} from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { ErrorBanner } from '@/components/ui/error-banner'
import { Input } from '@/components/ui/input'
import { LoadingState } from '@/components/ui/loading-state'
import { Textarea } from '@/components/ui/textarea'
import { extractApiErrorDetail } from '@/lib/apiError'
import { queryKeys } from '@/lib/queryKeys'
import type { InstalledPlugin, PluginVertexLabel } from '@/types'

import { PluginEntityManagement } from './PluginEntityManagement'

interface PluginPackageDetailProps {
  onBack: () => void
  slug: string
}

type VertexFormMap = Record<string, VertexFormState>

interface VertexFormState {
  description: string
  display_name: string
  nav_label: string
}

const VERTEX_FIELDS: (keyof VertexFormState)[] = [
  'display_name',
  'nav_label',
  'description',
]

const initialVertexForm = (
  vertex_labels: PluginVertexLabel[] | undefined,
): VertexFormMap => {
  const out: VertexFormMap = {}
  for (const v of vertex_labels ?? []) {
    out[v.name] = {
      description: v.overrides?.description ?? '',
      display_name: v.overrides?.display_name ?? '',
      nav_label: v.overrides?.nav_label ?? '',
    }
  }
  return out
}

export function PluginPackageDetail({
  onBack,
  slug,
}: PluginPackageDetailProps) {
  const queryClient = useQueryClient()

  const pluginQuery = useQuery<InstalledPlugin>({
    queryFn: ({ signal }) => getAdminPlugin(slug, signal),
    queryKey: queryKeys.adminPlugin(slug),
    staleTime: 30 * 1000,
  })

  const [widgetText, setWidgetText] = useState('')
  const [vertexForm, setVertexForm] = useState<VertexFormMap>({})
  const [confirmDisableOpen, setConfirmDisableOpen] = useState(false)

  // Initialize on first arrival, then again only when the server-known
  // override actually changes — otherwise a background refetch would
  // clobber in-flight user edits.
  const lastWidgetServerValue = useRef<null | string>(null)
  const lastOverridesSerialized = useRef<null | string>(null)
  useEffect(() => {
    const data = pluginQuery.data
    if (!data) return
    const widgetServer = data.widget_text_override ?? null
    if (widgetServer !== lastWidgetServerValue.current) {
      lastWidgetServerValue.current = widgetServer
      setWidgetText(widgetServer ?? '')
    }
    const overridesKey = JSON.stringify(
      (data.vertex_labels ?? []).map((v) => [v.name, v.overrides]),
    )
    if (overridesKey !== lastOverridesSerialized.current) {
      lastOverridesSerialized.current = overridesKey
      setVertexForm(initialVertexForm(data.vertex_labels))
    }
  }, [pluginQuery.data])

  const widgetDirty = useMemo(() => {
    if (!pluginQuery.data) return false
    const current = pluginQuery.data.widget_text_override ?? ''
    return widgetText !== current
  }, [widgetText, pluginQuery.data])

  const vertexDirty = useMemo(() => {
    if (!pluginQuery.data) return new Set<string>()
    const dirty = new Set<string>()
    for (const v of pluginQuery.data.vertex_labels ?? []) {
      const current = {
        description: v.overrides?.description ?? '',
        display_name: v.overrides?.display_name ?? '',
        nav_label: v.overrides?.nav_label ?? '',
      }
      const draft = vertexForm[v.name] ?? current
      if (
        draft.display_name !== current.display_name ||
        draft.nav_label !== current.nav_label ||
        draft.description !== current.description
      ) {
        dirty.add(v.name)
      }
    }
    return dirty
  }, [vertexForm, pluginQuery.data])

  const patchMutation = useMutation({
    mutationFn: (body: AdminPluginPatch) => updateAdminPlugin(slug, body),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to save')
    },
    onSuccess: (data) => {
      toast.success('Saved')
      queryClient.setQueryData(queryKeys.adminPlugin(slug), data)
      void queryClient.invalidateQueries({
        queryKey: queryKeys.adminPlugins(),
      })
    },
  })

  const enabledMutation = useMutation({
    mutationFn: (enabled: boolean) => setAdminPluginEnabled(slug, enabled),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to update plugin state')
    },
    onSuccess: (data, enabled) => {
      toast.success(enabled ? `${slug} enabled` : `${slug} disabled`)
      queryClient.setQueryData(queryKeys.adminPlugin(slug), data)
      void queryClient.invalidateQueries({
        queryKey: queryKeys.adminPlugins(),
      })
      setConfirmDisableOpen(false)
    },
  })

  if (pluginQuery.isLoading) {
    return <LoadingState label="Loading plugin…" />
  }
  if (pluginQuery.isError || !pluginQuery.data) {
    return (
      <ErrorBanner
        message={
          extractApiErrorDetail(pluginQuery.error) ?? 'Failed to load plugin'
        }
        title="Couldn't load plugin"
      />
    )
  }

  const plugin = pluginQuery.data

  const saveWidgetText = () => {
    const trimmed = widgetText.trim()
    patchMutation.mutate({ widget_text: trimmed === '' ? null : trimmed })
  }
  const resetWidgetText = () => {
    patchMutation.mutate({ widget_text: null })
    setWidgetText('')
  }

  const saveVertex = (label: string) => {
    const draft = vertexForm[label]
    if (!draft) return
    const fields: Record<string, null | string> = {}
    for (const key of VERTEX_FIELDS) {
      const value = draft[key].trim()
      fields[key] = value === '' ? null : value
    }
    patchMutation.mutate({ vertex_label_overrides: { [label]: fields } })
  }
  const resetVertex = (label: string) => {
    patchMutation.mutate({ vertex_label_overrides: { [label]: {} } })
    setVertexForm((s) => ({
      ...s,
      [label]: { description: '', display_name: '', nav_label: '' },
    }))
  }

  return (
    <div className="space-y-6">
      <div>
        <Button onClick={onBack} variant="outline">
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back
        </Button>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div>
              <CardTitle className="text-xl">{plugin.name}</CardTitle>
              <CardDescription>{plugin.description}</CardDescription>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge variant="secondary">{plugin.package_name}</Badge>
                <Badge variant="secondary">v{plugin.package_version}</Badge>
                <Badge variant="secondary">{plugin.auth_type}</Badge>
                {plugin.plugin_type && (
                  <Badge variant="secondary">{plugin.plugin_type}</Badge>
                )}
                <Badge variant={plugin.enabled ? 'default' : 'outline'}>
                  {plugin.enabled ? 'Enabled' : 'Disabled'}
                </Badge>
              </div>
            </div>
            <div className="shrink-0">
              {plugin.enabled ? (
                <Button
                  disabled={enabledMutation.isPending}
                  onClick={() => setConfirmDisableOpen(true)}
                  size="sm"
                  variant="outline"
                >
                  <PowerOff className="mr-1 h-3.5 w-3.5" />
                  Disable
                </Button>
              ) : (
                <Button
                  disabled={enabledMutation.isPending}
                  onClick={() => enabledMutation.mutate(true)}
                  size="sm"
                  variant="outline"
                >
                  <CirclePlay className="mr-1 h-3.5 w-3.5" />
                  Enable
                </Button>
              )}
            </div>
          </div>
        </CardHeader>
      </Card>

      {plugin.requires_identity && (
        <Card>
          <CardHeader>
            <CardTitle>Dashboard widget text</CardTitle>
            <CardDescription>
              Body copy shown on the dashboard's "Connect your {plugin.name}"
              widget. Leave empty to use the plugin author's default.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Textarea
              onChange={(e) => setWidgetText(e.target.value)}
              placeholder={plugin.widget_text_default ?? plugin.description}
              rows={4}
              value={widgetText}
            />
            <div className="flex items-center gap-2">
              <Button
                disabled={!widgetDirty || patchMutation.isPending}
                onClick={saveWidgetText}
                size="sm"
              >
                Save
              </Button>
              {plugin.widget_text_override !== null &&
                plugin.widget_text_override !== undefined && (
                  <Button
                    disabled={patchMutation.isPending}
                    onClick={resetWidgetText}
                    size="sm"
                    variant="ghost"
                  >
                    <RotateCcw className="mr-1 h-3.5 w-3.5" />
                    Reset to manifest default
                  </Button>
                )}
            </div>
            {plugin.widget_text_default && (
              <p className="text-xs text-tertiary">
                Default: {plugin.widget_text_default}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {(plugin.vertex_labels ?? []).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Entity labels</CardTitle>
            <CardDescription>
              Override the navigation, page, and help text shown for each entity
              type this plugin declares. Empty fields fall back to the plugin
              author's manifest values.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {(plugin.vertex_labels ?? []).map((vlabel) => {
              const draft =
                vertexForm[vlabel.name] ??
                ({
                  description: '',
                  display_name: '',
                  nav_label: '',
                } satisfies VertexFormState)
              const dirty = vertexDirty.has(vlabel.name)
              const hasOverride =
                vlabel.overrides &&
                Object.values(vlabel.overrides).some(
                  (v) => v !== null && v !== undefined && v !== '',
                )
              return (
                <div
                  className="space-y-3 border-l-2 border-tertiary pl-4"
                  key={vlabel.name}
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <code className="text-sm">{vlabel.name}</code>
                      <span className="ml-2 text-xs text-tertiary">
                        ({vlabel.model_ref})
                      </span>
                    </div>
                  </div>
                  <div className="grid gap-3 md:grid-cols-2">
                    <label className="block text-sm">
                      <span className="text-secondary">Display name</span>
                      <Input
                        onChange={(e) =>
                          setVertexForm((s) => ({
                            ...s,
                            [vlabel.name]: {
                              ...draft,
                              display_name: e.target.value,
                            },
                          }))
                        }
                        placeholder={vlabel.name}
                        value={draft.display_name}
                      />
                      <p className="mt-1 text-xs text-tertiary">
                        Page header / detail title.
                      </p>
                    </label>
                    <label className="block text-sm">
                      <span className="text-secondary">Sidebar label</span>
                      <Input
                        onChange={(e) =>
                          setVertexForm((s) => ({
                            ...s,
                            [vlabel.name]: {
                              ...draft,
                              nav_label: e.target.value,
                            },
                          }))
                        }
                        placeholder={draft.display_name || vlabel.name}
                        value={draft.nav_label}
                      />
                      <p className="mt-1 text-xs text-tertiary">
                        Defaults to display name when empty.
                      </p>
                    </label>
                  </div>
                  <label className="block text-sm">
                    <span className="text-secondary">Description</span>
                    <Textarea
                      onChange={(e) =>
                        setVertexForm((s) => ({
                          ...s,
                          [vlabel.name]: {
                            ...draft,
                            description: e.target.value,
                          },
                        }))
                      }
                      placeholder="Help text shown above the table."
                      rows={2}
                      value={draft.description}
                    />
                  </label>
                  <div className="flex items-center gap-2">
                    <Button
                      disabled={!dirty || patchMutation.isPending}
                      onClick={() => saveVertex(vlabel.name)}
                      size="sm"
                    >
                      Save
                    </Button>
                    {hasOverride && (
                      <Button
                        disabled={patchMutation.isPending}
                        onClick={() => resetVertex(vlabel.name)}
                        size="sm"
                        variant="ghost"
                      >
                        <RotateCcw className="mr-1 h-3.5 w-3.5" />
                        Reset to manifest default
                      </Button>
                    )}
                  </div>
                </div>
              )
            })}
          </CardContent>
        </Card>
      )}

      {(plugin.vertex_labels ?? []).map((vlabel) => (
        <Card key={`entities:${vlabel.name}`}>
          <CardContent className="pt-6">
            <PluginEntityManagement
              pluginName={plugin.name}
              pluginSlug={plugin.slug}
              vertexLabel={vlabel}
            />
          </CardContent>
        </Card>
      ))}

      <ConfirmDialog
        confirmLabel="Disable"
        description={`Disable ${plugin.name}? It will no longer be available for new project type or service assignments. Existing configuration is preserved and the plugin can be re-enabled at any time.`}
        onCancel={() => {
          if (!enabledMutation.isPending) setConfirmDisableOpen(false)
        }}
        onConfirm={() => enabledMutation.mutate(false)}
        open={confirmDisableOpen}
        title="Disable plugin"
      />
    </div>
  )
}
