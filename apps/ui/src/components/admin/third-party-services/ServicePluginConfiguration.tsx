import { useEffect, useMemo, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import {
  getAdminPlugin,
  getServicePluginConfiguration,
  listProjectTypes,
  listServicePluginAssignments,
  patchServicePluginConfiguration,
  replaceServicePluginAssignments,
  updateServicePlugin,
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
import type {
  InstalledPlugin,
  PluginAssignmentInput,
  PluginAssignmentRow,
  PluginOptionDef,
  PluginResponse,
  PluginTab,
} from '@/types'

import { ServicePluginEdgesCard } from './ServicePluginEdgesCard'

interface CredentialsCardProps {
  orgSlug: string
  pluginId: string
  queryClient: ReturnType<typeof useQueryClient>
  serviceSlug: string
}

interface DefaultOptionsCardProps {
  manifest: InstalledPlugin | null
  orgSlug: string
  plugin: PluginResponse
  queryClient: ReturnType<typeof useQueryClient>
  serviceSlug: string
}

// --------------------------- Identity ----------------------------------

interface DraftAssignment {
  default: boolean
  options: Record<string, unknown>
  project_type_slug: string
  tab: PluginTab
}

interface IdentityCardProps {
  orgSlug: string
  plugin: PluginResponse
  queryClient: ReturnType<typeof useQueryClient>
  serviceSlug: string
}

// --------------------------- Credentials -------------------------------

interface OptionRowProps {
  description: null | string
  label: string
  name: string
  onChange: (next: unknown) => void
  opt: PluginOptionDef
  placeholder?: string
  value: unknown
}

interface ProjectTypesCardProps {
  manifest: InstalledPlugin | null
  orgSlug: string
  plugin: PluginResponse
  queryClient: ReturnType<typeof useQueryClient>
  serviceSlug: string
}

// --------------------------- Default Options ---------------------------

interface ServicePluginConfigurationProps {
  onBack: () => void
  orgSlug: string
  plugin: PluginResponse
  serviceSlug: string
}

export function ServicePluginConfiguration({
  onBack: _onBack,
  orgSlug,
  plugin,
  serviceSlug,
}: ServicePluginConfigurationProps) {
  const queryClient = useQueryClient()

  const { data: manifest, isLoading: manifestLoading } = useQuery({
    queryFn: ({ signal }) => getAdminPlugin(plugin.plugin_slug, signal),
    queryKey: queryKeys.adminPlugin(plugin.plugin_slug),
    staleTime: 5 * 60 * 1000,
  })

  return (
    <div className="space-y-4">
      {manifestLoading ? (
        <LoadingState label="Loading…" />
      ) : (
        <>
          <IdentityCard
            orgSlug={orgSlug}
            plugin={plugin}
            queryClient={queryClient}
            serviceSlug={serviceSlug}
          />
          {manifest?.auth_type === 'api_token' && (
            <CredentialsCard
              orgSlug={orgSlug}
              pluginId={plugin.id}
              queryClient={queryClient}
              serviceSlug={serviceSlug}
            />
          )}
          <DefaultOptionsCard
            manifest={manifest ?? null}
            orgSlug={orgSlug}
            plugin={plugin}
            queryClient={queryClient}
            serviceSlug={serviceSlug}
          />
          <ProjectTypesCard
            manifest={manifest ?? null}
            orgSlug={orgSlug}
            plugin={plugin}
            queryClient={queryClient}
            serviceSlug={serviceSlug}
          />
          {manifest && (
            <ServicePluginEdgesCard manifest={manifest} orgSlug={orgSlug} />
          )}
        </>
      )}
    </div>
  )
}

// --------------------------- Project Types -----------------------------

function CredentialsCard({
  orgSlug,
  pluginId,
  queryClient,
  serviceSlug,
}: CredentialsCardProps) {
  const [values, setValues] = useState<Record<string, string>>({})

  const {
    data: config,
    error,
    isError,
    isLoading,
  } = useQuery({
    queryFn: ({ signal }) =>
      getServicePluginConfiguration(orgSlug, serviceSlug, pluginId, signal),
    queryKey: ['service-plugin-configuration', orgSlug, serviceSlug, pluginId],
    staleTime: 0,
  })

  useEffect(() => {
    setValues({})
  }, [pluginId])

  const populated = new Set(config?.populated ?? [])

  const saveMutation = useMutation({
    mutationFn: (payload: Record<string, null | string>) =>
      patchServicePluginConfiguration(orgSlug, serviceSlug, pluginId, payload),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to update credentials')
    },
    onSuccess: () => {
      toast.success('Credentials saved')
      setValues({})
      void queryClient.invalidateQueries({
        queryKey: [
          'service-plugin-configuration',
          orgSlug,
          serviceSlug,
          pluginId,
        ],
      })
    },
  })

  const dirty = Object.values(values).some((v) => v !== '')

  const handleSaveAll = () => {
    const payload: Record<string, null | string> = {}
    for (const [key, value] of Object.entries(values)) {
      if (value === '') continue
      payload[key] = value
    }
    if (Object.keys(payload).length === 0) return
    saveMutation.mutate(payload)
  }

  const handleClear = (name: string) => {
    saveMutation.mutate({ [name]: null })
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between px-6 py-4">
        <div>
          <CardTitle>Credentials</CardTitle>
          <CardDescription>
            Encrypted secrets used by this plugin instance.
          </CardDescription>
        </div>
        {dirty && (
          <Button
            disabled={saveMutation.isPending}
            onClick={handleSaveAll}
            size="sm"
          >
            {saveMutation.isPending ? 'Saving…' : 'Save'}
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-4 px-6 pb-6">
        {isLoading ? (
          <LoadingState label="Loading…" />
        ) : isError ? (
          <div className="text-sm text-destructive">
            {extractApiErrorDetail(error) ?? 'Failed to load credentials'}
          </div>
        ) : config && config.fields.length === 0 ? (
          <div className="text-sm text-secondary">
            This plugin defines no credential fields.
          </div>
        ) : (
          (config?.fields ?? []).map((field) => {
            const isSet = populated.has(field.name)
            return (
              <div className="space-y-1" key={field.name}>
                <Label htmlFor={`field-${field.name}`}>
                  {field.label}
                  {field.required && (
                    <span className="ml-1 text-destructive">*</span>
                  )}
                </Label>
                <div className="flex gap-2">
                  <Input
                    autoComplete="off"
                    id={`field-${field.name}`}
                    onChange={(e) =>
                      setValues((v) => ({
                        ...v,
                        [field.name]: e.target.value,
                      }))
                    }
                    placeholder={
                      isSet
                        ? '•••••••• (set — enter a value to replace)'
                        : 'Enter value'
                    }
                    type="password"
                    value={values[field.name] ?? ''}
                  />
                  {isSet && (
                    <Button
                      disabled={saveMutation.isPending}
                      onClick={() => handleClear(field.name)}
                      size="sm"
                      type="button"
                      variant="ghost"
                    >
                      Clear
                    </Button>
                  )}
                </div>
                {field.description && (
                  <p className="text-xs text-secondary">{field.description}</p>
                )}
              </div>
            )
          })
        )}
      </CardContent>
    </Card>
  )
}

function DefaultOptionsCard({
  manifest,
  orgSlug,
  plugin,
  queryClient,
  serviceSlug,
}: DefaultOptionsCardProps) {
  const [draft, setDraft] = useState<Record<string, unknown>>(plugin.options)

  useEffect(() => {
    setDraft(plugin.options)
  }, [plugin.id, plugin.options])

  const dirty = useMemo(
    () => JSON.stringify(draft) !== JSON.stringify(plugin.options),
    [draft, plugin.options],
  )

  const saveMutation = useMutation({
    mutationFn: () =>
      updateServicePlugin(orgSlug, serviceSlug, plugin.id, {
        label: plugin.label,
        options: draft,
      }),
    onError: (err) => {
      toast.error(
        extractApiErrorDetail(err) ?? 'Failed to save default options',
      )
    },
    onSuccess: () => {
      toast.success('Default options saved')
      void queryClient.invalidateQueries({
        queryKey: ['service-plugins', orgSlug, serviceSlug],
      })
    },
  })

  if (!manifest) return null
  if (manifest.options.length === 0) return null

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between px-6 py-4">
        <div>
          <CardTitle>Default Options</CardTitle>
          <CardDescription>
            Applied to every project type that uses this plugin instance.
            Per-project-type overrides shadow these defaults.
          </CardDescription>
        </div>
        {dirty && (
          <Button
            disabled={saveMutation.isPending}
            onClick={() => saveMutation.mutate()}
            size="sm"
          >
            {saveMutation.isPending ? 'Saving…' : 'Save'}
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-3 px-6 pb-6">
        {manifest.options.map((opt) => (
          <OptionRow
            description={opt.description ?? null}
            key={opt.name}
            label={opt.label}
            name={opt.name}
            onChange={(next) => setDraft((d) => ({ ...d, [opt.name]: next }))}
            opt={opt}
            placeholder={
              opt.default !== undefined && opt.default !== null
                ? `Manifest default: ${String(opt.default)}`
                : undefined
            }
            value={draft[opt.name]}
          />
        ))}
      </CardContent>
    </Card>
  )
}

function IdentityCard({
  orgSlug,
  plugin,
  queryClient,
  serviceSlug,
}: IdentityCardProps) {
  const [label, setLabel] = useState(plugin.label)

  useEffect(() => {
    setLabel(plugin.label)
  }, [plugin.id, plugin.label])

  const saveMutation = useMutation({
    mutationFn: () =>
      updateServicePlugin(orgSlug, serviceSlug, plugin.id, {
        label,
        options: plugin.options,
      }),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to save label')
    },
    onSuccess: () => {
      toast.success('Label saved')
      void queryClient.invalidateQueries({
        queryKey: ['service-plugins', orgSlug, serviceSlug],
      })
    },
  })

  const dirty = label !== plugin.label

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between px-6 py-4">
        <div>
          <CardTitle>Identity</CardTitle>
          <CardDescription>
            Label shown wherever this plugin instance is referenced.
          </CardDescription>
        </div>
        {dirty && (
          <Button
            disabled={saveMutation.isPending || label.trim() === ''}
            onClick={() => saveMutation.mutate()}
            size="sm"
          >
            {saveMutation.isPending ? 'Saving…' : 'Save'}
          </Button>
        )}
      </CardHeader>
      <CardContent className="px-6 pb-6">
        <div className="grid grid-cols-[160px_1fr] items-center gap-3">
          <Label htmlFor="plugin-label">Label</Label>
          <Input
            id="plugin-label"
            onChange={(e) => setLabel(e.target.value)}
            value={label}
          />
        </div>
      </CardContent>
    </Card>
  )
}

// --------------------------- OptionRow ---------------------------------

function OptionRow({
  description,
  label,
  name,
  onChange,
  opt,
  placeholder,
  value,
}: OptionRowProps) {
  const id = `option-${name}`
  let control: React.ReactNode

  if (opt.choices && opt.choices.length > 0) {
    control = (
      <Select
        onValueChange={(v) => onChange(v)}
        value={typeof value === 'string' ? value : ''}
      >
        <SelectTrigger id={id}>
          <SelectValue placeholder={placeholder ?? 'Select…'} />
        </SelectTrigger>
        <SelectContent>
          {opt.choices.map((c) => (
            <SelectItem key={c} value={c}>
              {c}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    )
  } else if (opt.type === 'boolean') {
    control = (
      <input
        checked={Boolean(value)}
        id={id}
        onChange={(e) => onChange(e.target.checked)}
        type="checkbox"
      />
    )
  } else if (opt.type === 'integer') {
    control = (
      <Input
        id={id}
        onChange={(e) => {
          const raw = e.target.value
          if (raw === '') {
            onChange(null)
            return
          }
          const n = Number.parseInt(raw, 10)
          if (!Number.isNaN(n)) onChange(n)
        }}
        placeholder={placeholder}
        type="number"
        value={
          typeof value === 'number' ? String(value) : (value as string) || ''
        }
      />
    )
  } else {
    control = (
      <Input
        id={id}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        type={opt.type === 'secret' ? 'password' : 'text'}
        value={(value as string) ?? ''}
      />
    )
  }

  return (
    <div className="grid grid-cols-[160px_1fr] items-center gap-3">
      <Label className="truncate text-xs" htmlFor={id} title={label}>
        {label}
        {opt.required && <span className="ml-1 text-destructive">*</span>}
      </Label>
      <div className="space-y-1">
        {control}
        {description && <p className="text-xs text-secondary">{description}</p>}
      </div>
    </div>
  )
}

function ProjectTypesCard({
  manifest,
  orgSlug,
  plugin,
  queryClient,
  serviceSlug,
}: ProjectTypesCardProps) {
  const [drafts, setDrafts] = useState<DraftAssignment[]>([])
  const [seedHash, setSeedHash] = useState<null | string>(null)

  const { data: existing } = useQuery({
    queryFn: ({ signal }) =>
      listServicePluginAssignments(orgSlug, serviceSlug, plugin.id, signal),
    queryKey: ['service-plugin-assignments', orgSlug, serviceSlug, plugin.id],
    staleTime: 0,
  })

  const { data: projectTypes } = useQuery({
    queryFn: ({ signal }) => listProjectTypes(orgSlug, signal),
    queryKey: ['project-types', orgSlug],
    staleTime: 60 * 1000,
  })

  // Re-seed drafts whenever the server-returned list actually changes.
  // Tracking by hash avoids stomping a user's in-progress edits on a
  // stale refetch and avoids the seeded/refetch race after save.
  useEffect(() => {
    if (!existing) return
    const hash = JSON.stringify(existing)
    if (hash === seedHash) return
    setDrafts(
      existing.map((a: PluginAssignmentRow) => ({
        default: a.default,
        options: a.options,
        project_type_slug: a.project_type_slug,
        tab: a.tab,
      })),
    )
    setSeedHash(hash)
  }, [existing, seedHash])

  const saveMutation = useMutation({
    mutationFn: (body: PluginAssignmentInput[]) =>
      replaceServicePluginAssignments(orgSlug, serviceSlug, plugin.id, body),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to save assignments')
    },
    onSuccess: () => {
      toast.success('Project type assignments saved')
      void queryClient.invalidateQueries({
        queryKey: [
          'service-plugin-assignments',
          orgSlug,
          serviceSlug,
          plugin.id,
        ],
      })
    },
  })

  const ptByName = useMemo(
    () =>
      new Map((projectTypes ?? []).map((pt) => [pt.slug, pt.name] as const)),
    [projectTypes],
  )

  const remainingPts = useMemo(() => {
    const used = new Set(drafts.map((d) => d.project_type_slug))
    return (projectTypes ?? []).filter((pt) => !used.has(pt.slug))
  }, [drafts, projectTypes])

  const isDirty = useMemo(() => {
    const baseline = (existing ?? []).map((a: PluginAssignmentRow) => ({
      default: a.default,
      options: a.options,
      project_type_slug: a.project_type_slug,
      tab: a.tab,
    }))
    return JSON.stringify(drafts) !== JSON.stringify(baseline)
  }, [drafts, existing])

  const supportedTab = (manifest?.supported_tabs[0] ??
    'configuration') as PluginTab

  const handleAdd = () => {
    if (!remainingPts.length) return
    setDrafts((prev) => [
      ...prev,
      {
        default: false,
        options: {},
        project_type_slug: remainingPts[0].slug,
        tab: supportedTab,
      },
    ])
  }

  const handleRemove = (idx: number) => {
    setDrafts((prev) => prev.filter((_, i) => i !== idx))
  }

  const updateDraft = (idx: number, patch: Partial<DraftAssignment>) => {
    setDrafts((prev) =>
      prev.map((d, i) => (i === idx ? { ...d, ...patch } : d)),
    )
  }

  const updateOverride = (idx: number, optName: string, value: unknown) => {
    setDrafts((prev) =>
      prev.map((d, i) =>
        i === idx
          ? {
              ...d,
              options:
                value === null || value === ''
                  ? Object.fromEntries(
                      Object.entries(d.options).filter(([k]) => k !== optName),
                    )
                  : { ...d.options, [optName]: value },
            }
          : d,
      ),
    )
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between px-6 py-4">
        <div>
          <CardTitle>Project Types</CardTitle>
          <CardDescription>
            Bind this plugin to project types. Leave option fields empty to
            inherit the default; fill them in to override per type.
          </CardDescription>
        </div>
        <div className="flex gap-2">
          {isDirty && (
            <Button
              disabled={saveMutation.isPending}
              onClick={() => saveMutation.mutate(drafts)}
              size="sm"
            >
              {saveMutation.isPending ? 'Saving…' : 'Save'}
            </Button>
          )}
          <Button
            disabled={remainingPts.length === 0}
            onClick={handleAdd}
            size="sm"
            variant="outline"
          >
            <Plus className="mr-1 h-3 w-3" />
            Add
          </Button>
        </div>
      </CardHeader>
      <CardContent className="px-6 pb-6">
        {drafts.length === 0 ? (
          <div className="rounded border border-dashed border-tertiary py-8 text-center text-sm text-secondary">
            No project type assignments. Add one to surface this plugin under a
            project type&apos;s {supportedTab} tab.
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Project Type</TableHead>
                <TableHead>Tab</TableHead>
                <TableHead>Default</TableHead>
                <TableHead>Option Overrides</TableHead>
                <TableHead className="w-12" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {drafts.map((draft, idx) => {
                const usedSlugs = new Set(
                  drafts
                    .filter((_, i) => i !== idx)
                    .map((d) => d.project_type_slug),
                )
                const ptOptions = (projectTypes ?? []).filter(
                  (pt) =>
                    pt.slug === draft.project_type_slug ||
                    !usedSlugs.has(pt.slug),
                )
                return (
                  <TableRow key={`${draft.project_type_slug}-${idx}`}>
                    <TableCell className="align-top">
                      <Select
                        onValueChange={(v) =>
                          updateDraft(idx, { project_type_slug: v })
                        }
                        value={draft.project_type_slug}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Select…">
                            {ptByName.get(draft.project_type_slug) ??
                              draft.project_type_slug}
                          </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                          {ptOptions.map((pt) => (
                            <SelectItem key={pt.slug} value={pt.slug}>
                              {pt.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </TableCell>
                    <TableCell className="align-top">
                      <Badge variant="secondary">{draft.tab}</Badge>
                    </TableCell>
                    <TableCell className="align-top">
                      <input
                        checked={draft.default}
                        onChange={(e) =>
                          updateDraft(idx, { default: e.target.checked })
                        }
                        type="checkbox"
                      />
                    </TableCell>
                    <TableCell className="align-top">
                      {(manifest?.options ?? []).length === 0 ? (
                        <span className="text-xs text-secondary">—</span>
                      ) : (
                        <div className="space-y-2">
                          {(manifest?.options ?? []).map((opt) => {
                            const defaultVal =
                              plugin.options[opt.name] ?? opt.default ?? null
                            const overridden = opt.name in draft.options
                            return (
                              <OptionRow
                                description={null}
                                key={opt.name}
                                label={opt.label}
                                name={`${opt.name}-${idx}`}
                                onChange={(next) =>
                                  updateOverride(idx, opt.name, next)
                                }
                                opt={opt}
                                placeholder={
                                  overridden
                                    ? undefined
                                    : defaultVal !== null
                                      ? `Inherits: ${String(defaultVal)}`
                                      : 'Inherits default'
                                }
                                value={
                                  overridden ? draft.options[opt.name] : ''
                                }
                              />
                            )
                          })}
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="align-top">
                      <Button
                        aria-label="Remove assignment"
                        onClick={() => handleRemove(idx)}
                        size="icon"
                        variant="ghost"
                      >
                        <Trash2 className="h-3 w-3 text-destructive" />
                      </Button>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
