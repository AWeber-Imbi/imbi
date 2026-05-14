import type { ReactNode } from 'react'
import {
  Fragment,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import { useSearchParams } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'
import {
  Calendar,
  ChevronRight,
  Copy,
  Download,
  RefreshCw,
  Search,
  Share2,
  X,
} from 'lucide-react'
import { toast } from 'sonner'

import {
  getProjectLogsHistogram,
  listProjectPlugins,
  searchProjectLogs,
} from '@/api/endpoints'
import { LoadingState } from '@/components/ui/loading-state'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useTheme } from '@/contexts/ThemeContext'
import { deriveChipColors } from '@/lib/chip-colors'
import { sortEnvironments } from '@/lib/utils'
import type { Environment, LogEntryResponse } from '@/types'

// ── Types & Interfaces (alphabetical) ─────────────────────────────────────
type DetailTab = 'json' | 'stack' | 'table'

interface ExceptionInfo {
  message: string
  stack: string[]
  type: string
}

interface HistogramBucket {
  count: number
  DEBUG: number
  ERROR: number
  INFO: number
  t: number
  WARN: number
}

interface LogsConfig {
  baseQuery: string
  envs: string[]
  excludeSources: string
  levels: Record<string, boolean>
  range: RelativeRange
  showHistogram: boolean
  wrap: boolean
}

interface LogsTabProps {
  environments?: Environment[]
  orgSlug: string
  projectId: string
}

type RelativeRange = '1d' | '1h' | '7d' | '12h' | '30d'

// ── Constants ──────────────────────────────────────────────────────────────
const DEFAULT_CONFIG: LogsConfig = {
  baseQuery: '',
  envs: ['production', 'staging'],
  excludeSources: '',
  levels: { DEBUG: false, ERROR: true, INFO: true, WARN: true },
  range: '1h',
  showHistogram: true,
  wrap: false,
}

const ENVS = ['production', 'staging', 'testing'] as const

const RANGES: { key: RelativeRange; label: string; ms: number }[] = [
  { key: '1h', label: '1h', ms: 60 * 60_000 },
  { key: '12h', label: '12h', ms: 12 * 60 * 60_000 },
  { key: '1d', label: '1d', ms: 24 * 60 * 60_000 },
  { key: '7d', label: '7d', ms: 7 * 24 * 60 * 60_000 },
  { key: '30d', label: '30d', ms: 30 * 24 * 60 * 60_000 },
]

// Normalise any raw log level string to one of ERROR | WARN | INFO | DEBUG.
// Unknown levels fall through to INFO so they are visible by default.
function normaliseLevel(raw: string): 'DEBUG' | 'ERROR' | 'INFO' | 'WARN' {
  switch (raw.toUpperCase()) {
    case 'ALERT':
    case 'CRIT':
    case 'CRITICAL':
    case 'EMERG':
    case 'ERR':
    case 'FATAL':
    case 'PANIC':
      return 'ERROR'
    case 'DEBUG':
      return 'DEBUG'
    case 'ERROR':
      return 'ERROR'
    case 'INFO':
      return 'INFO'
    case 'SILLY':
    case 'TRACE':
    case 'VERBOSE':
      return 'DEBUG'
    case 'WARN':
      return 'WARN'
    case 'WARNING':
      return 'WARN'
    default:
      return 'INFO'
  }
}

// Severity colours — use theme tokens so they adapt to dark mode.
const SEV_BAR_COLORS: Record<string, string> = {
  DEBUG: 'var(--text-color-tertiary)',
  ERROR: 'var(--text-color-danger)',
  INFO: 'var(--text-color-info)',
  WARN: 'var(--background-color-action)',
}

const CONTAINER_H_DEFAULT = 600 // px — initial scroll-container height
const ROW_H_COLLAPSED = 36 // px — estimated height for a collapsed log row
const VIRTUAL_OVERSCAN = 8 // rows pre-rendered above and below the viewport

