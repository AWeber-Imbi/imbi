import { useMemo } from 'react'

import type { OperationsLogMetrics } from '@/api/endpoints'
import { sortEnvironments } from '@/lib/utils'
import type { Environment, OperationsLogRecord } from '@/types'

import { type TimeRange, toMs } from './opsLogHelpers'

interface SummaryProps {
  entries: OperationsLogRecord[]
  environments: Environment[]
  loading?: boolean
  range: TimeRange
  rangeLabel: string
  // When the backend returns aggregate metrics for the full filter
  // universe, the tiles display those numbers rather than stats derived
  // only from `entries` (which is just the loaded pages).
  serverMetrics?: OperationsLogMetrics
}

function SkeletonBlock({ className }: { className: string }) {
  return (
    <span
      aria-hidden
      className={`bg-tertiary/40 inline-block animate-pulse rounded ${className}`}
    />
  )
}

const RANGE_WINDOW_MS: Record<Exclude<TimeRange, 'all'>, number> = {
  '7d': 7 * 24 * 60 * 60 * 1000,
  '24h': 24 * 60 * 60 * 1000,
  '30d': 30 * 24 * 60 * 60 * 1000,
  '90d': 90 * 24 * 60 * 60 * 1000,
}

const BARS = 12

export function OperationsLogSummary({
  entries,
  environments,
  loading = false,
  range,
  rangeLabel,
  serverMetrics,
}: SummaryProps) {
  // Terminal promotion target = highest sort_order env, matching the
  // release train. Avoids a hard-coded "production" slug so custom
  // pipelines with a final stage named e.g. "Live" pick up automatically.
  const terminalEnv = useMemo<Environment | undefined>(() => {
    const sorted = sortEnvironments(environments)
    return sorted[sorted.length - 1]
  }, [environments])
  // Single-pass aggregation: counts, uniques, sparkline buckets, and the
  // earliest-timestamp scan (for 'all time') all read the entries array
  // exactly once. Previously we did 4 filter/map passes plus 3 Set
  // allocations per render, all running again on every auto-fetch page.
  const terminalEnvSlug = terminalEnv?.slug
  const stats = useMemo(() => {
    const now = Date.now()
    const windowMs =
      range === 'all' ? 0 /* resolved after the pass */ : RANGE_WINDOW_MS[range]
    let effectiveWindowMs = windowMs
    let earliest = now

    const projectSlugs = new Set<string>()
    const envSlugs = new Set<string>()
    const people = new Set<string>()
    let deploys = 0
    let terminalDeploys = 0
    const occurredMs = new Array<number>(entries.length)
    for (let i = 0; i < entries.length; i++) {
      const e = entries[i]
      const t = toMs(e.occurred_at)
      occurredMs[i] = t
      if (range === 'all' && t < earliest) earliest = t
      projectSlugs.add(e.project_slug)
      if (e.environment_slug) envSlugs.add(e.environment_slug)
      // Match the row UI's performer fallback so the "Team members"
      // count doesn't underreport entries that show recorded_by.
      const performer = e.performed_by ?? e.recorded_by
      if (performer) people.add(performer)
      if (e.entry_type === 'Deployed') {
        deploys += 1
        if (terminalEnvSlug && e.environment_slug === terminalEnvSlug) {
          terminalDeploys += 1
        }
      }
    }
    if (range === 'all') {
      effectiveWindowMs = Math.max(60 * 60 * 1000, now - earliest)
    }
    const bucketMs = effectiveWindowMs / BARS
    const start = now - effectiveWindowMs
    const buckets = new Array<number>(BARS).fill(0)
    for (let i = 0; i < entries.length; i++) {
      const e = entries[i]
      if (e.entry_type !== 'Deployed') continue
      const t = occurredMs[i]
      if (t < start || t > now) continue
      const idx = Math.min(BARS - 1, Math.floor((t - start) / bucketMs))
      buckets[idx] += 1
    }
    let max = 1
    for (const v of buckets) if (v > max) max = v
    return {
      buckets,
      deploys,
      envCount: envSlugs.size,
      max,
      people: people.size,
      projects: projectSlugs.size,
      terminalDeploys,
    }
  }, [entries, range, terminalEnvSlug])

  const { buckets, max } = stats
  // Prefer server-computed metrics (which cover the full filter
  // universe) over numbers derived from just the loaded pages.
  const events = serverMetrics?.event_count ?? entries.length
  const deploys = serverMetrics?.deploys ?? stats.deploys
  const projects = serverMetrics?.projects ?? stats.projects
  const envCount = serverMetrics?.environments ?? stats.envCount
  const people = serverMetrics?.team_members ?? stats.people
  const terminalDeploys = terminalEnvSlug
    ? (serverMetrics?.deploys_by_environment?.[terminalEnvSlug] ??
      stats.terminalDeploys)
    : stats.terminalDeploys

  return (
    <div className="mb-4 grid grid-cols-2 overflow-hidden rounded-md border border-tertiary bg-primary md:grid-cols-4">
      <div className="flex flex-col gap-1 border-b border-r border-tertiary p-3 md:border-b-0">
        <span className="text-[11px] font-semibold uppercase tracking-[0.04em] text-tertiary">
          Events
        </span>
        {loading ? (
          <SkeletonBlock className="mt-0.5 h-5 w-16" />
        ) : (
          <span className="flex items-baseline gap-1.5 font-medium tabular-nums text-primary">
            <span className="text-xl leading-none">
              {events.toLocaleString()}
            </span>
            <span className="text-[11px] uppercase tracking-wide text-tertiary">
              in {rangeLabel}
            </span>
          </span>
        )}
        <div aria-hidden="true" className="mt-1 flex h-4 items-end gap-[2px]">
          {loading
            ? Array.from({ length: BARS }).map((_, i) => (
                <span
                  className="bg-tertiary/30 h-full flex-1 rounded-[1px]"
                  key={i}
                />
              ))
            : buckets.map((v, i) => (
                <span
                  className="flex-1 rounded-[1px] bg-amber-bg"
                  key={i}
                  style={{
                    height: v === 0 ? '0%' : `${Math.max(8, (v / max) * 100)}%`,
                  }}
                />
              ))}
        </div>
      </div>
      <div className="flex flex-col gap-1 border-b border-tertiary p-3 md:border-b-0 md:border-r">
        <span className="text-[11px] font-semibold uppercase tracking-[0.04em] text-tertiary">
          Deploys
        </span>
        {loading ? (
          <>
            <SkeletonBlock className="mt-0.5 h-5 w-12" />
            <SkeletonBlock className="mt-1 h-3 w-24" />
          </>
        ) : (
          <>
            <span className="text-xl font-medium tabular-nums leading-none text-primary">
              {deploys.toLocaleString()}
            </span>
            <span className="text-[11.5px] text-secondary">
              {terminalEnv
                ? `${terminalDeploys.toLocaleString()} to ${terminalEnv.name}`
                : `${deploys.toLocaleString()} total`}
            </span>
          </>
        )}
      </div>
      <div className="flex flex-col gap-1 border-r border-tertiary p-3">
        <span className="text-[11px] font-semibold uppercase tracking-[0.04em] text-tertiary">
          Projects touched
        </span>
        {loading ? (
          <>
            <SkeletonBlock className="mt-0.5 h-5 w-10" />
            <SkeletonBlock className="mt-1 h-3 w-32" />
          </>
        ) : (
          <>
            <span className="text-xl font-medium tabular-nums leading-none text-primary">
              {projects.toLocaleString()}
            </span>
            <span className="text-[11.5px] text-secondary">
              across {envCount.toLocaleString()}{' '}
              {envCount === 1 ? 'environment' : 'environments'}
            </span>
          </>
        )}
      </div>
      <div className="flex flex-col gap-1 p-3">
        <span className="text-[11px] font-semibold uppercase tracking-[0.04em] text-tertiary">
          Team members
        </span>
        {loading ? (
          <>
            <SkeletonBlock className="mt-0.5 h-5 w-10" />
            <SkeletonBlock className="mt-1 h-3 w-28" />
          </>
        ) : (
          <>
            <span className="text-xl font-medium tabular-nums leading-none text-primary">
              {people.toLocaleString()}
            </span>
            <span className="text-[11.5px] text-secondary">
              active in {rangeLabel}
            </span>
          </>
        )}
      </div>
    </div>
  )
}
