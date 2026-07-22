// Admin · Overview dashboard (Direction B: ops console + status rail).
//
// Recreates the chosen design from the Admin Dashboard handoff inside the
// real admin shell. All data is live: 7-day activity metrics via
// /admin/dashboard/metrics, project scores, the 30-day score trend via
// /scores/history-by-team, and datastore/service health via
// /admin/dashboard/status.

import { useMemo } from 'react'

import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  ArrowLeftRight,
  ArrowUpRight,
  BookOpen,
  Box,
  Database,
  GitFork,
  GitPullRequest,
  Hash,
  type LucideIcon,
  Plug,
  Rocket,
  ScrollText,
  Sparkles,
  Webhook,
  Zap,
} from 'lucide-react'

import {
  getDashboardMetrics,
  getDashboardStatus,
  getProjectsSlim,
  getScoreHistoryByTeam,
  listEnvironments,
  type TeamScoreSeries,
} from '@/api/endpoints'
import { Card } from '@/components/ui/card'
import { Sk } from '@/components/ui/skeleton'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useTheme } from '@/contexts/ThemeContext'
import { deriveChipColors } from '@/lib/chip-colors'
import type { DatastoreStatus, ServiceStatus } from '@/types'

// Icons keyed by the name the dashboard status endpoint returns.
const DATASTORE_ICONS: Record<string, LucideIcon> = {
  ClickHouse: Database,
  PostgreSQL: GitFork,
  Valkey: Zap,
}

const SERVICE_ICONS: Record<string, LucideIcon> = {
  API: Webhook,
  Assistant: Sparkles,
  Gateway: ArrowLeftRight,
  MCP: Plug,
  Slackbot: Hash,
}

// ---------------------------------------------------------------------------
// Data hook — real operations-log metrics + project scores.
// ---------------------------------------------------------------------------

interface ScoreBand {
  count: number
  label: string
  range: string
  tone: 'critical' | 'danger' | 'success' | 'warning'
}

// Collapse the per-team daily score series (from /scores/history-by-team)
// into a single trend line: for each day bucket, average every team's
// latest-known daily score (carried forward over days a team didn't
// change). The result is then emitted as a continuous daily series from
// the first data day through today, repeating the prior day's value on
// days with no score changes, so the line spans the window rather than
// collapsing onto the handful of days that actually changed.
// fallow-ignore-next-line complexity
function aggregateScoreTrend(teams: TeamScoreSeries[]): number[] {
  const dayKey = (ts: string) => ts.slice(0, 10)
  const days = [
    ...new Set(teams.flatMap((t) => t.points.map((p) => dayKey(p.timestamp)))),
  ].sort()
  if (days.length === 0) return []
  const teamMaps = teams.map(
    (t) => new Map(t.points.map((p) => [dayKey(p.timestamp), p.score])),
  )
  const lastKnown: (null | number)[] = teams.map(() => null)
  const avgByDay = new Map<string, number>()
  for (const day of days) {
    teamMaps.forEach((m, i) => {
      const v = m.get(day)
      if (v != null) lastKnown[i] = v
    })
    const vals = lastKnown.filter((v): v is number => v != null)
    if (vals.length > 0) {
      avgByDay.set(day, vals.reduce((a, b) => a + b, 0) / vals.length)
    }
  }
  const trend: number[] = []
  let carried: null | number = null
  const cursor = new Date(`${days[0]}T00:00:00Z`)
  const end = new Date(`${new Date().toISOString().slice(0, 10)}T00:00:00Z`)
  while (cursor.getTime() <= end.getTime()) {
    const value = avgByDay.get(cursor.toISOString().slice(0, 10))
    if (value != null) carried = value
    if (carried != null) trend.push(carried)
    cursor.setUTCDate(cursor.getUTCDate() + 1)
  }
  return trend
}

