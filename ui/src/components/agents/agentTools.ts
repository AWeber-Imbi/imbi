import type { AgentToolConfig, AgentToolGroup } from '@/types'

import type { AgentTools } from './agentDraft'

// The rules of the Tools and MCPs tab, without React: filters, the
// rows of each server group, and the edits to the tool map.

export type Capability = AgentToolGroup['tools'][number]['capability']

export type RatePeriod = NonNullable<AgentToolConfig['rate_limit']>['per']

export const CAPABILITIES: {
  label: string
  slug: Capability
  tone: 'danger' | 'neutral' | 'success' | 'warning'
}[] = [
  { label: 'Read', slug: 'read', tone: 'success' },
  { label: 'Write', slug: 'write', tone: 'warning' },
  { label: 'Destructive', slug: 'destructive', tone: 'danger' },
  { label: 'Unknown', slug: 'unknown', tone: 'neutral' },
]

export const RATE_PERIODS: {
  label: string
  short: string
  value: RatePeriod
}[] = [
  { label: 'Per minute', short: 'min', value: 'minute' },
  { label: 'Per hour', short: 'hr', value: 'hour' },
  { label: 'Per day', short: 'day', value: 'day' },
]

/** The configuration of a tool when it is switched on. */
export const DEFAULT_TOOL_CONFIG: AgentToolConfig = {
  approval: false,
  environments: null,
  rate_limit: null,
}

export interface ToolFilters {
  capabilities: Set<string>
  enabledOnly: boolean
  query: string
}

export interface ToolGroupView {
  /** Every row of the group before the filters. */
  allRows: ToolRow[]
  error: null | string
  name: string
  rows: ToolRow[]
  slug: string
  transport: string
}

export interface ToolRow {
  capability: Capability | null
  description: null | string
  key: string
  /** The tool is enabled, but the catalog does not list it now. */
  unavailable: boolean
}

/** The short form of a rate limit, for example "6 / hr". */
export function formatRateLimit(config: AgentToolConfig): string {
  const limit = config.rate_limit
  if (!limit) return 'No limit'
  const short = RATE_PERIODS.find((p) => p.value === limit.per)?.short
  return `${limit.count} / ${short ?? limit.per}`
}

/**
 * The groups to show. A tool that is enabled but not in the catalog
 * is an "unavailable" row in the group of its server, or in a group of
 * its own when the catalog has no such server, so it can be removed.
 */
export function groupViews(
  groups: AgentToolGroup[],
  tools: AgentTools,
  filters: ToolFilters,
): ToolGroupView[] {
  const listed = new Set(groups.flatMap((g) => g.tools.map((t) => t.key)))
  const orphans = Object.keys(tools)
    .filter((key) => !listed.has(key))
    .sort()
  const known = new Set(groups.map((g) => g.server.slug))
  const views: ToolGroupView[] = groups.map((g) => ({
    allRows: [
      ...g.tools.map((t) => ({
        capability: t.capability,
        description: t.description ?? null,
        key: t.key,
        unavailable: false,
      })),
      ...orphans
        .filter((key) => serverOf(key) === g.server.slug)
        .map(unavailableRow),
    ],
    error: g.error ?? null,
    name: g.server.name,
    rows: [],
    slug: g.server.slug,
    transport: g.server.transport,
  }))
  const lost = orphans.filter((key) => !known.has(serverOf(key)))
  if (lost.length)
    views.push({
      allRows: lost.map(unavailableRow),
      error: null,
      name: 'Not in the catalog',
      rows: [],
      slug: '',
      transport: 'unavailable',
    })
  const query = filters.query.trim().toLowerCase()
  for (const view of views) {
    view.rows = view.allRows.filter((row) => {
      if (filters.enabledOnly && !tools[row.key]) return false
      if (
        filters.capabilities.size &&
        !(row.capability && filters.capabilities.has(row.capability))
      )
        return false
      if (!query) return true
      return `${row.key} ${row.description ?? ''} ${view.name}`
        .toLowerCase()
        .includes(query)
    })
  }
  const filtering =
    !!query || filters.enabledOnly || filters.capabilities.size > 0
  // An error must stay visible, so a failed server is not hidden.
  return views.filter((v) => !filtering || v.rows.length > 0 || v.error)
}

/** The server slug of a tool key (`<server>.<tool>`). */
export function serverOf(key: string): string {
  return key.slice(0, key.indexOf('.'))
}

/** Switch every tool in `keys` on (keeping a stored config) or off. */
export function setTools(
  tools: AgentTools,
  keys: string[],
  on: boolean,
): AgentTools {
  const next = { ...tools }
  for (const key of keys) {
    if (on) next[key] = next[key] ?? { ...DEFAULT_TOOL_CONFIG }
    else delete next[key]
  }
  return next
}

/**
 * Allow or block one environment. `null` means every environment. The
 * last environment cannot be blocked: switch the tool off instead.
 */
export function toggleEnvironment(
  config: AgentToolConfig,
  slug: string,
  all: string[],
): AgentToolConfig {
  const current = config.environments ?? all
  const next = current.includes(slug)
    ? current.filter((s) => s !== slug)
    : [...current, slug]
  if (!next.length) return config
  const allowed = all.every((s) => next.includes(s))
  return { ...config, environments: allowed ? null : [...next].sort() }
}

function unavailableRow(key: string): ToolRow {
  return { capability: null, description: null, key, unavailable: true }
}
