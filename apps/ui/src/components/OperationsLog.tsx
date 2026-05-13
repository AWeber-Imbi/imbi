import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { useWindowVirtualizer } from '@tanstack/react-virtual'
import { Activity, LoaderCircle, SearchX, X } from 'lucide-react'

import { getProjects, listAdminUsers, listEnvironments } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { LoadingState } from '@/components/ui/loading-state'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useInfiniteOperationsLog } from '@/hooks/useInfiniteOperationsLog'
import { cn } from '@/lib/utils'
import type {
  Environment,
  OperationsLogEntryType,
  OperationsLogFilters,
  OperationsLogRecord,
  Project,
} from '@/types'

import {
  OperationsLogFeedItem,
  type VItem,
} from './operations-log/OperationsLogFeedItem'
import { OperationsLogSummary } from './operations-log/OperationsLogSummary'
import {
  OperationsLogToolbar,
  type ToolbarCounts,
} from './operations-log/OperationsLogToolbar'
import {
  bucketByDay,
  cleanName,
  type FeedItem,
  groupReleases,
  type OperationsLogView,
  type TimeRange,
  toMs,
} from './operations-log/opsLogHelpers'

// Memoised + WAAPI-driven so the spin animation has its own lifetime
// independent of React's render cycle and runs on the compositor thread.
// The CSS `animate-spin` class would be re-applied on every render and
// can visually stutter / appear to reverse when the main thread blocks;
// `element.animate(...)` is installed once on mount and never restarts.
const LoadingIndicator = memo(function LoadingIndicator({
  loading,
}: {
  loading: boolean
}) {
  const spinnerRef = useRef<null | SVGSVGElement>(null)
  useEffect(() => {
    const el = spinnerRef.current
    if (!el || typeof el.animate !== 'function') return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const animation = el.animate(
      [{ transform: 'rotate(0deg)' }, { transform: 'rotate(360deg)' }],
      { duration: 1200, easing: 'linear', iterations: Infinity },
    )
    return () => animation.cancel()
  }, [])
  return (
    <span
      aria-label={loading ? 'Loading' : undefined}
      className="relative inline-block size-5"
      style={{
        contain: 'layout paint',
        transform: 'translateZ(0)',
        willChange: 'transform',
      }}
    >
      <Activity
        aria-hidden
        className={cn(
          'absolute inset-0 size-5 text-secondary transition-opacity duration-200',
          loading && 'opacity-0',
        )}
      />
      <LoaderCircle
        aria-hidden
        className={cn(
          'absolute inset-0 size-5 text-secondary transition-opacity duration-200',
          !loading && 'opacity-0',
        )}
        ref={spinnerRef}
        style={{
          backfaceVisibility: 'hidden',
          transformOrigin: 'center',
          willChange: 'transform',
        }}
      />
    </span>
  )
})

const RANGE_DELTA: Record<Exclude<TimeRange, 'all'>, number> = {
  '7d': 7 * 24 * 60 * 60 * 1000,
  '24h': 24 * 60 * 60 * 1000,
  '30d': 30 * 24 * 60 * 60 * 1000,
  '90d': 90 * 24 * 60 * 60 * 1000,
}

const RANGE_LABEL: Record<TimeRange, string> = {
  '7d': 'last 7 days',
  '24h': 'last 24h',
  '30d': 'last 30 days',
  '90d': 'last 90 days',
  all: 'all time',
}

interface ScreenFilters {
  entry_types: OperationsLogEntryType[]
  environment_slugs: string[]
  performed_by?: string
  project_slugs: string[]
  q?: string
  range: TimeRange
}

function rangeToSince(range: TimeRange): string | undefined {
  if (range === 'all') return undefined
  return new Date(Date.now() - RANGE_DELTA[range]).toISOString()
}

const DEFAULT_FILTERS: ScreenFilters = {
  entry_types: [],
  environment_slugs: [],
  project_slugs: [],
  range: '30d',
}

export interface OperationsLogProps {
  embedded?: boolean
  projectSlug?: string
  showHeader?: boolean
  showSummary?: boolean
}