function deriveScores(projects: { score: null | number; slug: string }[]) {
  const valid = projects.filter(
    (p): p is { score: number; slug: string } =>
      p.score != null && Number.isFinite(p.score),
  )
  const total = valid.length
  const average = total
    ? Math.round(valid.reduce((sum, p) => sum + p.score, 0) / total)
    : null
  const bands: ScoreBand[] = [
    {
      count: valid.filter((p) => p.score >= 85).length,
      label: 'Healthy',
      range: '85–100',
      tone: 'success',
    },
    {
      count: valid.filter((p) => p.score >= 75 && p.score < 85).length,
      label: 'Fair',
      range: '75–84',
      tone: 'warning',
    },
    {
      count: valid.filter((p) => p.score >= 50 && p.score < 75).length,
      label: 'At risk',
      range: '50–74',
      tone: 'danger',
    },
    {
      count: valid.filter((p) => p.score < 50).length,
      label: 'Unhealthy',
      range: '< 50',
      tone: 'critical',
    },
  ]
  return { average, bands, total }
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KiB', 'MiB', 'GiB', 'TiB']
  let value = bytes / 1024
  let i = 0
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024
    i++
  }
  return `${value.toFixed(1)} ${units[i]}`
}

function nfmt(n: number): string {
  return n.toLocaleString('en-US')
}

function relativeTime(iso: string): string {
  const secs = Math.max(
    0,
    Math.round((Date.now() - new Date(iso).getTime()) / 1000),
  )
  if (secs < 60) return `${secs}s ago`
  const mins = Math.round(secs / 60)
  if (mins < 60) return `${mins}m ago`
  return `${Math.round(mins / 60)}h ago`
}

function thirtyDaysAgoIso(): string {
  return new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString()
}

function titleCase(slug: string): string {
  return slug
    .split(/[-_\s]+/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

function useOverviewData(orgSlug: string) {
  const metricsQuery = useQuery({
    queryFn: ({ signal }) => getDashboardMetrics(signal),
    queryKey: ['admin-overview', 'metrics'],
    staleTime: 60_000,
  })

  const projectsQuery = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => getProjectsSlim(orgSlug, signal),
    queryKey: ['admin-overview', 'projects', orgSlug],
    staleTime: 60_000,
  })

  const trendQuery = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) =>
      getScoreHistoryByTeam(
        { from: thirtyDaysAgoIso(), granularity: 'day', org: orgSlug },
        signal,
      ),
    queryKey: ['admin-overview', 'score-trend', orgSlug],
    staleTime: 120_000,
  })

  const environmentsQuery = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listEnvironments(orgSlug, signal),
    queryKey: ['admin-overview', 'environments', orgSlug],
    staleTime: 10 * 60_000,
  })

  const metrics = metricsQuery.data

  // Merge the per-environment release counts onto the full environment list so
  // every environment shows even with zero releases, ordered by the
  // environment's ``sort_order`` descending.
  const deploysByEnv = useMemo(() => {
    const counts = new Map(
      (metrics?.releases_by_environment ?? []).map((e) => [e.slug, e.count]),
    )
    return [...(environmentsQuery.data ?? [])]
      .sort((a, b) => b.sort_order - a.sort_order)
      .map((env) => ({
        count: counts.get(env.slug) ?? 0,
        label: env.name || titleCase(env.slug),
        labelColor: env.label_color ?? null,
        slug: env.slug,
      }))
  }, [metrics, environmentsQuery.data])

  const scores = useMemo(
    () => deriveScores(projectsQuery.data ?? []),
    [projectsQuery.data],
  )

  const scoreTrend = useMemo(
    () => aggregateScoreTrend(trendQuery.data?.teams ?? []),
    [trendQuery.data],
  )

  return {
    deploysByEnv,
    deploysError: metricsQuery.isError || environmentsQuery.isError,
    deploysLoading: metricsQuery.isLoading || environmentsQuery.isLoading,
    metrics,
    metricsError: metricsQuery.isError,
    metricsLoading: metricsQuery.isLoading,
    scores,
    scoresError: projectsQuery.isError,
    scoresLoading: projectsQuery.isLoading,
    scoreTrend,
  }
}

// ---------------------------------------------------------------------------
// Shared bits
// ---------------------------------------------------------------------------

const TONE_BG: Record<string, string> = {
  critical: 'bg-[var(--color-status-failed-dot)]',
  danger: 'bg-danger',
  success: 'bg-success',
  warning: 'bg-warning',
}

// Saturated, theme-neutral palette cycled across deploy environments.
const ENV_COLORS = [
  'var(--color-entity-project)',
  'var(--color-status-feedback-dot)',
  'var(--color-status-review-dot)',
  'var(--color-status-implementing-dot)',
  'var(--color-status-failed-dot)',
]

