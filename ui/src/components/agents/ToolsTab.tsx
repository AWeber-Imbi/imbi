import { useState } from 'react'

import { AlertCircle, ChevronDown, ChevronRight, RefreshCw } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ErrorBanner } from '@/components/ui/error-banner'
import { FilterPopover } from '@/components/ui/filter-popover'
import { Input } from '@/components/ui/input'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Sk } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { formatRelativeDate } from '@/lib/formatDate'
import { cn } from '@/lib/utils'
import type { AgentToolConfig } from '@/types'

import type { AgentTools } from './agentDraft'
import { useAgentToolCatalog, useOrgEnvironments } from './agentQueries'
import {
  CAPABILITIES,
  formatRateLimit,
  groupViews,
  RATE_PERIODS,
  type RatePeriod,
  setTools,
  toggleEnvironment,
  type ToolGroupView,
  type ToolRow,
} from './agentTools'

/** A group shows at most this many rows. Search to see the others. */
const ROW_LIMIT = 50

interface EnvironmentChip {
  name: string
  slug: string
}

interface ToolGroupCardProps {
  environments: EnvironmentChip[]
  isOpen: boolean
  onChange: (tools: AgentTools) => void
  onConfigChange: (key: string, config: AgentToolConfig) => void
  onToggleOpen: () => void
  tools: AgentTools
  view: ToolGroupView
}

interface ToolRowViewProps {
  config: AgentToolConfig | undefined
  environments: EnvironmentChip[]
  onConfigChange: (config: AgentToolConfig) => void
  onToggle: (checked: boolean) => void
  row: ToolRow
}

interface ToolsTabProps {
  onChange: (tools: AgentTools) => void
  orgSlug: string
  value: AgentTools
}

/**
 * The tools that the agent can use, in groups by server. A switch turns
 * a tool on; then approval, environments, and a rate limit apply to it.
 */
export function ToolsTab({ onChange, orgSlug, value }: ToolsTabProps) {
  const { query: catalog, refresh } = useAgentToolCatalog(orgSlug)
  const environments = useOrgEnvironments(orgSlug)
  const [search, setSearch] = useState('')
  const [capabilities, setCapabilities] = useState<Set<string>>(new Set())
  const [enabledOnly, setEnabledOnly] = useState(false)
  const [open, setOpen] = useState<Set<string>>(new Set())

  if (catalog.isLoading)
    return (
      <div className="flex flex-col gap-3">
        <Sk h={40} r={6} />
        <Sk h={56} r={8} />
        <Sk h={56} r={8} />
      </div>
    )
  if (catalog.isError || !catalog.data)
    return (
      <ErrorBanner error={catalog.error} title="Failed to load the tools" />
    )

  const groups = catalog.data.groups
  const filters = { capabilities, enabledOnly, query: search }
  const views = groupViews(groups, value, filters)
  const filtering = !!search.trim() || enabledOnly || capabilities.size > 0
  const total = groups.reduce((n, g) => n + g.tools.length, 0)
  const enabled = Object.keys(value).length
  const chips: EnvironmentChip[] = (environments.data ?? []).map((e) => ({
    name: e.name,
    slug: e.slug,
  }))

  const counts: Record<string, number> = {}
  for (const g of groups)
    for (const t of g.tools)
      counts[t.capability] = (counts[t.capability] ?? 0) + 1

  const setConfig = (key: string, config: AgentToolConfig) =>
    onChange({ ...value, [key]: config })

  return (
    <div className="flex flex-col gap-4">
      <p className="text-secondary text-sm">
        Imbi does not run agents yet. These settings are stored for when it
        does.
      </p>
      <div className="flex items-center gap-3">
        <div className="flex-1">
          <Input
            aria-label="Search tools"
            onChange={(e) => setSearch(e.target.value)}
            placeholder={`Search ${total.toLocaleString()} tools — name, server, or description`}
            value={search}
          />
        </div>
        <FilterPopover
          activeFilters={capabilities}
          label="Capability"
          onClear={() => setCapabilities(new Set())}
          onToggle={(slug) => {
            const next = new Set(capabilities)
            if (next.has(slug)) next.delete(slug)
            else next.add(slug)
            setCapabilities(next)
          }}
          options={CAPABILITIES.map((c) => ({
            count: counts[c.slug] ?? 0,
            label: c.label,
            slug: c.slug,
          }))}
          variant="button"
        />
        <Button
          aria-pressed={enabledOnly}
          onClick={() => setEnabledOnly(!enabledOnly)}
          size="sm"
          variant={enabledOnly ? 'default' : 'outline'}
        >
          Enabled only
        </Button>
        <Button
          aria-label="Refresh the tool list"
          disabled={refresh.isPending}
          onClick={() => refresh.mutate()}
          size="sm"
          title={`Listed ${formatRelativeDate(catalog.data.generated_at)}. List the tools again.`}
          variant="outline"
        >
          <RefreshCw className={cn(refresh.isPending && 'animate-spin')} />
        </Button>
        <span className="text-tertiary font-mono text-sm whitespace-nowrap tabular-nums">
          {enabled} of {total} enabled
        </span>
      </div>
      {refresh.error && (
        <ErrorBanner
          error={refresh.error}
          title="Failed to list the tools again"
        />
      )}

      <div className="flex flex-col gap-3">
        {views.map((view) => (
          <ToolGroupCard
            environments={chips}
            isOpen={filtering || open.has(view.slug)}
            key={view.slug}
            onChange={onChange}
            onConfigChange={setConfig}
            onToggleOpen={() => {
              const next = new Set(open)
              if (next.has(view.slug)) next.delete(view.slug)
              else next.add(view.slug)
              setOpen(next)
            }}
            tools={value}
            view={view}
          />
        ))}
        {filtering && views.length === 0 && (
          <div className="bg-card border-border text-tertiary rounded-lg border p-8 text-center text-sm">
            No tools match that search.
          </div>
        )}
      </div>
    </div>
  )
}