export function OperationsLog({
  embedded = false,
  projectSlug,
  showHeader = true,
  showSummary = true,
}: OperationsLogProps = {}) {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug || ''

  const [filters, setFilters] = useState<ScreenFilters>(() =>
    projectSlug ? { ...DEFAULT_FILTERS, range: 'all' } : DEFAULT_FILTERS,
  )
  useEffect(() => {
    if (!projectSlug) return
    setFilters((prev) => ({
      ...prev,
      project_slugs: [],
      range: 'all',
    }))
  }, [projectSlug])
  const [view, setView] = useState<OperationsLogView>('grouped')
  const [openId, setOpenId] = useState<string | undefined>(undefined)
  // Stable dispatcher — lets memoised row components compare props by
  // reference without creating a new closure per row per render.
  const toggleOpen = useCallback((id: string) => {
    setOpenId((prev) => (prev === id ? undefined : id))
  }, [])

  const {
    data: projects = [],
    isError: projectsError,
    refetch: refetchProjects,
  } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => getProjects(orgSlug, signal),
    queryKey: ['projects', orgSlug],
  })
  const {
    data: environments = [],
    isError: environmentsError,
    refetch: refetchEnvironments,
  } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listEnvironments(orgSlug, signal),
    queryKey: ['environments', orgSlug],
  })
  const {
    data: users = [],
    isError: usersError,
    refetch: refetchUsers,
  } = useQuery({
    queryFn: ({ signal }) => listAdminUsers({ is_active: true }, signal),
    queryKey: ['admin-users', 'active'],
  })
  // Metadata queries back the filter dropdowns and the slug→name
  // lookups. When any of them fail we surface a non-blocking banner so
  // the user can retry rather than silently falling back to raw slugs.
  const metadataError = projectsError || environmentsError || usersError
  const retryMetadata = () => {
    if (projectsError) refetchProjects()
    if (environmentsError) refetchEnvironments()
    if (usersError) refetchUsers()
  }

  // Only the time-range boundary is pushed to the server. Facet filters
  // (entry_types / environment_slugs / project_slugs) are applied
  // client-side in `visibleEntries` so the toolbar dropdowns always
  // show the full set of options for the selected range — applying a
  // filter does not shrink the choices in the other dropdowns.
  const apiFilters: OperationsLogFilters = useMemo(
    () => ({
      performed_by: filters.performed_by,
      project_slug: projectSlug,
      since: rangeToSince(filters.range),
    }),
    [filters.performed_by, filters.range, projectSlug],
  )

  const {
    data,
    fetchNextPage,
    hasNextPage,
    isError,
    isFetchingNextPage,
    isLoading,
    refetch,
  } = useInfiniteOperationsLog(orgSlug, apiFilters)

  const rawEntries: OperationsLogRecord[] = useMemo(
    () => data?.entries ?? [],
    [data],
  )
  const serverMetrics = data?.metrics

  // Next-page fetch is driven by the virtualizer overscanning past the
  // end of the list, rather than eagerly paginating every page. See the
  // effect below the virtualizer setup.

  // Also enforce the `since` cutoff client-side. Defense in depth: if the
  // backend ever drifts, a stale cached page reappears, or the clock skews,
  // we still only ever display entries inside the selected window.
  const sinceCutoffMs = useMemo(() => {
    if (filters.range === 'all') return 0
    return Date.now() - RANGE_DELTA[filters.range]
  }, [filters.range])

  const visibleEntries = useMemo(() => {
    let xs = rawEntries
    if (sinceCutoffMs > 0) {
      xs = xs.filter((e) => toMs(e.occurred_at) >= sinceCutoffMs)
    }
    // Multi-select facets: treat each selected set as an OR within a
    // facet and AND across facets. An empty set means "no restriction".
    // Use Sets for O(1) membership; only allocate when we actually need
    // to filter on that facet.
    const typeSet =
      filters.entry_types.length > 0 ? new Set(filters.entry_types) : undefined
    const envSet =
      filters.environment_slugs.length > 0
        ? new Set(filters.environment_slugs)
        : undefined
    const projectSet =
      filters.project_slugs.length > 0
        ? new Set(filters.project_slugs)
        : undefined
    if (typeSet || envSet || projectSet) {
      xs = xs.filter((e) => {
        if (typeSet && !typeSet.has(e.entry_type)) return false
        if (envSet && !envSet.has(e.environment_slug)) return false
        if (projectSet && !projectSet.has(e.project_slug)) return false
        return true
      })
    }
    const q = filters.q?.toLowerCase().trim()
    if (q) {
      xs = xs.filter((e) => {
        // Avoid .join().includes() on every entry — it builds a throwaway
        // string per row. Short-circuit on first hit instead.
        if (e.project_slug.toLowerCase().includes(q)) return true
        if (e.description.toLowerCase().includes(q)) return true
        if (e.version && e.version.toLowerCase().includes(q)) return true
        if (e.ticket_slug && e.ticket_slug.toLowerCase().includes(q))
          return true
        if (e.notes && e.notes.toLowerCase().includes(q)) return true
        if (e.performed_by && e.performed_by.toLowerCase().includes(q))
          return true
        if (e.recorded_by.toLowerCase().includes(q)) return true
        return false
      })
    }
    return xs
  }, [
    rawEntries,
    sinceCutoffMs,
    filters.entry_types,
    filters.environment_slugs,
    filters.project_slugs,
    filters.q,
  ])

  const projectsBySlug = useMemo(
    () => new Map(projects.map((p: Project) => [p.slug, p])),
    [projects],
  )
  const environmentsBySlug = useMemo(
    () => new Map(environments.map((e: Environment) => [e.slug, e])),
    [environments],
  )
  const performerDisplayNames = useMemo(() => {
    const m = new Map<string, string>()
    for (const u of users) {
      if (u.email && u.display_name) m.set(u.email, u.display_name)
    }
    return m
  }, [users])

  // Toolbar counts — one pass over the date-filtered universe, built
  // independently of the search/env filters so the other facets show
  // the full set they're picking from.
  const counts: ToolbarCounts = useMemo(() => {
    const type: ToolbarCounts['type'] = {}
    const env: ToolbarCounts['env'] = {}
    const project: Record<string, number> = {}
    for (const e of rawEntries) {
      if (sinceCutoffMs > 0 && toMs(e.occurred_at) < sinceCutoffMs) continue
      type[e.entry_type] = (type[e.entry_type] ?? 0) + 1
      if (e.environment_slug) {
        env[e.environment_slug] = (env[e.environment_slug] ?? 0) + 1
      }
      project[e.project_slug] = (project[e.project_slug] ?? 0) + 1
    }
    return { env, project, type }
  }, [rawEntries, sinceCutoffMs])

  // Stable Map so the sidebar's project section doesn't see a new ref
  // on every parent render and the section's own memoised filter runs
  // on a stable input.
  const projectNames = useMemo(
    () =>
      new Map(
        Array.from(projectsBySlug.entries()).map(([k, v]) => [k, v.name]),
      ),
    [projectsBySlug],
  )

  const items: FeedItem[] = useMemo(() => {
    // Decorate-sort-undecorate: parse each timestamp exactly once rather
    // than twice per comparator call. Cuts parse count from 2·N·log N to
    // N — roughly 20× fewer parses at 5000 entries.
    const decorated = visibleEntries.map(
      (entry) => [toMs(entry.occurred_at), entry] as const,
    )
    decorated.sort((a, b) => b[0] - a[0])
    const sorted = decorated.map(([, entry]) => entry)
    if (view === 'grouped') return groupReleases(sorted)
    return sorted.map((entry) => ({ entry, kind: 'single' }) as FeedItem)
  }, [visibleEntries, view])

  const buckets = useMemo(() => bucketByDay(items), [items])

  // Flatten buckets into a single list for the virtualizer: one entry
  // per day header plus one entry per row. Each virtual item renders
  // independently so the only DOM nodes on screen at once are those in
  // (or near) the viewport, regardless of how many rows we have loaded.
  const virtualItems: VItem[] = useMemo(() => {
    const out: VItem[] = []
    for (const bucket of buckets) {
      out.push({
        count: bucket.items.length,
        date: bucket.date,
        key: `h-${bucket.key}`,
        kind: 'header',
        label: bucket.label,
      })
      for (const it of bucket.items) {
        if (it.kind === 'release') {
          const id = it.group.latestEntry.id
          const isOpen =
            openId === id || it.group.stops.some((s) => s.entry.id === openId)
          out.push({ id, isOpen, key: `rel-${id}`, kind: 'rel' })
        } else {
          const id = it.entry.id
          out.push({ id, isOpen: openId === id, key: `evt-${id}`, kind: 'evt' })
        }
      }
    }
    return out
  }, [buckets, openId])

  // Reverse index so the virtualizer's absolutely-positioned row can
  // look up its FeedItem payload by id without scanning `items` each render.
  const groupsById = useMemo(() => {
    const m = new Map<string, FeedItem>()
    for (const it of items) {
      const id = it.kind === 'release' ? it.group.latestEntry.id : it.entry.id
      m.set(id, it)
    }
    return m
  }, [items])

  const virtualizer = useWindowVirtualizer({
    count: virtualItems.length,
    estimateSize: (index) => (virtualItems[index]?.kind === 'header' ? 34 : 72),
    getItemKey: (index) => virtualItems[index]?.key ?? index,
    overscan: 8,
  })

  // Pull the next page as soon as the virtualizer renders within a few
  // rows of the end of the current list. Replaces the prior eager loop
  // that fetched every page back-to-back.
  const virtualRows = virtualizer.getVirtualItems()
  const lastVisibleIndex =
    virtualRows.length > 0 ? virtualRows[virtualRows.length - 1].index : -1
  useEffect(() => {
    if (!hasNextPage || isFetchingNextPage) return
    if (lastVisibleIndex < virtualItems.length - 5) return
    fetchNextPage()
  }, [
    lastVisibleIndex,
    virtualItems.length,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  ])

  const activeChips = useMemo(() => {
    const chips: { clear: () => void; key: string; label: string }[] = []
    for (const t of filters.entry_types) {
      chips.push({
        clear: () =>
          setFilters((f) => ({
            ...f,
            entry_types: f.entry_types.filter((x) => x !== t),
          })),
        key: `type-${t}`,
        label: t,
      })
    }
    for (const slug of filters.environment_slugs) {
      const env = environmentsBySlug.get(slug)
      chips.push({
        clear: () =>
          setFilters((f) => ({
            ...f,
            environment_slugs: f.environment_slugs.filter((x) => x !== slug),
          })),
        key: `env-${slug}`,
        label: env?.name ?? slug,
      })
    }
    for (const slug of filters.project_slugs) {
      chips.push({
        clear: () =>
          setFilters((f) => ({
            ...f,
            project_slugs: f.project_slugs.filter((x) => x !== slug),
          })),
        key: `project-${slug}`,
        label: projectsBySlug.get(slug)?.name ?? slug,
      })
    }
    if (filters.performed_by) {
      const pb = filters.performed_by
      chips.push({
        clear: () => setFilters((f) => ({ ...f, performed_by: undefined })),
        key: 'person',
        label: performerDisplayNames.get(pb) ?? cleanName(pb),
      })
    }
    return chips
  }, [
    filters.entry_types,
    filters.environment_slugs,
    filters.project_slugs,
    filters.performed_by,
    environmentsBySlug,
    projectsBySlug,
    performerDisplayNames,
  ])

  // With on-demand pagination, hasNextPage stays true until the user
  // scrolls to the end. Don't let that keep the spinner and inert
  // overlay on forever — just tie loading to active network activity.
  const isPageLoading = Boolean(isLoading || isFetchingNextPage)

  return (
    <div className={cn(embedded ? '' : 'mx-auto max-w-[1400px] px-6 py-6')}>
      <div className="grid items-start gap-7">
        <main className="min-w-0">
          {showHeader && (
            <header className="mb-4 flex flex-wrap items-end justify-between gap-3">
              <h1 className="text-h1 text-primary flex items-center gap-2">
                <LoadingIndicator loading={isPageLoading} />
                Operations Log
              </h1>
            </header>
          )}

          <div
            aria-busy={isPageLoading}
            className={cn(
              'transition-opacity duration-200',
              isPageLoading && 'cursor-wait opacity-50',
            )}
            inert={isPageLoading}
          >
            {showSummary && (
              <OperationsLogSummary
                entries={visibleEntries}
                environments={environments}
                loading={isPageLoading}
                range={filters.range}
                rangeLabel={RANGE_LABEL[filters.range]}
                serverMetrics={serverMetrics}
              />
            )}

            <OperationsLogToolbar
              counts={counts}
              entryTypes={filters.entry_types}
              environments={environments}
              environmentSlugs={filters.environment_slugs}
              hideProjectFilter={!!projectSlug}
              hideTimeRange={!!projectSlug}
              onEntryTypes={(entry_types) =>
                setFilters({ ...filters, entry_types })
              }
              onEnvironmentSlugs={(environment_slugs) =>
                setFilters({ ...filters, environment_slugs })
              }
              onProjectSlugs={(project_slugs) =>
                setFilters({ ...filters, project_slugs })
              }
              onRange={(range) => setFilters({ ...filters, range })}
              onView={setView}
              projectNames={projectNames}
              projectSlugs={filters.project_slugs}
              range={filters.range}
              view={view}
            />

            {activeChips.length > 0 && (
              <div className="mb-3 flex flex-wrap items-center gap-1.5">
                <span className="text-tertiary mr-1 text-[11px] font-semibold tracking-[0.06em] uppercase">
                  Filters
                </span>
                {activeChips.map((c) => (
                  <Button
                    className="bg-secondary text-secondary hover:text-primary h-6 rounded px-2 text-[12px]"
                    key={c.key}
                    onClick={c.clear}
                    type="button"
                    variant="ghost"
                  >
                    <span className="truncate">{c.label}</span>
                    <X className="size-3" />
                  </Button>
                ))}
                <Button
                  className="text-tertiary hover:bg-secondary hover:text-primary ml-1 h-auto rounded px-2 py-0.5 text-[12px]"
                  onClick={() =>
                    setFilters({
                      entry_types: [],
                      environment_slugs: [],
                      project_slugs: [],
                      q: filters.q,
                      range: filters.range,
                    })
                  }
                  type="button"
                  variant="ghost"
                >
                  Clear all
                </Button>
              </div>
            )}

            {isError && (
              <div className="border-danger bg-danger/10 text-danger mb-3 rounded-md border px-3 py-2 text-sm">
                Failed to load operations log.{' '}
                <Button
                  className="ml-2"
                  onClick={() => refetch()}
                  size="sm"
                  variant="ghost"
                >
                  Retry
                </Button>
              </div>
            )}

            {metadataError && (
              <div className="border-warning bg-warning/10 text-warning mb-3 rounded-md border px-3 py-2 text-sm">
                Some filter metadata failed to load — projects, environments, or
                users may show as slugs.{' '}
                <Button
                  className="ml-2"
                  onClick={retryMetadata}
                  size="sm"
                  variant="ghost"
                >
                  Retry
                </Button>
              </div>
            )}

            {isLoading && <LoadingState label="Loading operations log…" />}

            {!isLoading &&
              !isError &&
              (virtualItems.length === 0 ? (
                <div className="border-tertiary bg-primary text-tertiary rounded-md border px-6 py-16 text-center text-sm">
                  <SearchX className="text-tertiary mx-auto mb-2 size-7" />
                  No events match these filters.
                </div>
              ) : (
                <>
                  <div
                    className="border-tertiary bg-primary relative w-full overflow-hidden rounded-md border"
                    style={{ height: virtualizer.getTotalSize() }}
                  >
                    {virtualizer.getVirtualItems().map((v) => {
                      const vi = virtualItems[v.index]
                      if (!vi) return null
                      return (
                        <div
                          className="absolute top-0 right-0 left-0"
                          data-index={v.index}
                          key={v.key}
                          ref={virtualizer.measureElement}
                          style={{ transform: `translateY(${v.start}px)` }}
                        >
                          <OperationsLogFeedItem
                            environmentsBySlug={environmentsBySlug}
                            groupsById={groupsById}
                            performerDisplayNames={performerDisplayNames}
                            projectsBySlug={projectsBySlug}
                            toggleOpen={toggleOpen}
                            vi={vi}
                          />
                        </div>
                      )
                    })}
                  </div>
                  <div className="text-tertiary py-3 text-center text-xs">
                    {isFetchingNextPage
                      ? 'Loading more…'
                      : hasNextPage
                        ? null
                        : `End of log · ${visibleEntries.length} entries`}
                  </div>
                </>
              ))}
          </div>
        </main>
      </div>
    </div>
  )
}