// fallow-ignore-next-line complexity
export function AdminOverview() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''
  const {
    deploysByEnv,
    deploysError,
    deploysLoading,
    metrics,
    metricsError,
    metricsLoading,
    scores,
    scoresError,
    scoresLoading,
    scoreTrend,
  } = useOverviewData(orgSlug)

  return (
    <div className="max-w-dashboard">
      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        {/* Main column */}
        <div className="flex flex-col gap-6">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <MetricTile
              icon={Rocket}
              isError={metricsError}
              isLoading={metricsLoading}
              label="Releases"
              spark={metrics?.releases.daily}
              sub="7 days"
              value={metrics?.releases.total ?? null}
            />
            <MetricTile
              icon={Activity}
              isError={metricsError}
              isLoading={metricsLoading}
              label="Events"
              spark={metrics?.events.daily}
              sub="7 days"
              value={metrics?.events.total ?? null}
            />
            <MetricTile
              icon={ScrollText}
              isError={metricsError}
              isLoading={metricsLoading}
              label="OpsLog Entries"
              spark={metrics?.ops_log.daily}
              sub="7 days"
              value={metrics?.ops_log.total ?? null}
            />
            <MetricTile
              icon={GitPullRequest}
              isError={metricsError}
              isLoading={metricsLoading}
              label="Pull Requests"
              spark={metrics?.pull_requests.daily}
              sub="7 days"
              value={metrics?.pull_requests.total ?? null}
            />
          </div>

          <section className="grid grid-cols-1 items-stretch gap-5 md:grid-cols-[2fr_1fr]">
            <div className="flex flex-col">
              <SectionLabel
                right={
                  <span className="text-tertiary text-xs">
                    {nfmt(metrics?.releases.total ?? 0)} total
                  </span>
                }
              >
                Releases by Environment
              </SectionLabel>
              <Card className="flex-1 p-4">
                <DeploysByEnv
                  data={deploysByEnv}
                  isError={deploysError}
                  isLoading={deploysLoading}
                  total={metrics?.releases.total ?? 0}
                />
              </Card>
            </div>
            <div className="flex flex-col">
              <SectionLabel
                right={
                  <span className="text-tertiary text-xs">
                    avg {scores.average ?? '—'}
                  </span>
                }
              >
                Project health
              </SectionLabel>
              <Card className="flex-1 p-4">
                <ProjectHealth
                  isError={scoresError}
                  isLoading={scoresLoading}
                  scores={scores}
                  trend={scoreTrend}
                />
              </Card>
            </div>
          </section>

          <ResourcesCard />
        </div>

        {/* Status rail */}
        <div className="flex flex-col gap-3.5">
          <SystemHealthRail />
        </div>
      </div>
    </div>
  )
}

// fallow-ignore-next-line complexity
function DatastoreRow({ ds }: { ds: DatastoreStatus }) {
  const Icon = DATASTORE_ICONS[ds.name] ?? Box
  const ok = ds.status === 'ok'
  return (
    <div className="bg-secondary flex items-center gap-3 rounded-md px-2.5 py-2.5">
      <span
        className={`${ok ? 'bg-success text-success' : 'bg-danger text-danger'} flex size-7.5 shrink-0 items-center justify-center rounded-md`}
      >
        <Icon className="size-3.75" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold">{ds.name}</span>
          <StatusDot ok={ok} size={7} />
        </div>
        <span className="text-tertiary font-mono text-[11px]">{ds.role}</span>
      </div>
      <div className="text-right">
        <div className="font-mono text-xs font-semibold">
          {ok && ds.latency_ms != null ? `${ds.latency_ms} ms` : '—'}
        </div>
        {ok && ds.size_bytes != null && (
          <div className="text-tertiary font-mono text-[11px]">
            {ds.total_bytes != null
              ? `${formatBytes(ds.size_bytes)} of ${formatBytes(ds.total_bytes)}`
              : formatBytes(ds.size_bytes)}
          </div>
        )}
      </div>
    </div>
  )
}

