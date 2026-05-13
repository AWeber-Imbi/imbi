import { useEffect, useMemo, useRef, useState } from 'react'

import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import {
  Check,
  Eye,
  EyeOff,
  Lock,
  Plus,
  Search,
  Settings2,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import {
  deleteConfigurationKey,
  fetchConfigurationValues,
  listConfigurationKeys,
  listProjectPlugins,
  setConfigurationValue,
} from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardTitle } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import { LoadingState } from '@/components/ui/loading-state'
import { useTheme } from '@/contexts/ThemeContext'
import { extractApiErrorDetail } from '@/lib/apiError'
import { deriveChipColors } from '@/lib/chip-colors'
import { cn, sortEnvironments } from '@/lib/utils'
import type { ConfigKeyResponse, Environment } from '@/types'

const DATA_TYPES = ['string', 'string_list', 'secret'] as const
type DataType = (typeof DATA_TYPES)[number]
const DATA_TYPE_LABELS: Record<DataType, string> = {
  secret: 'Secret',
  string: 'String',
  string_list: 'String List',
}

const COMMON_PREFIX_MIN_DEPTH = 3

interface AggregatedKey {
  data_type: DataType
  envs: Record<string, PerEnvKey | undefined>
  key: string
  last_modified: null | string
  secret: boolean
}

interface ConfigurationTabProps {
  environments: Environment[]
  orgSlug: string
  projectId: string
  projectSlug: string
  teamSlug: string
}

interface CreateDraft {
  data_type: DataType
  key: string
  values: Record<string, string>
}

interface DetailPaneProps {
  draft?: CreateDraft
  environments: Environment[]
  isCreate?: boolean
  onAdd?: () => void
  onCancel?: () => void
  onCommitType?: (type: DataType) => void
  onCommitValue?: (envSlug: string, value: string) => void
  onCreate?: () => void
  onDelete?: () => void
  onDraftChange?: (next: CreateDraft) => void
  onToggleReveal?: (envSlug: string, key: string) => void
  prefix: string
  revealed?: Record<string, boolean>
  savedFlash: boolean
  selected?: AggregatedKey
  typeOverride?: DataType | null
  valueLoadingByEnv?: Record<string, boolean>
  valuesByEnv?: Record<string, Record<string, unknown>>
}

interface EnvRowProps {
  dataType: DataType
  env: Environment
  isCreate: boolean
  isLoadingValue?: boolean
  isSecret: boolean
  isSet: boolean
  onCommit: (value: string) => void
  onToggleReveal: () => void
  revealed: boolean
  value: string | undefined
}

interface ParamListProps {
  filter: string
  items: AggregatedKey[]
  onSelect: (key: string) => void
  prefix: string
  selectedKey: null | string
}

interface PerEnvKey {
  data_type: DataType
  last_modified: null | string
  secret: boolean
}