// ── Export ─────────────────────────────────────────────────────────────────
export function LogsTab({
  environments = [],
  orgSlug,
  projectId,
}: LogsTabProps) {
  const { isDarkMode } = useTheme()
  const sortedEnvironments = useMemo(
    () => sortEnvironments(environments),
    [environments],
  )
  const envChipColors = useMemo(() => {
    const out: Record<string, ReturnType<typeof deriveChipColors>> = {}
    for (const e of sortedEnvironments) {
      if (e.label_color)
        out[e.slug] = deriveChipColors(e.label_color, isDarkMode)
    }
    return out
  }, [sortedEnvironments, isDarkMode])
  const envOptions = useMemo(
    () =>
      sortedEnvironments.length > 0
        ? sortedEnvironments.map((e) => ({
            color: envChipColors[e.slug],
            name: e.name,
            slug: e.slug,
          }))
        : ENVS.map((slug) => ({ color: null, name: slug, slug })),
    [sortedEnvironments, envChipColors],
  )
  const envSlugToName = useMemo(() => {
    const out: Record<string, string> = {}
    for (const e of sortedEnvironments) out[e.slug] = e.name
    return out
  }, [sortedEnvironments])
  const storageKey = `imbi.logs.config.${projectId}`
  const [searchParams, setSearchParams] = useSearchParams()

  const [config] = useState<LogsConfig>(() => {
    try {
      const saved = localStorage.getItem(storageKey)
      return saved ? (JSON.parse(saved) as LogsConfig) : { ...DEFAULT_CONFIG }
    } catch {
      return { ...DEFAULT_CONFIG }
    }
  })

  useEffect(() => {
    localStorage.setItem(storageKey, JSON.stringify(config))
  }, [config, storageKey])

  const [range, setRange] = useState<RelativeRange>(() => {
    const p = searchParams.get('range')
    return (
      p && RANGES.some((r) => r.key === p) ? p : config.range
    ) as RelativeRange
  })
  const [envs, setEnvs] = useState<string[]>(() => {
    const p = searchParams.getAll('env')
    return p.length > 0 ? p : config.envs
  })
  const [levels, setLevels] = useState<Record<string, boolean>>(() => {
    const p = searchParams.getAll('level')
    if (p.length > 0) {
      return {
        DEBUG: p.includes('DEBUG'),
        ERROR: p.includes('ERROR'),
        INFO: p.includes('INFO'),
        WARN: p.includes('WARN'),
      }
    }
    return config.levels
  })
  const pluginDefaultsApplied = useRef(false)
  const [customStart, setCustomStart] = useState<Date | undefined>(() => {
    const p = searchParams.get('start')
    return p ? new Date(p) : undefined
  })
  const [customEnd, setCustomEnd] = useState<Date | undefined>(() => {
    const p = searchParams.get('end')
    return p ? new Date(p) : undefined
  })
  const [query, setQuery] = useState(() => searchParams.get('q') ?? '')
  const [fieldFilters, setFieldFilters] = useState<string[]>(() =>
    searchParams.getAll('filter'),
  )
  const [datePickerOpen, setDatePickerOpen] = useState(false)
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set())
  const [selectedBucket, setSelectedBucket] = useState<null | number>(null)
  const [cursor, setCursor] = useState<null | string>(null)
  const [accEntries, setAccEntries] = useState<LogEntryResponse[]>([])
  const [startInput, setStartInput] = useState('')
  const [endInput, setEndInput] = useState('')
  const [source, setSource] = useState<string | undefined>()

  // Virtual scroll
  const listRef = useRef<HTMLDivElement>(null)
  // Tracks the actual rendered height of the scroll container so the
  // virtual-scroll math (visStart/visEnd) stays in sync when the panel
  // is sized via CSS calc against the viewport rather than a fixed px.
  const [containerH, setContainerH] = useState(CONTAINER_H_DEFAULT)
  useEffect(() => {
    const el = listRef.current
    if (!el) return
    const update = () => setContainerH(el.clientHeight || CONTAINER_H_DEFAULT)
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  const loadTriggerRef = useRef<HTMLDivElement>(null)
  const rowHeightCache = useRef<Map<string, number>>(new Map())
  const [listScrollTop, setListScrollTop] = useState(0)
  const [heightVersion, setHeightVersion] = useState(0)

  const { data: assignments } = useQuery({
    queryFn: ({ signal }) => listProjectPlugins(orgSlug, projectId, signal),
    queryKey: ['project-plugins', orgSlug, projectId],
    staleTime: 5 * 60_000,
  })

  const logAssignments = assignments?.filter((a) => a.tab === 'logs') ?? []
  const sources = logAssignments.map((a) => ({
    id: a.plugin_id,
    label: a.label,
  }))
  const activeSource = source ?? sources[0]?.id
  const activeAssignment = logAssignments.find(
    (a) => a.plugin_id === activeSource,
  )

  // Apply plugin-level default_environments once, only when there is no
  // user-saved config in localStorage (i.e. first visit for this project).
  useEffect(() => {
    if (pluginDefaultsApplied.current) return
    if (!activeAssignment) return
    const raw = activeAssignment.options['default_environments']
    if (typeof raw !== 'string' || !raw.trim()) return
    const defaults = raw
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
    if (defaults.length === 0) return
    pluginDefaultsApplied.current = true
    const hasLocalConfig = !!localStorage.getItem(storageKey)
    if (!hasLocalConfig) setEnvs(defaults)
  }, [activeAssignment, storageKey])

  // Sync filter state → URL params whenever they change
  useEffect(() => {
    const next = new URLSearchParams()
    next.set('range', range)
    if (customStart) next.set('start', customStart.toISOString())
    if (customEnd) next.set('end', customEnd.toISOString())
    envs.forEach((e) => next.append('env', e))
    Object.entries(levels).forEach(([lv, on]) => {
      if (on) next.append('level', lv)
    })
    if (query.trim()) next.set('q', query.trim())
    fieldFilters.forEach((f) => next.append('filter', f))
    setSearchParams(next, { replace: true })
  }, [
    range,
    envs,
    levels,
    query,
    fieldFilters,
    customStart,
    customEnd,
    setSearchParams,
  ])

  // Stable ISO strings — only recompute when range/custom dates actually change,
  // not on every render (new Date() would produce a different string each time).
  const customStartIso = customStart?.toISOString() ?? null
  const customEndIso = customEnd?.toISOString() ?? null
  const datetimes = useMemo(
    () => rangeToDatetimes(range, customStart, customEnd),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [range, customStartIso, customEndIso],
  )

  const apiFilters = useMemo(() => {
    const filters: string[] = [...fieldFilters]
    config.baseQuery
      .trim()
      .split(/\s+/)
      .forEach((tok) => {
        if (tok.includes(':')) {
          const [k, v] = tok.split(':', 2)
          filters.push(`${k}:eq:${v}`)
        }
      })
    return filters.length ? filters : undefined
  }, [fieldFilters, config.baseQuery])

  const {
    data: logResult,
    error: logError,
    failureCount,
    isFetching,
    refetch,
  } = useQuery({
    enabled: sources.length > 0 && !!activeSource,
    queryFn: ({ signal }) =>
      searchProjectLogs(
        orgSlug,
        projectId,
        {
          cursor: cursor ?? undefined,
          end_time: datetimes.end,
          environment: envs.length > 0 ? envs : undefined,
          filter: apiFilters,
          limit: 100,
          source: activeSource,
          start_time: datetimes.start,
        },
        signal,
      ),
    queryKey: [
      'project-logs',
      orgSlug,
      projectId,
      activeSource,
      range,
      customStartIso,
      customEndIso,
      apiFilters,
      envs,
      cursor,
    ],
    retry: 3,
    retryDelay: (attempt) => Math.min(500 * 2 ** attempt, 15_000),
    staleTime: 0,
  })

  useEffect(() => {
    setAccEntries([])
    setCursor(null)
    setSelectedBucket(null)
  }, [activeSource, range, customStartIso, customEndIso, apiFilters, envs])

  const handleSearch = useCallback(() => {
    setAccEntries([])
    setCursor(null)
    void refetch()
  }, [refetch])

  const handleLoadMore = useCallback(() => {
    if (logResult?.next_cursor) {
      setAccEntries((prev) => [...prev, ...(logResult.entries ?? [])])
      setCursor(logResult.next_cursor)
    }
  }, [logResult])

  const handleAddFilter = useCallback((field: string, value: string) => {
    const isExclude = field.startsWith('-')
    const key = field.replace(/^-/, '')
    const filter = isExclude ? `${key}:ne:${value}` : `${key}:eq:${value}`
    setFieldFilters((prev) =>
      prev.includes(filter) ? prev : [...prev, filter],
    )
    setAccEntries([])
    setCursor(null)
  }, [])

  const allEntries = useMemo(
    () =>
      accEntries.length > 0
        ? [...accEntries, ...(logResult?.entries ?? [])]
        : (logResult?.entries ?? []),
    [accEntries, logResult],
  )

  const excludedSources = useMemo(
    () =>
      config.excludeSources
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
    [config.excludeSources],
  )

  function applyClientFilters(entries: LogEntryResponse[]) {
    const q = query.trim().toLowerCase()
    return entries.filter((e) => {
      const lv = normaliseLevel(e.level ?? 'INFO')
      if (!levels[lv]) return false
      const eenv = extractEnv(e)
      if (eenv && envs.length > 0 && !envs.includes(eenv)) return false
      const src = extractSource(e)
      if (excludedSources.some((s) => src.includes(s))) return false
      if (
        q &&
        !e.message.toLowerCase().includes(q) &&
        !src.toLowerCase().includes(q)
      )
        return false
      return true
    })
  }

  const filteredEntries = useMemo(
    () => applyClientFilters(allEntries),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [allEntries, query, levels, envs, excludedSources],
  )

  // Reset scroll and height cache whenever the query changes
  useEffect(() => {
    rowHeightCache.current.clear()
    setHeightVersion(0)
    setListScrollTop(0)
    if (listRef.current) listRef.current.scrollTop = 0
  }, [activeSource, range, customStartIso, customEndIso, apiFilters, envs])

  const endMs = new Date(datetimes.end).getTime()

  // Dedicated histogram query — single API call returning pre-aggregated
  // bucket counts. Independent of the table pagination state so scrolling
  // never causes the histogram to flicker or reset.
  const { data: histData } = useQuery({
    enabled:
      config.showHistogram &&
      !!activeSource &&
      Boolean(activeAssignment?.supports_histogram),
    queryFn: ({ signal }) =>
      getProjectLogsHistogram(
        orgSlug,
        projectId,
        {
          bucket_count: 60,
          end_time: datetimes.end,
          environment: envs.length > 0 ? envs : undefined,
          filter: apiFilters,
          source: activeSource,
          start_time: datetimes.start,
        },
        signal,
      ),
    queryKey: [
      'project-logs-histogram',
      orgSlug,
      projectId,
      activeSource,
      datetimes.start,
      datetimes.end,
      apiFilters,
      envs,
    ],
    staleTime: 60_000,
  })

  const buckets = useMemo(
    () =>
      (histData ?? []).map((b) => {
        const totals: Record<'DEBUG' | 'ERROR' | 'INFO' | 'WARN', number> = {
          DEBUG: 0,
          ERROR: 0,
          INFO: 0,
          WARN: 0,
        }
        for (const [raw, cnt] of Object.entries(b.levels)) {
          totals[normaliseLevel(raw)] += cnt
        }
        return { count: b.count, t: new Date(b.timestamp).getTime(), ...totals }
      }),
    [histData],
  )

  const displayEntries = useMemo(() => {
    if (selectedBucket === null || !buckets[selectedBucket])
      return filteredEntries
    const bStart = buckets[selectedBucket].t
    const bEnd = buckets[selectedBucket + 1]?.t ?? endMs
    return filteredEntries.filter((e) => {
      const ts = new Date(e.timestamp).getTime()
      return ts >= bStart && ts < bEnd
    })
  }, [filteredEntries, selectedBucket, buckets, endMs])

  const toggleRow = useCallback((id: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }, [])

  // Cumulative offset table — rebuilt when entries change or measured heights update
  const { offsets, totalH } = useMemo(() => {
    const list: Array<{ h: number; top: number }> = []
    let top = 0
    for (let i = 0; i < displayEntries.length; i++) {
      const id = `${displayEntries[i].timestamp}-${i}`
      const h = rowHeightCache.current.get(id) ?? ROW_H_COLLAPSED
      list.push({ h, top })
      top += h
    }
    return { offsets: list, totalH: top }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [displayEntries, heightVersion])

  // Binary search for visible window
  const { visEnd, visStart } = useMemo(() => {
    if (!offsets.length) return { visEnd: 0, visStart: 0 }
    const viewTop = listScrollTop
    const viewBot = listScrollTop + containerH

    // Lower bound: first row whose bottom edge is below viewTop
    let hi = offsets.length,
      lo = 0
    while (lo < hi) {
      const mid = (lo + hi) >> 1
      if (offsets[mid].top + offsets[mid].h <= viewTop) lo = mid + 1
      else hi = mid
    }
    const first = lo

    // Upper bound: one past the last row whose top is above viewBot
    hi = offsets.length
    lo = 0
    while (lo < hi) {
      const mid = (lo + hi) >> 1
      if (offsets[mid].top < viewBot) lo = mid + 1
      else hi = mid
    }

    return {
      visEnd: Math.min(offsets.length, lo + VIRTUAL_OVERSCAN),
      visStart: Math.max(0, first - VIRTUAL_OVERSCAN),
    }
  }, [offsets, listScrollTop, containerH])

  const topPad = offsets[visStart]?.top ?? 0
  const botPad = Math.max(
    0,
    totalH -
      (offsets[visEnd - 1]
        ? offsets[visEnd - 1].top + offsets[visEnd - 1].h
        : 0),
  )

  const handleRowHeight = useCallback((id: string, h: number) => {
    if (rowHeightCache.current.get(id) !== h) {
      rowHeightCache.current.set(id, h)
      setHeightVersion((v) => v + 1)
    }
  }, [])

  // Auto-load next page when the scroll sentinel enters the viewport
  useEffect(() => {
    const el = loadTriggerRef.current
    if (!el || !logResult?.next_cursor) return
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !isFetching) handleLoadMore()
      },
      { root: listRef.current, rootMargin: '200px' },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [logResult?.next_cursor, isFetching, handleLoadMore])

  if (sources.length === 0 && assignments !== undefined) {
    return (
      <div className="bg-primary rounded-lg border px-6 py-12 text-center">
        <div className="text-primary mb-2 text-sm font-medium">
          No logs plugin configured
        </div>
        <p className="text-tertiary text-xs">
          Assign a logs plugin to this project type or in project settings.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {/* Source picker */}
      {sources.length > 1 && (
        <div className="flex items-center gap-2">
          <span className="text-tertiary text-xs">Source:</span>
          {sources.map((s) => (
            <button
              className={`rounded border px-2.5 py-1 text-xs transition-colors ${
                activeSource === s.id
                  ? 'border-action bg-amber-bg text-amber-text'
                  : 'border-secondary text-secondary hover:border-primary hover:text-primary'
              }`}
              key={s.id}
              onClick={() => setSource(s.id)}
            >
              {s.label}
            </button>
          ))}
        </div>
      )}

      {/* Query bar */}
      <div className="bg-tertiary flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2.5">
        {/* Search box */}
        <div className="bg-primary focus-within:border-action focus-within:ring-action/20 flex min-w-64 flex-1 items-center gap-2 rounded border px-2.5 py-1.5 focus-within:ring-1">
          <Search className="text-tertiary" size={13} />
          <input
            className="text-primary placeholder:text-tertiary flex-1 bg-transparent font-mono text-xs outline-none"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSearch()
            }}
            placeholder="Search · field:value, -exclude, quoted phrases"
            value={query}
          />
          {query && (
            <button
              className="text-tertiary hover:text-primary"
              onClick={() => setQuery('')}
            >
              <X size={11} />
            </button>
          )}
        </div>

        {/* Range presets */}
        <div className="bg-primary flex items-center gap-px rounded border p-0.5">
          {RANGES.map((r) => (
            <button
              className={`rounded px-2.5 py-1 font-mono text-xs transition-colors ${
                range === r.key && !customStart
                  ? 'bg-secondary text-primary border font-medium shadow-sm'
                  : 'text-secondary hover:text-primary'
              }`}
              key={r.key}
              onClick={() => {
                setRange(r.key)
                setCustomStart(undefined)
                setCustomEnd(undefined)
              }}
            >
              {r.label}
            </button>
          ))}
        </div>

        {/* Date picker */}
        <div className="relative">
          <button
            className={`bg-primary text-primary hover:border-primary flex items-center gap-1.5 rounded border px-2.5 py-1.5 font-mono text-xs transition-colors ${datePickerOpen ? 'ring-action/20 border-action ring-1' : ''}`}
            onClick={() => setDatePickerOpen(!datePickerOpen)}
          >
            <Calendar className="text-tertiary" size={12} />
            {customStart && customEnd
              ? fmtRangeLabel(
                  customStart.toISOString(),
                  customEnd.toISOString(),
                )
              : fmtRangeLabel(datetimes.start, datetimes.end)}
          </button>
          {datePickerOpen && (
            <div className="bg-primary absolute top-full left-0 z-30 mt-1 min-w-72 rounded-lg border p-3 shadow-lg">
              <div className="text-tertiary mb-2 text-[10px] font-semibold tracking-wide uppercase">
                Custom range
              </div>
              <div className="mb-3 flex gap-2">
                <input
                  className="bg-tertiary text-primary focus:border-action flex-1 rounded border px-2 py-1 font-mono text-xs outline-none"
                  onChange={(e) => setStartInput(e.target.value)}
                  type="datetime-local"
                  value={startInput}
                />
                <input
                  className="bg-tertiary text-primary focus:border-action flex-1 rounded border px-2 py-1 font-mono text-xs outline-none"
                  onChange={(e) => setEndInput(e.target.value)}
                  type="datetime-local"
                  value={endInput}
                />
              </div>
              <div className="flex justify-end gap-2 border-t pt-2">
                <button
                  className="text-tertiary hover:text-secondary text-xs"
                  onClick={() => setDatePickerOpen(false)}
                >
                  Cancel
                </button>
                <button
                  className="bg-action text-action-foreground rounded px-2.5 py-1 text-xs font-medium"
                  onClick={() => {
                    if (startInput && endInput) {
                      setCustomStart(new Date(startInput))
                      setCustomEnd(new Date(endInput))
                    }
                    setDatePickerOpen(false)
                  }}
                >
                  Apply
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Visual gap between date and env groups */}
        <div aria-hidden className="bg-tertiary ml-3 h-5 w-px opacity-50" />

        {/* Env toggles — same pattern as the level toggles below, ordered
            by sort_order and colored from each Environment's label_color. */}
        <div className="flex items-center gap-1">
          {envOptions.map((opt) => {
            const active = envs.includes(opt.slug)
            const c = opt.color
            const activeStyle: React.CSSProperties | undefined =
              active && c
                ? {
                    backgroundColor: c.bg,
                    borderColor: c.border,
                    color: c.fg,
                  }
                : undefined
            return (
              <button
                className={`rounded border px-2 py-1 font-mono text-[10px] transition-colors ${
                  active && !c
                    ? 'border-secondary bg-secondary text-primary'
                    : !active
                      ? 'border-tertiary text-tertiary opacity-50'
                      : ''
                }`}
                key={opt.slug}
                onClick={() =>
                  setEnvs(
                    envs.includes(opt.slug)
                      ? envs.filter((x) => x !== opt.slug)
                      : [...envs, opt.slug],
                  )
                }
                style={activeStyle}
                type="button"
              >
                {opt.name}
              </button>
            )
          })}
        </div>

        {/* Visual gap between env and severity groups */}
        <div aria-hidden className="bg-tertiary ml-3 h-5 w-px opacity-50" />

        {/* Level toggles */}
        <div className="flex items-center gap-1">
          {['ERROR', 'WARN', 'INFO', 'DEBUG'].map((lv) => (
            <button
              className={`rounded border px-2 py-1 font-mono text-[10px] transition-colors ${
                levels[lv]
                  ? lv === 'ERROR'
                    ? 'border-danger bg-danger text-danger'
                    : lv === 'WARN'
                      ? 'border-warning bg-warning text-warning'
                      : lv === 'INFO'
                        ? 'border-info bg-info text-info'
                        : 'border-secondary bg-secondary text-tertiary'
                  : 'border-tertiary text-tertiary opacity-50'
              }`}
              key={lv}
              onClick={() => setLevels({ ...levels, [lv]: !levels[lv] })}
            >
              {lv}
            </button>
          ))}
        </div>

        {/* Visual gap between level toggles and the action icons */}
        <div aria-hidden className="bg-tertiary ml-3 h-5 w-px opacity-50" />

        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                className="bg-primary text-secondary hover:border-primary hover:text-primary flex items-center gap-1.5 rounded border px-2.5 py-1.5 text-xs"
                disabled={isFetching}
                onClick={() => void refetch()}
              >
                <RefreshCw
                  className={isFetching ? 'animate-spin' : ''}
                  size={12}
                />
              </button>
            </TooltipTrigger>
            <TooltipContent>Refresh</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                className="bg-primary text-secondary hover:border-primary hover:text-primary rounded border p-1.5"
                onClick={() => {
                  void navigator.clipboard
                    .writeText(window.location.href)
                    .then(() => {
                      toast.success('Link copied to clipboard')
                    })
                }}
              >
                <Share2 size={12} />
              </button>
            </TooltipTrigger>
            <TooltipContent>Copy link</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <button className="bg-primary text-secondary hover:border-primary hover:text-primary rounded border p-1.5">
                <Download size={12} />
              </button>
            </TooltipTrigger>
            <TooltipContent>Export</TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>

      {/* Active field filters */}
      {fieldFilters.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {fieldFilters.map((f, i) => (
            <span
              className="bg-tertiary text-secondary flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[11px]"
              key={i}
            >
              {f}
              <button
                className="text-tertiary hover:text-primary"
                onClick={() =>
                  setFieldFilters((prev) => prev.filter((_, j) => j !== i))
                }
              >
                <X size={10} />
              </button>
            </span>
          ))}
          <button
            className="text-tertiary hover:text-secondary text-[11px]"
            onClick={() => setFieldFilters([])}
          >
            Clear all
          </button>
        </div>
      )}

      {/* Histogram — only render when the active log plugin advertises
          time-bucket aggregation. CloudWatch Logs Insights, for example,
          can do it via `stats count(*) by bin(...)` but the AWS plugin
          doesn't yet implement it, so we hide the strip rather than
          showing an empty chart. */}
      {config.showHistogram && activeAssignment?.supports_histogram && (
        <Histogram
          buckets={buckets}
          levels={levels}
          onBucketSelect={setSelectedBucket}
          selectedBucket={selectedBucket}
          total={logResult?.total ?? buckets.reduce((s, b) => s + b.count, 0)}
        />
      )}

      {/* Log table */}
      <div className="bg-primary overflow-hidden rounded-lg border">
        <div
          className="bg-secondary text-tertiary grid gap-2.5 border-b px-3 py-2 font-mono text-[11px] tracking-widest uppercase"
          style={{ gridTemplateColumns: '16px 164px 96px 58px minmax(0,1fr)' }}
        >
          <div />
          <div>Time (UTC)</div>
          <div className="text-center">Environment</div>
          <div className="text-center">Level</div>
          <div>Message</div>
        </div>

        <div
          className="overflow-y-auto"
          onScroll={(e) => setListScrollTop(e.currentTarget.scrollTop)}
          ref={listRef}
          style={{
            height:
              config.showHistogram && activeAssignment?.supports_histogram
                ? 'calc(100dvh - 680px)'
                : 'calc(100dvh - 500px)',
            minHeight: '320px',
          }}
        >
          {isFetching && failureCount > 0 && displayEntries.length === 0 ? (
            <div className="py-10 text-center">
              <LoadingState
                label={`Retrying… (attempt ${failureCount + 1} of 4)`}
              />
            </div>
          ) : isFetching && displayEntries.length === 0 ? (
            <LoadingState label="Loading logs…" />
          ) : logError && displayEntries.length === 0 ? (
            <div className="py-10 text-center">
              <div className="text-danger mb-1 text-sm font-medium">
                Failed to load logs
              </div>
              <div className="text-tertiary mb-4 font-mono text-xs">
                {logError instanceof Error
                  ? logError.message
                  : 'An unexpected error occurred'}
              </div>
              <button
                className="text-secondary hover:border-primary hover:text-primary rounded border px-3 py-1.5 text-xs"
                onClick={() => void refetch()}
              >
                Try again
              </button>
            </div>
          ) : displayEntries.length === 0 ? (
            <div className="py-10 text-center">
              <div className="text-secondary mb-1 text-sm font-medium">
                No matching log entries
              </div>
              <div className="text-tertiary text-xs">
                Try widening the time range or removing filters.
              </div>
            </div>
          ) : (
            <>
              <div style={{ height: topPad }} />
              {displayEntries.slice(visStart, visEnd).map((entry, ii) => {
                const i = visStart + ii
                const rowId = `${entry.timestamp}-${i}`
                return (
                  <LogRow
                    entry={entry}
                    envChipColors={envChipColors}
                    envNames={envSlugToName}
                    expanded={expandedRows.has(rowId)}
                    key={rowId}
                    onAddFilter={handleAddFilter}
                    onHeightChange={(h) => handleRowHeight(rowId, h)}
                    onToggle={() => toggleRow(rowId)}
                    query={query}
                    wrap={config.wrap}
                  />
                )
              })}
              <div style={{ height: botPad }} />
              {logResult?.next_cursor && (
                <div className="py-3 text-center" ref={loadTriggerRef}>
                  {isFetching && <LoadingState label="Loading more…" />}
                </div>
              )}
            </>
          )}
        </div>

        <div className="bg-secondary text-tertiary flex items-center justify-between border-t px-3 py-2 font-mono text-[11px]">
          <span>
            {filteredEntries.length.toLocaleString()} entries
            {logResult?.total != null &&
              ` · ${logResult.total.toLocaleString()} total`}
          </span>
          {isFetching && <span className="text-tertiary">Loading…</span>}
        </div>
      </div>
    </div>
  )
}