function DeploysByEnv({
  data,
  isError,
  isLoading,
  total,
}: {
  data: {
    count: number
    label: string
    labelColor: null | string
    slug: string
  }[]
  isError?: boolean
  isLoading?: boolean
  total: number
}) {
  const { isDarkMode } = useTheme()
  if (isLoading) {
    return (
      <div className="flex flex-col gap-3">
        {[0, 1, 2].map((i) => (
          <div className="flex items-center gap-3" key={i}>
            <Sk className="w-32 shrink-0" h={13} />
            <Sk className="flex-1" h={8} r={4} />
            <Sk className="w-9 shrink-0" h={13} />
          </div>
        ))}
      </div>
    )
  }
  if (isError) {
    return <p className="text-danger text-sm">Unavailable</p>
  }
  const max = Math.max(...data.map((d) => d.count), 1)
  if (data.length === 0) {
    return (
      <div className="text-tertiary text-sm">
        No releases in the last 7 days.
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-3">
      {data.map((d, i) => {
        const derived = d.labelColor
          ? deriveChipColors(d.labelColor, isDarkMode)
          : null
        const color = derived?.fg ?? ENV_COLORS[i % ENV_COLORS.length]
        return (
          <div className="flex items-center gap-3" key={d.slug}>
            <span
              className="flex w-32 shrink-0 items-center gap-2 text-[12.5px] font-medium"
              style={{ color }}
              title={d.label}
            >
              <span
                className="size-1.75 shrink-0 rounded-full"
                style={{ background: color }}
              />
              <span className="truncate">{d.label}</span>
            </span>
            <div className="bg-secondary h-2 flex-1 overflow-hidden rounded">
              <div
                className="h-full rounded"
                style={{
                  background: color,
                  opacity: 0.55,
                  width: `${(d.count / max) * 100}%`,
                }}
              />
            </div>
            <span className="w-9 text-right font-mono text-[13px] font-semibold tabular-nums">
              {d.count}
            </span>
          </div>
        )
      })}
      <div className="text-tertiary mt-1 text-xs">
        {nfmt(total)} total · last 7 days
      </div>
    </div>
  )
}

// fallow-ignore-next-line complexity
function MetricTile({
  icon: Icon,
  isError = false,
  isLoading = false,
  label,
  spark,
  sub,
  value,
}: {
  icon: LucideIcon
  isError?: boolean
  isLoading?: boolean
  label: string
  spark?: number[]
  sub: string
  value: null | number
}) {
  return (
    <Card className="hover:border-secondary flex flex-col gap-3 p-4 transition-colors">
      <div className="flex items-center justify-between">
        <span className="text-tertiary text-xs font-semibold tracking-wider uppercase">
          {label}
        </span>
        <Icon className="text-tertiary size-4" />
      </div>
      <div className="flex items-end justify-between gap-2">
        <div>
          {isLoading ? (
            <Sk h={32} r={6} w={80} />
          ) : isError ? (
            <p className="text-danger text-sm">Unavailable</p>
          ) : (
            <div className="text-primary text-3xl font-semibold tracking-tight tabular-nums">
              {value == null ? '—' : nfmt(value)}
            </div>
          )}
          <div className="text-tertiary mt-1 text-xs">{sub}</div>
        </div>
        {spark && !isLoading && !isError ? <Sparkbars data={spark} /> : null}
      </div>
    </Card>
  )
}

// fallow-ignore-next-line complexity
function ProjectHealth({
  isError,
  isLoading,
  scores,
  trend,
}: {
  isError?: boolean
  isLoading?: boolean
  scores: ReturnType<typeof deriveScores>
  trend: number[]
}) {
  if (isLoading) {
    return (
      <div>
        <div className="mb-3.5">
          <Sk h={34} w={56} />
          <Sk className="mt-1" h={10} w={80} />
        </div>
        <Sk className="mb-3 w-full" h={10} r={5} />
        <div className="flex flex-col gap-2">
          {[0, 1, 2].map((i) => (
            <div className="flex items-center gap-2.5" key={i}>
              <Sk h={8} r={2} w={8} />
              <Sk className="flex-1" h={11} />
              <Sk h={11} w={28} />
            </div>
          ))}
        </div>
      </div>
    )
  }
  if (isError) {
    return <p className="text-danger text-sm">Unavailable</p>
  }
  const { average, bands, total } = scores
  return (
    <div className="flex h-full flex-col">
      <div className="mb-3.5 flex items-end gap-3.5">
        <div>
          <div className="text-primary text-[34px] leading-none font-semibold tracking-tight tabular-nums">
            {average ?? '—'}
          </div>
          <div className="text-tertiary mt-1 text-xs">average score</div>
        </div>
        {trend.length >= 2 && (
          <div className="ml-auto text-right">
            <TrendLine data={trend} />
            <div className="text-tertiary mt-0.5 text-xs">30-day trend</div>
          </div>
        )}
      </div>
      <div className="mb-3 flex h-2.5 gap-0.5 overflow-hidden rounded-[5px]">
        {bands.map((b) => (
          <div
            className={TONE_BG[b.tone]}
            key={b.tone}
            style={{ flex: b.count || 0.0001, opacity: 0.7 }}
            title={`${b.label}: ${b.count}`}
          />
        ))}
      </div>
      <div className="mt-auto flex flex-col gap-2">
        {bands.map((b) => (
          <div className="flex items-center gap-2.5 text-[13px]" key={b.tone}>
            <span
              className={`size-2 rounded-sm ${TONE_BG[b.tone]}`}
              style={{ opacity: 0.7 }}
            />
            <span className="flex-1">
              {b.label} <span className="text-tertiary text-xs">{b.range}</span>
            </span>
            <span className="font-mono font-semibold tabular-nums">
              {nfmt(b.count)}
            </span>
            <span className="text-tertiary w-9 text-right text-xs">
              {total ? Math.round((b.count / total) * 100) : 0}%
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function ResourcesCard() {
  const base = window.location.origin
  const resources = [
    { icon: BookOpen, name: 'API docs', url: `${base}/docs` },
    { icon: Webhook, name: 'REST API', url: `${base}/api/` },
    { icon: Plug, name: 'MCP server', url: `${base}/mcp/` },
    { icon: ArrowLeftRight, name: 'Webhook gateway', url: `${base}/gateway/` },
  ]
  const snippet = `claude mcp add imbi --url ${base}/mcp/`
  return (
    <Card className="overflow-hidden p-0">
      <div className="px-4 pt-3 pb-1">
        <span className="text-[15px] font-semibold">Resources</span>
      </div>
      <div className="px-2 pb-3">
        <div className="flex flex-col gap-px">
          {resources.map((r) => (
            <a
              className="hover:bg-secondary flex items-center gap-3 rounded-md px-3 py-2.5 no-underline transition-colors"
              href={r.url}
              key={r.name}
              rel="noreferrer"
              target="_blank"
            >
              <span className="bg-secondary text-secondary flex size-7.5 shrink-0 items-center justify-center rounded-md">
                <r.icon className="size-3.75" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[13.5px] font-medium">
                  {r.name}
                </span>
                <span className="text-tertiary block truncate font-mono text-[11.5px]">
                  {r.url}
                </span>
              </span>
              <ArrowUpRight className="text-tertiary size-3.5" />
            </a>
          ))}
        </div>
        <div className="border-tertiary bg-secondary mt-2.5 rounded-md border px-3 py-2.5">
          <div className="text-tertiary mb-1.5 text-[10px] font-semibold tracking-wider uppercase">
            Connect the MCP server
          </div>
          <pre className="text-secondary font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap">
            {snippet}
          </pre>
        </div>
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Tiles
// ---------------------------------------------------------------------------

function SectionLabel({
  children,
  right,
}: {
  children: React.ReactNode
  right?: React.ReactNode
}) {
  return (
    <div className="mb-3 flex items-baseline justify-between">
      <div className="text-tertiary text-xs font-semibold tracking-wider uppercase">
        {children}
      </div>
      {right}
    </div>
  )
}

// fallow-ignore-next-line complexity
function ServiceRow({ service }: { service: ServiceStatus }) {
  const Icon = SERVICE_ICONS[service.name] ?? Box
  const up = service.status === 'up'
  return (
    <div className="bg-primary flex items-center gap-2.5 px-3 py-2.5">
      <Icon className="text-tertiary size-3.75" />
      <span className="flex-1 text-[13.5px]">{service.name}</span>
      {service.version && (
        <span className="text-tertiary font-mono text-[11px]">
          v{service.version}
        </span>
      )}
      <StatusDot ok={up} />
      <span
        className={`${up ? 'text-success' : 'text-danger'} text-xs font-medium`}
      >
        {up ? 'Up' : 'Down'}
      </span>
    </div>
  )
}

function Sparkbars({ data }: { data: number[] }) {
  const max = Math.max(...data, 1)
  const w = 64
  const h = 22
  const gap = 2
  const bw = (w - gap * (data.length - 1)) / data.length
  return (
    <svg className="block" height={h} width={w}>
      {data.map((v, i) => {
        const bh = Math.max(2, (v / max) * h)
        return (
          <rect
            fill="var(--text-color-amber-border)"
            height={bh}
            key={i}
            opacity={i === data.length - 1 ? 1 : 0.4}
            rx={1}
            width={bw}
            x={i * (bw + gap)}
            y={h - bh}
          />
        )
      })}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Status rail
// ---------------------------------------------------------------------------

function StatusDot({ ok = true, size = 8 }: { ok?: boolean; size?: number }) {
  return (
    <span
      className={`${ok ? 'bg-success' : 'bg-danger'} inline-block shrink-0 rounded-full`}
      style={{
        boxShadow: `0 0 0 3px ${ok ? 'var(--ds-bg-success)' : 'var(--ds-bg-danger)'}`,
        height: size,
        width: size,
      }}
    />
  )
}

// fallow-ignore-next-line complexity
function SystemHealthRail() {
  const { data, isError, isLoading } = useQuery({
    queryFn: ({ signal }) => getDashboardStatus(signal),
    queryKey: ['admin-overview', 'status'],
    refetchInterval: 15_000,
    staleTime: 10_000,
  })

  const datastores = data?.datastores ?? []
  const services = data?.services ?? []
  const loadingFirst = isLoading && !data

  let headerNote: string
  if (loadingFirst) headerNote = 'checking…'
  else if (isError || !data) headerNote = 'unavailable'
  else headerNote = relativeTime(data.checked_at)

  return (
    <Card className="overflow-hidden p-0">
      <div className="border-tertiary flex items-center gap-2.5 border-b px-4 py-3">
        <span className="flex-1 text-[15px] font-semibold">System health</span>
        <span className="text-tertiary text-xs">{headerNote}</span>
      </div>
      <div className="flex flex-col gap-2 p-3">
        {loadingFirst
          ? [0, 1, 2].map((i) => (
              <div
                aria-busy
                className="bg-secondary flex items-center gap-3 rounded-md px-2.5 py-2.5"
                key={i}
              >
                <Sk h={30} r={6} w={30} />
                <div className="min-w-0 flex-1 space-y-1.5">
                  <Sk h={11} w={96} />
                  <Sk h={9} w={64} />
                </div>
                <Sk h={11} w={48} />
              </div>
            ))
          : datastores.map((ds) => <DatastoreRow ds={ds} key={ds.name} />)}
      </div>
      <div className="px-3 pb-3">
        <div className="text-tertiary mx-1 mb-2 text-xs font-semibold tracking-wider uppercase">
          Services
        </div>
        <div className="divide-tertiary border-tertiary divide-y overflow-hidden rounded-md border">
          {loadingFirst
            ? [0, 1, 2, 3].map((i) => (
                <div
                  aria-busy
                  className="bg-primary flex items-center gap-2.5 px-3 py-2.5"
                  key={i}
                >
                  <Sk h={15} r={4} w={15} />
                  <Sk className="flex-1" h={11} w={80} />
                  <Sk h={9} w={36} />
                  <Sk circle h={8} w={8} />
                </div>
              ))
            : services.map((s) => <ServiceRow key={s.name} service={s} />)}
        </div>
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

function TrendLine({ data }: { data: number[] }) {
  const w = 120
  const h = 34
  const min = Math.min(...data)
  const max = Math.max(...data)
  const span = max - min || 1
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w
    const y = h - 3 - ((v - min) / span) * (h - 6)
    return [x, y] as const
  })
  const line = pts
    .map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`)
    .join(' ')
  const area = `${line} L${w} ${h} L0 ${h} Z`
  const last = pts[pts.length - 1]
  return (
    <svg className="block" height={h} width={w}>
      <path d={area} fill="var(--ds-bg-success)" />
      <path
        d={line}
        fill="none"
        stroke="var(--ds-text-success)"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
      />
      <circle cx={last[0]} cy={last[1]} fill="var(--ds-text-success)" r="2.5" />
    </svg>
  )
}