export function ConfigurationTab({
  environments,
  orgSlug,
  projectId,
  projectSlug,
  teamSlug,
}: ConfigurationTabProps) {
  const queryClient = useQueryClient()
  const sortedEnvironments = useMemo(
    () => sortEnvironments(environments ?? []),
    [environments],
  )
  const envSlugs = useMemo(
    () => sortedEnvironments.map((e) => e.slug),
    [sortedEnvironments],
  )

  const [source, setSource] = useState<string | undefined>()
  const [filter, setFilter] = useState('')
  const [selectedKey, setSelectedKey] = useState<null | string>(null)
  const [mode, setMode] = useState<'create' | 'view'>('view')
  const [revealed, setRevealed] = useState<Record<string, boolean>>({})
  const [confirmDelete, setConfirmDelete] = useState<null | string>(null)
  const [savedFlash, setSavedFlash] = useState(false)
  const [typeOverride, setTypeOverride] = useState<null | {
    key: string
    type: DataType
  }>(null)
  const [draft, setDraft] = useState<CreateDraft>({
    data_type: 'string',
    key: '',
    values: {},
  })

  const flashTimer = useRef<null | ReturnType<typeof setTimeout>>(null)
  const flashSaved = () => {
    setSavedFlash(true)
    if (flashTimer.current) clearTimeout(flashTimer.current)
    flashTimer.current = setTimeout(() => setSavedFlash(false), 1400)
  }
  useEffect(() => {
    return () => {
      if (flashTimer.current) clearTimeout(flashTimer.current)
    }
  }, [])

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
  const activeAssignment = configAssignments.find(
    (a) => a.plugin_id === activeSource,
  )
  const configuredPrefix = (() => {
    const raw = activeAssignment?.options?.path_prefix
    if (typeof raw !== 'string' || !raw) return ''
    // Expand the same variables the backend's plugin template expander
    // supports, so users see a concrete prefix instead of `${...}`.
    // ${environment} stays unexpanded — it varies per row, and rendering
    // any single env's value would be misleading at the panel level.
    const vars: Record<string, string> = {
      org_slug: orgSlug,
      project_id: projectId,
      project_slug: projectSlug,
      team_slug: teamSlug,
    }
    return raw.replace(/\$\{([^}]+)\}/g, (match, name: string) =>
      name in vars ? vars[name] : match,
    )
  })()

  // Reset reveals whenever the data scope changes.
  useEffect(() => {
    setRevealed({})
  }, [activeSource])

  // List keys for each environment in parallel; aggregate into a single list.
  const listQueries = useQueries({
    queries: sortedEnvironments.map((env) => ({
      enabled: sources.length > 0,
      queryFn: ({ signal }: { signal?: AbortSignal }) =>
        listConfigurationKeys(
          orgSlug,
          projectId,
          { environment: env.slug, source: activeSource },
          signal,
        ),
      queryKey: [
        'config-keys',
        orgSlug,
        projectId,
        activeSource,
        env.slug,
      ] as const,
      staleTime: 60 * 1000,
    })),
  })

  const isLoading = listQueries.some((q) => q.isLoading)
  const loadError = listQueries.find((q) => q.error)?.error

  const aggregated = useMemo(
    () =>
      aggregate(
        sortedEnvironments.map((env, idx) => ({
          envSlug: env.slug,
          keys: listQueries[idx]?.data ?? [],
        })),
      ),
    // listQueries is recreated each render; depend on each query's data.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sortedEnvironments, ...listQueries.map((q) => q.data)],
  )

  // Fetch values for every key in each environment so the right pane can
  // render them inline. Secrets are returned in plaintext when the caller
  // has the `read_secrets` permission and are masked client-side.
  const valueQueries = useQueries({
    queries: sortedEnvironments.map((env, idx) => {
      const keys = listQueries[idx]?.data ?? []
      const keyNames = keys.map((k) => k.key)
      return {
        enabled: keyNames.length > 0,
        queryFn: () =>
          fetchConfigurationValues(orgSlug, projectId, keyNames, {
            environment: env.slug,
            source: activeSource,
          }),
        queryKey: [
          'config-values',
          orgSlug,
          projectId,
          activeSource,
          env.slug,
          keyNames,
        ] as const,
        staleTime: 60 * 1000,
      }
    }),
  })

  const valuesByEnv = useMemo(() => {
    const out: Record<string, Record<string, unknown>> = {}
    sortedEnvironments.forEach((env, idx) => {
      const data = valueQueries[idx]?.data
      if (!data) return
      const map: Record<string, unknown> = {}
      for (const v of data) map[v.key] = v.value
      out[env.slug] = map
    })
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sortedEnvironments, ...valueQueries.map((q) => q.data)])

  // Per-env load state for the values query. The keys list can resolve
  // before its matching value fetch, so we surface this to EnvRow to
  // gate edit/reveal until each env's values are actually present —
  // otherwise an existing key briefly looks empty and a stray keystroke
  // could overwrite a value the user never saw.
  // ``q.fetchStatus === 'idle'`` is the disabled-query state (no keys
  // for this env yet) — treat that as "not loading" so empty envs
  // don't render a permanent skeleton.
  const valueLoadingFlags = valueQueries.map(
    (q) => q.fetchStatus !== 'idle' && (q.isLoading || q.data === undefined),
  )
  const valueLoadingByEnv = useMemo(() => {
    const out: Record<string, boolean> = {}
    sortedEnvironments.forEach((env, idx) => {
      out[env.slug] = Boolean(valueLoadingFlags[idx])
    })
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sortedEnvironments, ...valueLoadingFlags])

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return aggregated
    return aggregated.filter((p) => p.key.toLowerCase().includes(q))
  }, [aggregated, filter])

  // The configured `path_prefix` (with ${...} variables) is the canonical
  // prefix declared on the assignment. The keys returned by the plugin have
  // those variables already expanded — and they expand differently per
  // environment (e.g. ${environment} → testing/staging/production), so the
  // longest common prefix across the aggregated key set is shorter than the
  // configured one. We display the configured value when present and only
  // fall back to a derived prefix when the assignment doesn't declare one.
  const derivedPrefix = useMemo(
    () => commonPrefix(aggregated.map((a) => a.key)),
    [aggregated],
  )
  // For list-row truncation we still need a prefix that actually matches the
  // keys, so use the derived value there.
  const prefix = derivedPrefix
  const displayPrefix = configuredPrefix || derivedPrefix

  const selected = useMemo(
    () => aggregated.find((a) => a.key === selectedKey) ?? null,
    [aggregated, selectedKey],
  )

  // When data first arrives, auto-select the first key.
  useEffect(() => {
    if (mode === 'view' && !selected && aggregated.length > 0) {
      setSelectedKey(aggregated[0].key)
    }
  }, [aggregated, mode, selected])

  // Reset draft entering create mode.
  useEffect(() => {
    if (mode === 'create') {
      setDraft({
        data_type: 'string',
        key: prefix,
        values: Object.fromEntries(envSlugs.map((s) => [s, ''])),
      })
    }
  }, [mode, prefix, envSlugs])

  const setMutation = useMutation({
    mutationFn: ({
      data_type,
      environment,
      key,
      secret,
      value,
    }: {
      data_type: DataType
      environment: string
      key: string
      secret: boolean
      value: string
    }) =>
      setConfigurationValue(
        orgSlug,
        projectId,
        key,
        { data_type, secret, value },
        { environment, source: activeSource },
      ),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to save value')
    },
    onSuccess: (_, vars) => {
      flashSaved()
      // Invalidate both the keys list (in case data_type/secret flipped)
      // *and* the per-env values so EnvRow rehydrates from fresh data on
      // blur instead of snapping back to a stale cached value.
      void Promise.all([
        queryClient.invalidateQueries({
          queryKey: [
            'config-keys',
            orgSlug,
            projectId,
            activeSource,
            vars.environment,
          ],
        }),
        queryClient.invalidateQueries({
          queryKey: [
            'config-values',
            orgSlug,
            projectId,
            activeSource,
            vars.environment,
          ],
        }),
      ])
    },
  })

  const deleteMutation = useMutation({
    mutationFn: async (key: string) => {
      // Delete from every environment where the key is set.
      const targets = envSlugs.filter(
        (slug) => aggregated.find((a) => a.key === key)?.envs[slug],
      )
      await Promise.all(
        targets.map((env) =>
          deleteConfigurationKey(orgSlug, projectId, key, {
            environment: env,
            source: activeSource,
          }),
        ),
      )
    },
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to delete key')
    },
    onSuccess: (_, key) => {
      toast.success(`Key "${key}" deleted`)
      setConfirmDelete(null)
      setSelectedKey(null)
      void queryClient.invalidateQueries({
        queryKey: ['config-keys', orgSlug, projectId],
      })
    },
  })

  const toggleReveal = (envSlug: string, key: string) => {
    const ref = `${envSlug}::${key}`
    setRevealed((prev) => {
      const next = { ...prev }
      if (next[ref]) delete next[ref]
      else next[ref] = true
      return next
    })
  }

  const handleCommitValue = (envSlug: string, value: string) => {
    if (!selected) return
    setMutation.mutate({
      data_type: selected.data_type,
      environment: envSlug,
      key: selected.key,
      secret: selected.secret,
      value,
    })
  }

  const handleCommitType = (newType: DataType) => {
    if (!selected) return
    // Optimistic override so the segmented control reflects the click
    // immediately, before the round-trip lands.
    setTypeOverride({ key: selected.key, type: newType })
    const targets = envSlugs.filter((slug) => selected.envs[slug])
    if (targets.length === 0) {
      flashSaved()
      return
    }
    Promise.all(
      targets.map((env) => {
        const cached =
          (valuesByEnv[env]?.[selected.key] as string | undefined) ?? ''
        return setConfigurationValue(
          orgSlug,
          projectId,
          selected.key,
          {
            data_type: newType,
            secret: newType === 'secret',
            value: cached,
          },
          { environment: env, source: activeSource },
        )
      }),
    )
      .then(() => {
        flashSaved()
        void queryClient.invalidateQueries({
          queryKey: ['config-keys', orgSlug, projectId],
        })
      })
      .catch((err) => {
        toast.error(extractApiErrorDetail(err) ?? 'Failed to change data type')
      })
      .finally(() => {
        setTypeOverride(null)
      })
  }

  const handleCreate = async () => {
    if (!draft.key.trim()) {
      toast.error('Key is required')
      return
    }
    const targets = envSlugs.filter((slug) => draft.values[slug]?.trim())
    if (targets.length === 0) {
      toast.error('Set a value for at least one environment')
      return
    }
    try {
      await Promise.all(
        targets.map((env) =>
          setConfigurationValue(
            orgSlug,
            projectId,
            draft.key.trim(),
            {
              data_type: draft.data_type,
              secret: draft.data_type === 'secret',
              value: draft.values[env],
            },
            { environment: env, source: activeSource },
          ),
        ),
      )
      toast.success(`Key "${draft.key.trim()}" created`)
      setMode('view')
      setSelectedKey(draft.key.trim())
      void queryClient.invalidateQueries({
        queryKey: ['config-keys', orgSlug, projectId],
      })
    } catch (err) {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to create key')
    }
  }

  if (sources.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <CardTitle className="mb-2">No Configuration Plugin</CardTitle>
          <p className="text-secondary text-sm">
            No configuration plugin is assigned to this project. Configure
            plugins on the project type or in project settings.
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-3">
      {sources.length > 1 && (
        <div className="flex items-center gap-3">
          <span className="text-secondary text-sm">Source:</span>
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

      {displayPrefix && (
        <div className="text-secondary text-xs">
          <span className="text-tertiary">Prefix:</span>{' '}
          <span className="text-primary font-mono">{displayPrefix}</span>
        </div>
      )}

      <div className="border-primary bg-primary grid h-[calc(100dvh-460px)] min-h-80 grid-cols-[420px_1fr] overflow-hidden rounded-lg border">
        {/* LEFT pane: filter + key list */}
        <div className="border-primary bg-secondary flex min-h-0 flex-col border-r">
          <div className="border-primary flex h-14 shrink-0 items-center border-b px-3.5">
            <div className="relative flex w-full items-center">
              <Search
                aria-hidden
                className="text-tertiary pointer-events-none absolute left-3 size-3.5"
              />
              <Input
                className="h-8 pl-9 font-mono text-xs"
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter"
                value={filter}
              />
            </div>
          </div>
          {isLoading ? (
            <LoadingState label="Loading..." />
          ) : loadError ? (
            <ConfigLoadError error={loadError} />
          ) : filtered.length === 0 ? (
            <div className="text-tertiary px-5 py-10 text-center text-sm">
              {filter
                ? `No parameters match "${filter}"`
                : 'No configuration keys yet.'}
            </div>
          ) : (
            <ParamList
              filter={filter}
              items={filtered}
              onSelect={(k) => {
                setSelectedKey(k)
                setMode('view')
              }}
              prefix={prefix}
              selectedKey={mode === 'create' ? null : selectedKey}
            />
          )}
        </div>

        {/* RIGHT pane */}
        <div className="bg-primary flex min-h-0 flex-col">
          {mode === 'create' ? (
            <DetailPane
              draft={draft}
              environments={sortedEnvironments}
              isCreate
              onCancel={() => setMode('view')}
              onCreate={handleCreate}
              onDraftChange={setDraft}
              prefix={prefix}
              savedFlash={false}
            />
          ) : selected ? (
            <DetailPane
              environments={sortedEnvironments}
              onAdd={() => setMode('create')}
              onCommitType={handleCommitType}
              onCommitValue={handleCommitValue}
              onDelete={() => setConfirmDelete(selected.key)}
              onToggleReveal={toggleReveal}
              prefix={prefix}
              revealed={revealed}
              savedFlash={savedFlash}
              selected={selected}
              typeOverride={
                typeOverride && typeOverride.key === selected.key
                  ? typeOverride.type
                  : null
              }
              valueLoadingByEnv={valueLoadingByEnv}
              valuesByEnv={valuesByEnv}
            />
          ) : (
            <EmptyState onAdd={() => setMode('create')} />
          )}
        </div>
      </div>

      <ConfirmDialog
        description={`Delete key "${confirmDelete ?? ''}" from every environment? This cannot be undone.`}
        onCancel={() => setConfirmDelete(null)}
        onConfirm={() => {
          if (confirmDelete) deleteMutation.mutate(confirmDelete)
        }}
        open={confirmDelete !== null}
        title="Delete Configuration Key"
      />
    </div>
  )
}

function aggregate(
  perEnv: Array<{ envSlug: string; keys: ConfigKeyResponse[] }>,
): AggregatedKey[] {
  const map = new Map<string, AggregatedKey>()
  for (const { envSlug, keys } of perEnv) {
    for (const k of keys) {
      const dt: DataType = DATA_TYPES.includes(k.data_type as DataType)
        ? (k.data_type as DataType)
        : 'string'
      let entry = map.get(k.key)
      if (!entry) {
        entry = {
          data_type: dt,
          envs: {},
          key: k.key,
          last_modified: k.last_modified,
          secret: k.secret,
        }
        map.set(k.key, entry)
      }
      entry.envs[envSlug] = {
        data_type: dt,
        last_modified: k.last_modified,
        secret: k.secret,
      }
      // Promote the most recent last_modified across envs for the key card.
      if (
        k.last_modified &&
        (!entry.last_modified || k.last_modified > entry.last_modified)
      ) {
        entry.last_modified = k.last_modified
      }
      entry.secret = entry.secret || k.secret
      entry.data_type = dt
    }
  }
  return Array.from(map.values()).sort((a, b) => a.key.localeCompare(b.key))
}

function commonPrefix(keys: string[]): string {
  if (keys.length === 0) return ''
  const segs = keys[0].split('/')
  let prefix = ''
  for (let i = 0; i < segs.length; i++) {
    const candidate = (prefix ? prefix + '/' : '') + segs[i]
    if (keys.every((k) => k === candidate || k.startsWith(candidate + '/'))) {
      prefix = candidate
    } else {
      break
    }
  }
  // Only collapse a prefix if it's at least 3 segments deep — otherwise the
  // collapsed view hides too little to be worth the indirection.
  if (prefix.split('/').filter(Boolean).length < COMMON_PREFIX_MIN_DEPTH) {
    return ''
  }
  return prefix.endsWith('/') ? prefix : prefix + '/'
}

function ConfigLoadError({ error }: { error: unknown }) {
  // FastAPI's identity_required 401 has detail = {error, plugin_id, start_url}
  const detail =
    error instanceof ApiError
      ? (
          error.data as
            | undefined
            | {
                detail?:
                  | string
                  | { error?: string; plugin_id?: string; start_url?: string }
              }
        )?.detail
      : undefined
  const isIdentityRequired =
    error instanceof ApiError &&
    error.status === 401 &&
    typeof detail === 'object' &&
    detail?.error === 'identity_required'
  const startUrl =
    isIdentityRequired && typeof detail === 'object'
      ? detail.start_url
      : undefined

  if (isIdentityRequired) {
    return (
      <div className="space-y-2 px-5 py-10 text-center text-sm">
        <div className="text-primary">Connect your account to continue</div>
        <div className="text-tertiary text-xs">
          The configuration plugin needs an authenticated identity for your
          user.
        </div>
        {startUrl && (
          <a
            className="text-amber-text inline-flex items-center text-xs font-medium hover:underline"
            href={startUrl}
            rel="noreferrer"
            target="_blank"
          >
            Connect now →
          </a>
        )}
      </div>
    )
  }

  const isUnavailable = error instanceof ApiError && error.status === 503
  return (
    <div className="space-y-1 px-5 py-10 text-center text-sm">
      <div className="text-danger">
        {isUnavailable
          ? 'Configuration plugin is not available'
          : 'Failed to load configuration keys'}
      </div>
      <div className="text-tertiary text-xs">
        {extractApiErrorDetail(error)}
      </div>
    </div>
  )
}

// True when the value (or any comma-separated segment of it) embeds a
// URL credential pair like `scheme://user:password@host`. Used to mask
// non-secret keys whose values still carry sensitive material.
function containsCredentials(value: string): boolean {
  if (!value) return false
  const re = /[a-z][a-z0-9+\-.]*:\/\/[^:@/\s]+:[^@/\s]+@/i
  return value.split(',').some((part) => re.test(part.trim()))
}

function DetailPane({
  draft,
  environments,
  isCreate,
  onAdd,
  onCancel,
  onCommitType,
  onCommitValue,
  onCreate,
  onDelete,
  onDraftChange,
  onToggleReveal,
  prefix,
  revealed,
  savedFlash,
  selected,
  typeOverride,
  valueLoadingByEnv,
  valuesByEnv,
}: DetailPaneProps) {
  // Defensively force `secret` to win over `data_type` so the picker
  // reflects what the lock icon already conveys in the list.
  const liveType: DataType = isCreate
    ? draft!.data_type
    : selected?.secret
      ? 'secret'
      : (selected?.data_type ?? 'string')
  const currentType: DataType =
    !isCreate && typeOverride ? typeOverride : liveType

  const currentKey = isCreate ? draft!.key : (selected?.key ?? '')
  const showsPrefix = prefix && currentKey.startsWith(prefix)
  const keyTail = showsPrefix ? currentKey.slice(prefix.length) : currentKey

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Header: type segmented + saved + add */}
      <div className="border-primary flex h-14 shrink-0 items-center gap-2 border-b px-6">
        <div className="border-secondary bg-primary inline-flex rounded-md border p-0.5">
          {DATA_TYPES.map((t) => (
            <button
              className={cn(
                'inline-flex h-7 items-center gap-1.5 rounded-[5px] px-2.5 text-xs font-medium transition-colors',
                currentType === t
                  ? 'bg-amber-bg text-amber-text shadow-sm'
                  : 'text-secondary hover:bg-tertiary hover:text-primary',
              )}
              key={t}
              onClick={() => {
                if (isCreate) {
                  onDraftChange?.({ ...draft!, data_type: t })
                } else {
                  onCommitType?.(t)
                }
              }}
              type="button"
            >
              {t === 'secret' && <Lock className="size-2.5" />}
              {DATA_TYPE_LABELS[t]}
            </button>
          ))}
        </div>
        <div className="flex-1" />
        {savedFlash && (
          <span className="text-success inline-flex items-center gap-1 text-xs">
            <Check className="size-3" /> Saved
          </span>
        )}
        {!isCreate && onAdd && (
          <Button onClick={onAdd} size="sm">
            <Plus className="size-3" /> Add parameter
          </Button>
        )}
      </div>

      {/* Name */}
      <div className="border-primary border-b px-6 py-4">
        <div className="text-overline text-tertiary mb-1.5 uppercase">Name</div>
        <div className="border-secondary bg-primary flex items-stretch overflow-hidden rounded-md border">
          {prefix && (
            <span className="border-primary bg-secondary text-tertiary inline-flex items-center border-r px-2.5 font-mono text-xs whitespace-nowrap">
              {prefix}
            </span>
          )}
          {isCreate ? (
            <input
              autoFocus
              className="text-primary placeholder:text-tertiary h-9 flex-1 bg-transparent px-3 font-mono text-xs outline-none"
              onChange={(e) =>
                onDraftChange?.({
                  ...draft!,
                  key: (showsPrefix ? prefix : '') + e.target.value,
                })
              }
              placeholder="component/setting/name"
              value={keyTail}
            />
          ) : (
            <span className="text-primary flex-1 px-3 py-2 font-mono text-xs">
              {keyTail || currentKey}
            </span>
          )}
        </div>
      </div>

      {/* Body: env rows. The grid lives on the parent so the env-label
          column auto-sizes to the widest label across all rows. */}
      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="grid grid-cols-[max-content_1fr] items-start gap-x-4 gap-y-3.5">
          {environments.map((env) => {
            const envValue = isCreate
              ? (draft!.values[env.slug] ?? '')
              : ((valuesByEnv?.[env.slug]?.[currentKey] as
                  | string
                  | undefined) ?? undefined)
            const isSet = !isCreate && Boolean(selected?.envs[env.slug])
            // Treat the row as loading when the env claims this key is
            // set but its value query hasn't landed yet — that's the
            // window where an editable input could overwrite a value
            // the user never saw.
            const isLoadingValue =
              !isCreate && isSet && Boolean(valueLoadingByEnv?.[env.slug])
            return (
              <EnvRow
                dataType={currentType}
                env={env}
                isCreate={Boolean(isCreate)}
                isLoadingValue={isLoadingValue}
                isSecret={
                  isCreate
                    ? currentType === 'secret'
                    : Boolean(
                        selected?.envs[env.slug]?.secret ?? selected?.secret,
                      )
                }
                isSet={isSet}
                key={env.slug}
                onCommit={(v) => {
                  if (isCreate) {
                    onDraftChange?.({
                      ...draft!,
                      values: { ...draft!.values, [env.slug]: v },
                    })
                  } else {
                    onCommitValue?.(env.slug, v)
                  }
                }}
                onToggleReveal={() => onToggleReveal?.(env.slug, currentKey)}
                revealed={
                  !isCreate && Boolean(revealed?.[`${env.slug}::${currentKey}`])
                }
                value={envValue}
              />
            )
          })}
        </div>
      </div>

      {/* Footer */}
      <div className="border-primary flex shrink-0 items-center gap-2 border-t px-6 py-3">
        {isCreate ? (
          <>
            <div className="flex-1" />
            <Button onClick={onCancel} size="sm" variant="outline">
              Cancel
            </Button>
            <Button onClick={onCreate} size="sm">
              <Plus className="size-3" /> Save
            </Button>
          </>
        ) : (
          <>
            <Button
              className="text-danger hover:text-danger"
              onClick={onDelete}
              size="sm"
              variant="ghost"
            >
              <Trash2 className="size-3" /> Delete parameter
            </Button>
            <div className="flex-1" />
            {selected?.last_modified && (
              <span className="text-tertiary text-xs">
                Last modified{' '}
                {new Date(selected.last_modified).toLocaleString()}
              </span>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-10 text-center">
      <Settings2 aria-hidden className="text-tertiary size-7" />
      <div className="text-secondary text-sm">
        Select a parameter to view its values.
      </div>
      <Button onClick={onAdd} size="sm" variant="outline">
        <Plus className="size-3" /> Add parameter
      </Button>
    </div>
  )
}

function EnvRow({
  dataType,
  env,
  isCreate,
  isLoadingValue,
  isSecret,
  isSet,
  onCommit,
  onToggleReveal,
  revealed,
  value,
}: EnvRowProps) {
  const { isDarkMode } = useTheme()
  const chip = env.label_color
    ? deriveChipColors(env.label_color, isDarkMode)
    : null

  const [local, setLocal] = useState(value ?? '')
  const [focused, setFocused] = useState(false)
  const initialRef = useRef(value ?? '')

  useEffect(() => {
    if (!focused) {
      setLocal(value ?? '')
      initialRef.current = value ?? ''
    }
  }, [value, focused])

  const handleBlur = () => {
    setFocused(false)
    if (local !== initialRef.current) {
      onCommit(local)
      initialRef.current = local
    }
  }

  // Mask whenever the param is flagged secret OR the value embeds URL
  // credentials — non-secret string_list params often hold connection
  // strings (rabbitmq, postgres) whose passwords still shouldn't be shown
  // in plain text. The eye toggle reveals on demand either way.
  const looksSensitive = !isCreate && containsCredentials(local)
  const shouldMask =
    !isCreate &&
    (isSecret || looksSensitive) &&
    !revealed &&
    !focused &&
    (isSet || Boolean(local))
  const placeholder = isLoadingValue
    ? 'Loading…'
    : isCreate
      ? 'Optional'
      : isSet
        ? ''
        : 'Not set'
  const display = isLoadingValue
    ? ''
    : shouldMask
      ? maskSecret(local)
      : focused || revealed || isCreate
        ? local
        : (local ?? '')

  const showRevealButton =
    !isCreate &&
    !isLoadingValue &&
    (isSecret || looksSensitive) &&
    (isSet || Boolean(local))

  return (
    <>
      <div className="pt-2">
        <span
          className="inline-flex h-6 items-center rounded-md px-2 text-xs font-medium whitespace-nowrap"
          style={
            chip
              ? {
                  backgroundColor: chip.bg,
                  color: chip.fg,
                }
              : undefined
          }
        >
          {env.name}
        </span>
      </div>
      <div className="flex items-start gap-1.5">
        {dataType === 'string_list' ? (
          <textarea
            className={cn(
              'block w-full resize-y rounded-md border bg-transparent px-3 py-2 font-mono text-xs leading-relaxed text-primary transition-colors outline-none placeholder:text-tertiary',
              focused
                ? 'border-amber-border bg-primary ring-2 ring-amber-border/30'
                : 'border-transparent hover:bg-tertiary',
              isLoadingValue && 'animate-pulse cursor-wait',
            )}
            disabled={isLoadingValue}
            onBlur={handleBlur}
            onChange={(e) => {
              if (!shouldMask && !isLoadingValue) setLocal(e.target.value)
            }}
            onFocus={() => setFocused(true)}
            placeholder={placeholder}
            rows={2}
            value={display}
          />
        ) : (
          <input
            className={cn(
              'block h-9 w-full rounded-md border bg-transparent px-3 font-mono text-xs text-primary transition-colors outline-none placeholder:text-tertiary',
              focused
                ? 'border-amber-border bg-primary ring-2 ring-amber-border/30'
                : 'border-transparent hover:bg-tertiary',
              isLoadingValue && 'animate-pulse cursor-wait',
            )}
            disabled={isLoadingValue}
            onBlur={handleBlur}
            onChange={(e) => {
              if (!shouldMask && !isLoadingValue) setLocal(e.target.value)
            }}
            onFocus={() => setFocused(true)}
            placeholder={placeholder}
            type="text"
            value={display}
          />
        )}
        {showRevealButton && (
          <Button
            aria-label={revealed ? 'Hide value' : 'Reveal value'}
            className="mt-0.5 h-7 px-1.5"
            onClick={onToggleReveal}
            size="sm"
            type="button"
            variant="ghost"
          >
            {revealed ? (
              <EyeOff className="size-3" />
            ) : (
              <Eye className="size-3" />
            )}
          </Button>
        )}
      </div>
    </>
  )
}

function Highlight({ q, text }: { q: string; text: string }) {
  if (!q) return <>{text}</>
  const idx = text.toLowerCase().indexOf(q.toLowerCase())
  if (idx < 0) return <>{text}</>
  return (
    <>
      {text.slice(0, idx)}
      <mark className="bg-amber-border/25 rounded-sm px-0 text-inherit">
        {text.slice(idx, idx + q.length)}
      </mark>
      {text.slice(idx + q.length)}
    </>
  )
}

// If the value looks like a connection URL with embedded credentials
// (scheme://user:password@host…), mask only the password segment.
// Otherwise mask the whole value with bullets capped at a sensible length.
// For string_list values (comma-separated), each entry is masked
// independently so a list of URLs only hides each URL's password.
function maskSecret(value: string): string {
  if (!value) return ''
  if (value.includes(',')) {
    return value
      .split(',')
      .map((part) => {
        // Preserve surrounding whitespace so the rendered list doesn't
        // shift when toggling reveal.
        const leading = part.match(/^\s*/)?.[0] ?? ''
        const trailing = part.match(/\s*$/)?.[0] ?? ''
        const inner = part.slice(leading.length, part.length - trailing.length)
        return leading + maskSecretSingle(inner) + trailing
      })
      .join(',')
  }
  return maskSecretSingle(value)
}

function maskSecretSingle(value: string): string {
  if (!value) return ''
  const url = /^([a-z][a-z0-9+\-.]*:\/\/)([^:@/\s]+):([^@/\s]+)(@.*)$/i.exec(
    value,
  )
  if (url) {
    return `${url[1]}${url[2]}:${'•'.repeat(8)}${url[4]}`
  }
  return '•'.repeat(Math.min(40, value.length || 8))
}

function ParamList({
  filter,
  items,
  onSelect,
  prefix,
  selectedKey,
}: ParamListProps) {
  return (
    <div className="flex-1 overflow-y-auto">
      {items.map((p) => {
        const isSelected = p.key === selectedKey
        const display =
          prefix && p.key.startsWith(prefix)
            ? p.key.slice(prefix.length)
            : p.key
        return (
          <button
            className={cn(
              'flex w-full items-center gap-2.5 border-b border-primary px-3.5 py-2.5 text-left transition-colors',
              isSelected ? 'bg-amber-bg' : 'hover:bg-tertiary',
            )}
            key={p.key}
            onClick={() => onSelect(p.key)}
            style={{
              borderLeft: isSelected
                ? '2px solid var(--color-action-bg)'
                : '2px solid transparent',
            }}
            type="button"
          >
            <span
              className={cn(
                'flex-1 overflow-hidden font-mono text-xs text-ellipsis whitespace-nowrap',
                isSelected ? 'text-amber-text' : 'text-primary',
                isSelected && 'font-medium',
              )}
              style={{ direction: 'rtl', textAlign: 'left' }}
              title={p.key}
            >
              <span style={{ direction: 'ltr', unicodeBidi: 'bidi-override' }}>
                <Highlight q={filter} text={display} />
              </span>
            </span>
            {p.secret && <Lock aria-hidden className="text-tertiary size-3" />}
          </button>
        )
      })}
    </div>
  )
}