// ── Internal helpers & components ──────────────────────────────────────────

function extractEnv(entry: LogEntryResponse): string {
  const r = entry.raw
  return (r?.environment ?? r?.env ?? '') as string
}

function extractException(entry: LogEntryResponse): ExceptionInfo | null {
  const r = entry.raw
  if (r?.exception && typeof r.exception === 'object') {
    const e = r.exception as Record<string, unknown>
    return {
      message: (e.message ?? e.msg ?? '') as string,
      stack: Array.isArray(e.stack) ? (e.stack as string[]) : [],
      type: (e.type ?? e.class ?? 'Exception') as string,
    }
  }
  if (typeof r?.stack_trace === 'string') {
    return {
      message: entry.message,
      stack: (r.stack_trace as string).split('\n').filter(Boolean),
      type: 'Exception',
    }
  }
  return null
}

function extractSource(entry: LogEntryResponse): string {
  const r = entry.raw
  return (r?.source ?? r?.logger ?? r?.module ?? r?.service ?? '') as string
}

function fmtBucketInterval(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`
  const minutes = seconds / 60
  if (minutes < 60) return `${Math.round(minutes)}m`
  return `${Math.round(minutes / 60)}h`
}

function fmtRangeLabel(start: string, end: string): string {
  const s = new Date(start)
  const e = new Date(end)
  const fmt = (d: Date) =>
    `${d.toUTCString().slice(5, 11)} ${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`
  return `${fmt(s)} → ${fmt(e)} UTC`
}

function fmtTimestamp(ts: string) {
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return {
    date: d.toUTCString().slice(5, 11),
    hms: `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`,
    ms: String(d.getUTCMilliseconds()).padStart(3, '0'),
  }
}

function HighlightedText({ query, text }: { query: string; text: string }) {
  if (!query.trim()) return <>{text}</>
  const term = query
    .trim()
    .split(/\s+/)
    .find((t) => !t.includes(':') && t.length >= 2)
  if (!term) return <>{text}</>
  const parts: (ReactNode | string)[] = []
  let i = 0
  const lc = text.toLowerCase()
  const lt = term.toLowerCase()
  while (i < text.length) {
    const idx = lc.indexOf(lt, i)
    if (idx < 0) {
      parts.push(text.slice(i))
      break
    }
    if (idx > i) parts.push(text.slice(i, idx))
    parts.push(
      <mark className="bg-warning text-primary rounded-sm px-px" key={idx}>
        {text.slice(idx, idx + term.length)}
      </mark>,
    )
    i = idx + term.length
  }
  return <>{parts}</>
}

function Histogram({
  buckets,
  levels,
  onBucketSelect,
  selectedBucket,
  total,
}: {
  buckets: HistogramBucket[]
  levels: Record<string, boolean>
  onBucketSelect: (i: null | number) => void
  selectedBucket: null | number
  total: null | number
}) {
  const BAR_H = 60
  const n = buckets.length
  // ``activeSum`` is the height-driving total for each bucket. Prefer the
  // sum of the level toggles the user has on; fall back to ``b.count``
  // when this bucket has no per-level breakdown (e.g. Postgres logs in
  // CloudWatch have no structured ``level`` field, so the per-level
  // Insights query returns nothing — but the totals query still
  // populates ``b.count``). The fallback is evaluated per bucket so a
  // mixed response (some buckets with level data, others count-only)
  // still renders every bar at the right height.
  const activeSum = (b: HistogramBucket) =>
    (['ERROR', 'WARN', 'INFO', 'DEBUG'] as const).some((lv) => b[lv] > 0)
      ? (['ERROR', 'WARN', 'INFO', 'DEBUG'] as const).reduce(
          (s, lv) => s + (levels[lv] ? b[lv] : 0),
          0,
        )
      : b.count
  const max = Math.max(1, ...buckets.map(activeSum))

  // 5 evenly-spaced axis ticks that work for any bucket count
  const axisIndices =
    n <= 1
      ? [0]
      : [
          0,
          Math.round(n * 0.25),
          Math.round(n * 0.5),
          Math.round(n * 0.75),
          n - 1,
        ]

  // Show date prefix on labels when the range spans more than one calendar day
  const firstMs = buckets[0]?.t ?? 0
  const lastMs = buckets[n - 1]?.t ?? 0
  const spansMultipleDays =
    n > 1 &&
    new Date(firstMs).toUTCString().slice(0, 16) !==
      new Date(lastMs).toUTCString().slice(0, 16)

  const fmtAxisLabel = (ms: number): string => {
    const d = new Date(ms)
    const hhmm = `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`
    if (spansMultipleDays) {
      // e.g. "28 Apr\n00:26"
      return `${d.toUTCString().slice(5, 11)}\n${hhmm}`
    }
    return hhmm
  }

  const intervalSec =
    n > 1 && buckets[1]?.t != null && buckets[0]?.t != null
      ? (buckets[1].t - buckets[0].t) / 1000
      : 0

  return (
    <div className="bg-tertiary rounded-md border p-3">
      <div className="mb-2 flex items-baseline justify-between">
        <div className="flex items-baseline gap-2">
          <span className="text-primary font-mono text-sm font-medium">
            {(total ?? 0).toLocaleString()}
          </span>
          <span className="text-tertiary text-xs">events</span>
        </div>
        <div className="text-tertiary font-mono text-xs">
          {intervalSec > 0 ? `events / ${fmtBucketInterval(intervalSec)}` : ''}
        </div>
      </div>
      {/* Bars: each column is an absolutely-sized div so heights render correctly */}
      <div
        style={{
          alignItems: 'flex-end',
          display: 'flex',
          gap: '1px',
          height: `${BAR_H + 4}px`,
        }}
      >
        {buckets.map((b, i) => {
          const sum = activeSum(b)
          const colH =
            sum > 0 ? Math.max(2, Math.round((sum / max) * BAR_H)) : 2
          const hasLevelData = (
            ['ERROR', 'WARN', 'INFO', 'DEBUG'] as const
          ).some((lv) => levels[lv] && b[lv] > 0)
          return (
            <div
              key={i}
              onClick={() => onBucketSelect(selectedBucket === i ? null : i)}
              style={{
                cursor: 'crosshair',
                display: 'flex',
                flex: '1 1 0%',
                flexDirection: 'column-reverse',
                height: `${colH}px`,
                opacity:
                  selectedBucket !== null && selectedBucket !== i ? 0.4 : 1,
                transition: 'opacity 150ms',
              }}
              title={`${new Date(b.t).toUTCString().slice(5, 22)} · ${b.count.toLocaleString()} events`}
            >
              {sum === 0 ? (
                <div
                  style={{
                    background: 'var(--background-color-secondary)',
                    flex: 1,
                  }}
                />
              ) : !hasLevelData ? (
                <div style={{ background: SEV_BAR_COLORS['INFO'], flex: 1 }} />
              ) : (
                (['ERROR', 'WARN', 'INFO', 'DEBUG'] as const).map((lv) => {
                  if (!levels[lv] || !b[lv] || !sum) return null
                  const segH = Math.max(1, Math.round((b[lv] / sum) * colH))
                  return (
                    <div
                      key={lv}
                      style={{
                        background: SEV_BAR_COLORS[lv],
                        flexShrink: 0,
                        height: `${segH}px`,
                        width: '100%',
                      }}
                    />
                  )
                })
              )}
            </div>
          )
        })}
      </div>
      <div
        className="relative mt-1 border-t pt-1"
        style={{ height: spansMultipleDays ? '28px' : '16px' }}
      >
        {axisIndices.map((idx, pos) => {
          const ms = buckets[idx]?.t ?? 0
          const pct = n <= 1 ? 0 : (idx / (n - 1)) * 100
          const label = fmtAxisLabel(ms)
          return (
            <span
              className={`text-tertiary absolute top-1 font-mono text-[10px] leading-tight ${
                pos === 0
                  ? '-translate-x-0'
                  : pos === axisIndices.length - 1
                    ? '-translate-x-full'
                    : '-translate-x-1/2'
              }`}
              key={idx}
              style={{ left: `${pct}%`, whiteSpace: 'pre' }}
            >
              {label}
            </span>
          )
        })}
      </div>
    </div>
  )
}

function JsonPretty({ value }: { value: unknown }) {
  const json = JSON.stringify(value, null, 2)
  const tokens: (ReactNode | string)[] = []
  const re =
    /("(?:\\.|[^"\\])*")(\s*:)?|(\b(?:true|false|null)\b)|(-?\d+\.?\d*)/g
  let last = 0
  let idx = 0
  let m: null | RegExpExecArray
  while ((m = re.exec(json)) !== null) {
    if (m.index > last) tokens.push(json.slice(last, m.index))
    if (m[1] && m[2]) {
      tokens.push(
        <span className="text-accent" key={idx++}>
          {m[1]}
        </span>,
      )
      tokens.push(m[2])
    } else if (m[1]) {
      tokens.push(
        <span className="text-success" key={idx++}>
          {m[1]}
        </span>,
      )
    } else if (m[3]) {
      tokens.push(
        <span className="text-warning" key={idx++}>
          {m[3]}
        </span>,
      )
    } else if (m[4]) {
      tokens.push(
        <span className="text-info" key={idx++}>
          {m[4]}
        </span>,
      )
    }
    last = re.lastIndex
  }
  if (last < json.length) tokens.push(json.slice(last))
  return (
    <pre className="bg-secondary text-primary overflow-x-auto rounded p-3 font-mono text-xs leading-relaxed">
      {tokens}
    </pre>
  )
}

function LogRow({
  entry,
  envChipColors,
  envNames,
  expanded,
  onAddFilter,
  onHeightChange,
  onToggle,
  query,
  wrap,
}: {
  entry: LogEntryResponse
  envChipColors: Record<string, ReturnType<typeof deriveChipColors>>
  envNames: Record<string, string>
  expanded: boolean
  onAddFilter: (field: string, value: string) => void
  onHeightChange?: (h: number) => void
  onToggle: () => void
  query: string
  wrap: boolean
}) {
  const rowRef = useRef<HTMLDivElement>(null)
  const [detailTab, setDetailTab] = useState<DetailTab>('table')
  const t = fmtTimestamp(entry.timestamp)
  const source = extractSource(entry)
  const exception = extractException(entry)

  useLayoutEffect(() => {
    if (rowRef.current && onHeightChange) {
      onHeightChange(rowRef.current.offsetHeight)
    }
  }, [expanded, onHeightChange])

  const rawFields = useMemo(() => {
    const reserved = new Set([
      '@timestamp',
      'env',
      'environment',
      'exception',
      'level',
      'logger',
      'message',
      'module',
      'msg',
      'service',
      'source',
      'stack_trace',
      'timestamp',
    ])
    return Object.entries(entry.raw ?? {}).filter(([k]) => !reserved.has(k))
  }, [entry.raw])

  return (
    <div
      className={`border-tertiary border-b last:border-0 ${expanded ? 'bg-secondary' : 'hover:bg-tertiary'} cursor-pointer`}
      onClick={onToggle}
      ref={rowRef}
    >
      <div
        className="grid items-start gap-2.5 px-3 py-2"
        style={{ gridTemplateColumns: '16px 164px 96px 58px minmax(0,1fr)' }}
      >
        <ChevronRight
          className={`text-tertiary mt-0.5 transition-transform duration-100 ${expanded ? 'text-primary rotate-90' : ''}`}
          size={12}
        />
        <div className="text-secondary font-mono text-xs tabular-nums">
          {t.date} {t.hms}
          <span className="text-tertiary">.{t.ms}</span>
        </div>
        <div className="flex min-w-0 justify-center">
          {(() => {
            const slug = extractEnv(entry)
            if (!slug) return null
            const c = envChipColors[slug]
            return (
              <span
                className="inline-flex h-5 max-w-full items-center overflow-hidden rounded px-1.5 font-mono text-[10px] font-medium text-ellipsis whitespace-nowrap"
                style={
                  c
                    ? {
                        backgroundColor: c.bg,
                        color: c.fg,
                      }
                    : undefined
                }
                title={envNames[slug] ?? slug}
              >
                {envNames[slug] ?? slug}
              </span>
            )
          })()}
        </div>
        <div className="flex justify-center">
          <SevBadge level={entry.level} />
        </div>
        <div
          className={`text-primary min-w-0 font-mono text-xs ${wrap ? 'break-all' : 'overflow-hidden text-ellipsis whitespace-nowrap'}`}
        >
          {source && <span className="text-tertiary mr-2">{source}</span>}
          <HighlightedText query={query} text={entry.message} />
        </div>
      </div>

      {expanded && (
        <div
          className="border-tertiary bg-primary border-t px-3 pt-2 pb-3"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="border-tertiary mb-3 flex items-center border-b">
            {(
              [
                { id: 'table', label: 'Table' },
                { id: 'json', label: 'JSON' },
                ...(exception ? [{ id: 'stack', label: 'Stack trace' }] : []),
              ] as { id: DetailTab; label: string }[]
            ).map((tab) => (
              <button
                className={`border-0 bg-transparent pt-1 pr-4 pb-2 text-xs ${
                  detailTab === tab.id
                    ? 'text-primary font-medium'
                    : 'text-tertiary hover:text-secondary'
                }`}
                key={tab.id}
                onClick={() => setDetailTab(tab.id)}
                style={
                  detailTab === tab.id
                    ? {
                        borderBottom:
                          '2px solid var(--background-color-action)',
                        marginBottom: '-1px',
                      }
                    : {}
                }
              >
                {tab.label}
              </button>
            ))}
            <div className="flex-1" />
            <button
              className="text-tertiary hover:text-secondary flex items-center gap-1 pt-1 pb-2 text-xs"
              onClick={() =>
                navigator.clipboard.writeText(
                  `${entry.timestamp} ${source} ${entry.message}`,
                )
              }
            >
              <Copy size={10} /> Copy
            </button>
          </div>

          {detailTab === 'table' && (
            <div
              className="grid gap-y-0.5"
              style={{ gridTemplateColumns: 'max-content 1fr' }}
            >
              {[
                ['@timestamp', new Date(entry.timestamp).toISOString()],
                ['level', entry.level ?? ''],
                ...(source ? [['source', source]] : []),
                ...(extractEnv(entry)
                  ? [['environment', extractEnv(entry)]]
                  : []),
                ...rawFields.map(([k, v]) => [
                  k,
                  typeof v === 'object' ? JSON.stringify(v) : String(v ?? ''),
                ]),
              ].map(([k, v], rowIdx) => (
                <Fragment key={`row-${rowIdx}`}>
                  <div
                    className="text-tertiary pr-4 font-mono text-[11px]"
                    style={{ paddingBottom: '3px', paddingTop: '3px' }}
                  >
                    {k}
                  </div>
                  <div
                    className="group text-primary flex min-w-0 items-center gap-1.5 font-mono text-[11px]"
                    style={{ paddingBottom: '3px', paddingTop: '3px' }}
                  >
                    <span className="min-w-0 break-all">{v}</span>
                    <span className="flex gap-0.5 opacity-0 group-hover:opacity-100">
                      <button
                        className="border-secondary text-secondary hover:border-action hover:text-primary rounded border px-1 py-px font-mono text-[10px]"
                        onClick={() => onAddFilter(k as string, v as string)}
                        title="Filter for value"
                      >
                        +
                      </button>
                      <button
                        className="border-secondary text-secondary hover:border-danger hover:text-danger rounded border px-1 py-px font-mono text-[10px]"
                        onClick={() =>
                          onAddFilter(`-${k as string}`, v as string)
                        }
                        title="Filter out value"
                      >
                        −
                      </button>
                      <button
                        className="border-secondary text-secondary hover:text-primary rounded border px-1 py-px font-mono text-[10px]"
                        onClick={() =>
                          navigator.clipboard.writeText(v as string)
                        }
                        title="Copy value"
                      >
                        <Copy size={8} />
                      </button>
                    </span>
                  </div>
                </Fragment>
              ))}
            </div>
          )}

          {detailTab === 'json' && (
            <JsonPretty
              value={{
                '@timestamp': new Date(entry.timestamp).toISOString(),
                environment: extractEnv(entry) || undefined,
                level: entry.level,
                message: entry.message,
                source: source || undefined,
                ...Object.fromEntries(rawFields),
              }}
            />
          )}

          {detailTab === 'stack' && exception && (
            <div className="bg-secondary rounded p-3 font-mono text-xs leading-relaxed">
              <div className="text-danger mb-2 font-semibold">
                {exception.type}: {exception.message}
              </div>
              {exception.stack.map((line, lineIdx) => (
                <div
                  className={
                    lineIdx % 2 === 0 ? 'text-secondary' : 'text-tertiary'
                  }
                  key={lineIdx}
                >
                  {line}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function rangeToDatetimes(
  rangeKey: RelativeRange,
  customStart?: Date,
  customEnd?: Date,
) {
  if (customStart && customEnd) {
    return {
      end: customEnd.toISOString(),
      start: customStart.toISOString(),
    }
  }
  const range = RANGES.find((r) => r.key === rangeKey)!
  const end = new Date()
  const start = new Date(end.getTime() - range.ms)
  return { end: end.toISOString(), start: start.toISOString() }
}

function SevBadge({ level }: { level: null | string }) {
  const lv = (level ?? 'INFO').toUpperCase()
  const cls =
    lv === 'ERROR' || lv === 'FATAL'
      ? 'bg-danger text-danger'
      : lv === 'WARN' || lv === 'WARNING'
        ? 'bg-warning text-warning'
        : lv === 'DEBUG'
          ? 'bg-secondary text-tertiary'
          : 'bg-info text-info'
  return (
    <span
      className={`inline-flex h-5 max-w-full items-center overflow-hidden rounded px-1.5 font-mono text-[10px] font-medium text-ellipsis whitespace-nowrap ${cls}`}
    >
      {lv === 'WARNING' ? 'WARN' : lv === 'FATAL' ? 'ERROR' : lv}
    </span>
  )
}