function chip(on: boolean, size: string): string {
  return cn(
    'rounded-md border text-xs',
    size,
    on
      ? 'border-action bg-amber-bg text-amber-text font-medium'
      : 'border-input text-secondary hover:bg-secondary',
  )
}

function RateLimitButton({
  config,
  onChange,
}: {
  config: AgentToolConfig
  onChange: (config: AgentToolConfig) => void
}) {
  const [open, setOpen] = useState(false)
  const [count, setCount] = useState('')
  const [per, setPer] = useState<RatePeriod>('hour')
  const valid = /^[1-9]\d*$/.test(count.trim())

  return (
    <Popover
      onOpenChange={(next) => {
        if (next) {
          setCount(config.rate_limit ? String(config.rate_limit.count) : '')
          setPer(config.rate_limit?.per ?? 'hour')
        }
        setOpen(next)
      }}
      open={open}
    >
      <PopoverTrigger asChild>
        <button
          className="border-input text-secondary hover:bg-secondary h-7 rounded-md border px-2 font-mono text-xs whitespace-nowrap"
          title="Rate limit"
          type="button"
        >
          {formatRateLimit(config)}
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64">
        <div className="flex flex-col gap-3">
          <p className="text-secondary text-xs font-medium tracking-wide uppercase">
            Rate limit
          </p>
          <div className="flex gap-2">
            <Input
              aria-label="Calls"
              className="w-20"
              inputMode="numeric"
              onChange={(e) => setCount(e.target.value)}
              placeholder="Calls"
              value={count}
            />
            <Select onValueChange={(v) => setPer(v as RatePeriod)} value={per}>
              <SelectTrigger aria-label="Period">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {RATE_PERIODS.map((p) => (
                  <SelectItem key={p.value} value={p.value}>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {count.trim() && !valid && (
            <p className="text-danger text-xs">Enter a whole number above 0</p>
          )}
          <div className="flex justify-end gap-2">
            {config.rate_limit && (
              <Button
                onClick={() => {
                  onChange({ ...config, rate_limit: null })
                  setOpen(false)
                }}
                size="sm"
                variant="ghost"
              >
                Remove limit
              </Button>
            )}
            <Button
              disabled={!valid}
              onClick={() => {
                onChange({
                  ...config,
                  rate_limit: { count: Number(count.trim()), per },
                })
                setOpen(false)
              }}
              size="sm"
            >
              Apply
            </Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}

function ToolGroupCard({
  environments,
  isOpen,
  onChange,
  onConfigChange,
  onToggleOpen,
  tools,
  view,
}: ToolGroupCardProps) {
  const listed = view.allRows.filter((r) => !r.unavailable)
  const on = view.allRows.filter((r) => tools[r.key]).length
  const allOn = listed.length > 0 && listed.every((r) => tools[r.key])
  const shown = view.rows.slice(0, ROW_LIMIT)
  const Chevron = isOpen ? ChevronDown : ChevronRight
  return (
    <div className="bg-card border-border overflow-hidden rounded-lg border">
      <div className="border-border flex items-center gap-3 border-b px-5 py-3">
        <button
          aria-expanded={isOpen}
          className="flex min-w-0 flex-1 items-center gap-3 text-left"
          onClick={onToggleOpen}
          type="button"
        >
          <Chevron className="text-tertiary size-4 shrink-0" />
          <span className="truncate text-sm font-semibold">{view.name}</span>
          <span className="bg-secondary text-secondary rounded px-2 py-0.5 font-mono text-xs">
            {view.transport}
          </span>
        </button>
        <span className="text-secondary font-mono text-xs whitespace-nowrap tabular-nums">
          {on} of {listed.length} enabled
        </span>
        {(listed.length > 0 || on > 0) && (
          <Button
            onClick={() =>
              onChange(
                allOn || listed.length === 0
                  ? setTools(
                      tools,
                      view.allRows.map((r) => r.key),
                      false,
                    )
                  : setTools(
                      tools,
                      listed.map((r) => r.key),
                      true,
                    ),
              )
            }
            size="sm"
            variant="outline"
          >
            {allOn || listed.length === 0 ? 'Disable all' : 'Enable all'}
          </Button>
        )}
      </div>
      {view.error && (
        <div
          className="text-danger border-border flex items-center gap-2 border-b px-5 py-3 text-sm"
          role="alert"
        >
          <AlertCircle className="size-4 shrink-0" />
          Could not list the tools of this server: {view.error}
        </div>
      )}
      {isOpen && (
        <div className="flex flex-col">
          {shown.map((row) => (
            <ToolRowView
              config={tools[row.key]}
              environments={environments}
              key={row.key}
              onConfigChange={(config) => onConfigChange(row.key, config)}
              onToggle={(checked) =>
                onChange(setTools(tools, [row.key], checked))
              }
              row={row}
            />
          ))}
          {view.rows.length > shown.length && (
            <div className="text-tertiary px-5 py-2 text-xs">
              Showing {shown.length} of {view.rows.length} tools on this server.
              Search to narrow.
            </div>
          )}
          {view.rows.length === 0 && !view.error && (
            <div className="text-tertiary px-5 py-3 text-xs">
              This server lists no tools.
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ToolRowView({
  config,
  environments,
  onConfigChange,
  onToggle,
  row,
}: ToolRowViewProps) {
  const capability = CAPABILITIES.find((c) => c.slug === row.capability)
  const all = environments.map((e) => e.slug)
  return (
    <div className="border-border flex items-center gap-4 border-b px-5 py-3 last:border-b-0">
      <Switch
        aria-label={`Enable ${row.key}`}
        checked={!!config}
        onCheckedChange={onToggle}
      />
      <div className="w-70 min-w-0">
        <div
          className={cn(
            'truncate font-mono text-xs',
            config ? 'text-primary' : 'text-tertiary',
          )}
          title={row.key}
        >
          {row.key}
        </div>
        <div
          className="text-tertiary truncate text-xs"
          title={row.description ?? undefined}
        >
          {row.unavailable
            ? 'The catalog does not list this tool now.'
            : row.description}
        </div>
      </div>
      {row.unavailable ? (
        <Badge variant="neutral">Unavailable</Badge>
      ) : (
        capability && (
          <Badge variant={capability.tone}>{capability.label}</Badge>
        )
      )}
      <span className="flex-1" />
      {config && (
        <div className="flex items-center gap-2">
          <button
            aria-pressed={config.approval}
            className={chip(config.approval, 'h-7 px-2')}
            onClick={() =>
              onConfigChange({ ...config, approval: !config.approval })
            }
            title="Require human approval before each call"
            type="button"
          >
            Approval
          </button>
          {environments.length > 0 && (
            <div className="flex gap-1">
              {environments.map((e) => {
                const allowed =
                  !config.environments || config.environments.includes(e.slug)
                return (
                  <button
                    aria-label={`${e.name}: ${allowed ? 'allowed' : 'blocked'}`}
                    aria-pressed={allowed}
                    className={chip(allowed, 'h-7 px-2 font-mono')}
                    key={e.slug}
                    onClick={() =>
                      onConfigChange(toggleEnvironment(config, e.slug, all))
                    }
                    title={`${e.name} — ${allowed ? 'allowed' : 'blocked'}`}
                    type="button"
                  >
                    {e.slug}
                  </button>
                )
              })}
            </div>
          )}
          <RateLimitButton config={config} onChange={onConfigChange} />
        </div>
      )}
    </div>
  )
}
