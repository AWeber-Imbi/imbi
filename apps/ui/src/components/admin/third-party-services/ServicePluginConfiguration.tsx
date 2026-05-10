import * as React from 'react'
import { useEffect, useMemo, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import {
  getAdminPlugin,
  getServicePluginConfiguration,
  type IdentityPluginRef,
  listIdentityPlugins,
  listProjectTypes,
  listServiceApplications,
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
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

interface ApplicationCardProps {
  orgSlug: string
  plugin: PluginResponse
  queryClient: ReturnType<typeof useQueryClient>
  serviceSlug: string
}

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
  identity_plugin_id: null | string
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
          {manifest?.auth_type === 'api_token' ? (
            <CredentialsCard
              orgSlug={orgSlug}
              pluginId={plugin.id}
              queryClient={queryClient}
              serviceSlug={serviceSlug}
            />
          ) : manifest ? (
            <ApplicationCard
              orgSlug={orgSlug}
              plugin={plugin}
              queryClient={queryClient}
              serviceSlug={serviceSlug}
            />
          ) : null}
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

const APPLICATION_NONE_VALUE = '__none__'

function ApplicationCard({
  orgSlug,
  plugin,
  queryClient,
  serviceSlug,
}: ApplicationCardProps) {
  // Local draft so the operator can pick from the dropdown without
  // dispatching a save on every change. ``null`` means "no link" /
  // clear the binding on save.
  const initial = plugin.application_slug ?? null
  const [draft, setDraft] = useState<null | string>(initial)

  useEffect(() => {
    setDraft(plugin.application_slug ?? null)
  }, [plugin.id, plugin.application_slug])

  const { data: applications, isLoading } = useQuery({
    // ``usage='integration'`` is the default; the same call already
    // appears on the OAuth2 Applications tab. Filter to apps whose
    // service_slug matches this service so cross-service apps are
    // excluded — the backend enforces same-service on save anyway,
    // but pre-filtering avoids a confusing 400.
    queryFn: ({ signal }) =>
      listServiceApplications(orgSlug, serviceSlug, 'integration', signal),
    queryKey: ['service-applications', orgSlug, serviceSlug, 'integration'],
    staleTime: 30 * 1000,
  })

  // The list endpoint already restricts to apps registered to this
  // service, then folds in any global login apps as ``is_global=true``.
  // Drop the latter — they're login-providers from a different org and
  // can't legally back this Plugin's outbound credentials.
  const sameServiceApps = useMemo(
    () => (applications ?? []).filter((a) => !a.is_global),
    [applications],
  )

  const saveMutation = useMutation({
    mutationFn: () =>
      updateServicePlugin(orgSlug, serviceSlug, plugin.id, {
        label: plugin.label,
        options: plugin.options,
        // Tri-state: ``null`` clears, a string sets/replaces. Omitting
        // would leave the old link in place — never what the operator
        // who just changed the dropdown wants.
        service_application_slug: draft,
      }),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to link application')
    },
    onSuccess: () => {
      toast.success(
        draft === null ? 'Application unlinked' : 'Application linked',
      )
      void queryClient.invalidateQueries({
        queryKey: ['service-plugins', orgSlug, serviceSlug],
      })
    },
  })

  const dirty = (draft ?? null) !== (initial ?? null)

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between px-6 py-4">
        <div>
          <CardTitle>Application</CardTitle>
          <CardDescription>
            Picks the OAuth2 application this plugin uses for client_id and
            client_secret. Edit the credentials themselves on the Applications
            tab. This setting is unrelated to using the app as an Imbi login
            provider.
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
      <CardContent className="space-y-2 px-6 pb-6">
        <div className="grid grid-cols-[160px_1fr] items-center gap-3">
          <Label htmlFor="plugin-application">
            Application
            <span className="ml-1 text-destructive">*</span>
          </Label>
          {isLoading ? (
            <LoadingState label="Loading…" />
          ) : (
            <Select
              onValueChange={(v) =>
                setDraft(v === APPLICATION_NONE_VALUE ? null : v)
              }
              value={draft ?? APPLICATION_NONE_VALUE}
            >
              <SelectTrigger id="plugin-application">
                <SelectValue placeholder="Select an application…">
                  {draft
                    ? (sameServiceApps.find((a) => a.slug === draft)?.name ??
                      plugin.application_name ??
                      draft)
                    : 'None'}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={APPLICATION_NONE_VALUE}>None</SelectItem>
                {sameServiceApps.map((a) => (
                  <SelectItem key={a.slug} value={a.slug}>
                    {a.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>
        {!isLoading && sameServiceApps.length === 0 && (
          <p className="text-xs text-secondary">
            No OAuth2 applications are registered to this service yet. Add one
            on the Applications tab before linking it here.
          </p>
        )}
        {draft === null && initial !== null && (
          <p className="text-xs text-destructive">
            Saving will clear the link. The plugin will fail with
            "PluginCredentialsMissing" until another application is linked.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

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
  const [identityDraft, setIdentityDraft] = useState<null | string>(
    plugin.identity_plugin_id ?? null,
  )

  useEffect(() => {
    setDraft(plugin.options)
    setIdentityDraft(plugin.identity_plugin_id ?? null)
  }, [plugin.id, plugin.options, plugin.identity_plugin_id])

  const { data: identityPlugins } = useQuery({
    queryFn: ({ signal }) => listIdentityPlugins(orgSlug, signal),
    queryKey: queryKeys.identityPlugins(orgSlug),
    staleTime: 60 * 1000,
  })

  const dirty = useMemo(
    () =>
      JSON.stringify(draft) !== JSON.stringify(plugin.options) ||
      (identityDraft ?? null) !== (plugin.identity_plugin_id ?? null),
    [draft, identityDraft, plugin.options, plugin.identity_plugin_id],
  )

  const saveMutation = useMutation({
    mutationFn: () =>
      updateServicePlugin(orgSlug, serviceSlug, plugin.id, {
        // Empty string explicitly clears the binding on the backend;
        // omitting it would leave the previous value in place.
        identity_plugin_id: identityDraft ?? '',
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
  // Even when the manifest has no plugin options, we still render the card
  // when a default identity plugin can be configured.
  const hasOptions = manifest.options.length > 0
  if (!hasOptions && manifest.plugin_type === 'identity') return null

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
        {manifest.plugin_type !== 'identity' && (
          <div className="grid grid-cols-[160px_1fr] items-center gap-3">
            <Label className="truncate text-xs" title="Identity Plugin">
              Identity Plugin
            </Label>
            <div className="space-y-1">
              <IdentityPluginSelect
                identityPlugins={identityPlugins ?? []}
                onChange={setIdentityDraft}
                value={identityDraft}
              />
              <p className="text-xs text-secondary">
                Default identity used for plugin calls when no project-type
                assignment names one. Per-type bindings still take precedence.
              </p>
            </div>
          </div>
        )}
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
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const toggleExpanded = (idx: number) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })

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

  const { data: identityPlugins } = useQuery({
    queryFn: ({ signal }) => listIdentityPlugins(orgSlug, signal),
    queryKey: queryKeys.identityPlugins(orgSlug),
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
        identity_plugin_id: a.identity_plugin_id ?? null,
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
      identity_plugin_id: a.identity_plugin_id ?? null,
      options: a.options,
      project_type_slug: a.project_type_slug,
      tab: a.tab,
    }))
    return JSON.stringify(drafts) !== JSON.stringify(baseline)
  }, [drafts, existing])

  const supportedTab = (manifest?.supported_tabs[0] ??
    'configuration') as PluginTab

  const handleAdd = (slug: string) => {
    setDrafts((prev) => {
      if (prev.some((d) => d.project_type_slug === slug)) return prev
      return [
        ...prev,
        {
          default: true,
          identity_plugin_id: null,
          options: {},
          project_type_slug: slug,
          tab: supportedTab,
        },
      ]
    })
  }

  const handleRemove = (idx: number) => {
    setDrafts((prev) => prev.filter((_, i) => i !== idx))
    setExpanded((prev) => {
      const next = new Set<number>()
      // Indices shift left by 1 once we drop ``idx``; rebuild the set
      // accordingly so a different row doesn't suddenly appear expanded.
      for (const i of prev) {
        if (i === idx) continue
        next.add(i > idx ? i - 1 : i)
      }
      return next
    })
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
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                disabled={remainingPts.length === 0}
                size="sm"
                variant="outline"
              >
                <Plus className="mr-1 h-3 w-3" />
                Add
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="max-h-72 overflow-auto">
              {remainingPts.map((pt) => (
                <DropdownMenuItem
                  key={pt.slug}
                  onSelect={() => handleAdd(pt.slug)}
                >
                  {pt.name}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
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
                <TableHead className="w-24">Default</TableHead>
                <TableHead className="w-12" />
                <TableHead className="w-12" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {drafts.map((draft, idx) => {
                const isExpanded = expanded.has(idx)
                // Override count = identity-plugin override (if set) + each
                // explicitly overridden option field. The identity selector
                // lives inside the accordion now, so the row is always
                // expandable even when the manifest has no option fields.
                const overrideCount =
                  Object.keys(draft.options).length +
                  (draft.identity_plugin_id ? 1 : 0)
                return (
                  <React.Fragment key={`${draft.project_type_slug}-${idx}`}>
                    <TableRow
                      aria-expanded={isExpanded}
                      className="hover:bg-secondary/40 cursor-pointer"
                      onClick={() => toggleExpanded(idx)}
                    >
                      <TableCell className="align-middle">
                        <span className="text-sm">
                          {ptByName.get(draft.project_type_slug) ??
                            draft.project_type_slug}
                        </span>
                      </TableCell>
                      <TableCell className="align-middle">
                        <input
                          checked={draft.default}
                          onChange={(e) =>
                            updateDraft(idx, { default: e.target.checked })
                          }
                          onClick={(e) => e.stopPropagation()}
                          type="checkbox"
                        />
                      </TableCell>
                      <TableCell className="align-middle">
                        <span className="relative inline-flex items-center">
                          <ChevronDown
                            className={`h-3.5 w-3.5 text-tertiary transition-transform ${
                              isExpanded ? 'rotate-180' : ''
                            }`}
                          />
                          {overrideCount > 0 && (
                            <Badge
                              className="ml-1 h-4 px-1 text-[10px]"
                              variant="secondary"
                            >
                              {overrideCount}
                            </Badge>
                          )}
                        </span>
                      </TableCell>
                      <TableCell className="align-middle">
                        <Button
                          aria-label="Remove assignment"
                          onClick={(e) => {
                            e.stopPropagation()
                            handleRemove(idx)
                          }}
                          size="icon"
                          variant="ghost"
                        >
                          <Trash2 className="h-3 w-3 text-destructive" />
                        </Button>
                      </TableCell>
                    </TableRow>
                    {isExpanded && (
                      <TableRow className="bg-secondary/30 hover:bg-secondary/30">
                        <TableCell className="p-0" colSpan={4}>
                          <div className="space-y-3 px-6 py-4">
                            <div className="grid grid-cols-[160px_1fr] items-center gap-3">
                              <Label className="text-sm">Identity Plugin</Label>
                              <IdentityPluginSelect
                                identityPlugins={identityPlugins ?? []}
                                onChange={(next) =>
                                  updateDraft(idx, {
                                    identity_plugin_id: next,
                                  })
                                }
                                value={draft.identity_plugin_id ?? null}
                              />
                            </div>
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
                        </TableCell>
                      </TableRow>
                    )}
                  </React.Fragment>
                )
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

const IDENTITY_NONE_VALUE = '__none__'

function IdentityPluginSelect({
  identityPlugins,
  onChange,
  value,
}: {
  identityPlugins: IdentityPluginRef[]
  onChange: (next: null | string) => void
  value: null | string
}) {
  const selectedLabel =
    value && identityPlugins.find((ip) => ip.plugin_id === value)?.label
  return (
    <Select
      onValueChange={(v) => onChange(v === IDENTITY_NONE_VALUE ? null : v)}
      value={value ?? IDENTITY_NONE_VALUE}
    >
      <SelectTrigger>
        <SelectValue placeholder="None">
          {value ? (selectedLabel ?? value) : 'None'}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={IDENTITY_NONE_VALUE}>None</SelectItem>
        {identityPlugins.map((ip) => (
          <SelectItem key={ip.plugin_id} value={ip.plugin_id}>
            {ip.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
