import type { AgentToolCatalog, AgentToolConfig } from '@/types'

import type { AgentTools } from './agentDraft'

// The rules of the Tools tab, without React: filters, the rows of
// each group, and the edits to the tool map.

export type Capability = AgentToolCatalog['tools'][number]['capability']

export type ToolErrorCode = NonNullable<AgentToolCatalog['error']>

/** The message for each error code of the catalog. */
export const TOOL_ERROR_MESSAGES: Record<ToolErrorCode, string> = {
  auth_failed: 'the API did not accept the credentials.',
  timeout: 'the API did not answer in time.',
  unreachable: 'the API is not reachable.',
}

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

/** The group slug of the Imbi tools, and the prefix of their keys. */
export const IMBI_SLUG = 'imbi'

/**
 * The group slug of the opt-in Claude Code built-in tools (Skill,
 * Agent), and the prefix of their keys. They are off until switched on.
 */
export const BUILTIN_SLUG = 'builtin'

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
  error: null | ToolErrorCode
  name: string
  rows: ToolRow[]
  slug: string
}

export interface ToolRow {
  capability: Capability | null
  description: null | string
  key: string
  /** The tool is enabled, but the catalog does not list it now. */
  unavailable: boolean
}

/** Every tool that the catalog lists: the Imbi and built-in tools. */
export function catalogTools(
  catalog: AgentToolCatalog,
): AgentToolCatalog['tools'] {
  return [...(catalog.builtin_tools ?? []), ...catalog.tools]
}

/** The short form of a rate limit, for example "6 / hr". */
export function formatRateLimit(config: AgentToolConfig): string {
  const limit = config.rate_limit
  if (!limit) return 'No limit'
  const short = RATE_PERIODS.find((p) => p.value === limit.per)?.short
  return `${limit.count} / ${short ?? limit.per}`
}

/**
 * The groups to show: the opt-in built-in tools, the Imbi tools, and
 * then each tool that is enabled but not in the catalog, for example a
 * `zoekt.*` key from an earlier release, as an "unavailable" row so it
 * can be removed.
 */
export function groupViews(
  catalog: AgentToolCatalog,
  tools: AgentTools,
  filters: ToolFilters,
): ToolGroupView[] {
  const listed = new Set(catalogTools(catalog).map((t) => t.key))
  const lost = Object.keys(tools)
    .filter((key) => !listed.has(key))
    .sort()
  const builtins = catalog.builtin_tools ?? []
  const views: ToolGroupView[] = []
  if (builtins.length)
    views.push({
      allRows: builtins.map(catalogRow),
      error: null,
      name: 'Built-in',
      rows: [],
      slug: BUILTIN_SLUG,
    })
  views.push({
    allRows: catalog.tools.map(catalogRow),
    error: catalog.error ?? null,
    name: 'Imbi',
    rows: [],
    slug: IMBI_SLUG,
  })
  if (lost.length)
    views.push({
      allRows: lost.map(unavailableRow),
      error: null,
      name: 'Not in the catalog',
      rows: [],
      slug: '',
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
  // An error must stay visible, so a failed group is not hidden.
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

function catalogRow(tool: AgentToolCatalog['tools'][number]): ToolRow {
  return {
    capability: tool.capability,
    description: tool.description ?? null,
    key: tool.key,
    unavailable: false,
  }
}

function unavailableRow(key: string): ToolRow {
  return { capability: null, description: null, key, unavailable: true }
}
