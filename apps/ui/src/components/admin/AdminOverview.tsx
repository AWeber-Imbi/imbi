// Admin · Overview dashboard (Direction B: ops console + status rail).
//
// Recreates the chosen design from the Admin Dashboard handoff inside the
// real admin shell. Real data is wired where the API already exposes it
// (operations-log metrics + project scores); everything the backend does not
// expose yet — datastore/service health, active-user counts, the 30-day score
// trend, and the per-label entity counts that need one Cypher count each — is
// MOCKED below and flagged so it's easy to swap for a real `/status` payload.

import { useMemo } from 'react'

import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  ArrowLeftRight,
  ArrowUpRight,
  Box,
  Building2,
  Database,
  FileCode2,
  FolderKanban,
  GitBranch,
  GitFork,
  Hash,
  KeyRound,
  Layers,
  type LucideIcon,
  Plug,
  Rocket,
  Shapes,
  Sparkles,
  User,
  Users,
  Webhook,
  Zap,
} from 'lucide-react'

import { getProjectsSlim, listOperationsLog } from '@/api/endpoints'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useOrganization } from '@/contexts/OrganizationContext'

// ---------------------------------------------------------------------------
// Mock data — not yet exposed by the API (see file header).
// ---------------------------------------------------------------------------

interface HealthEntry {
  icon: LucideIcon
  latency: string
  name: string
  role: string
}

// Tier-1 datastore pings (SELECT 1 / PING per store).
const MOCK_DATASTORES: HealthEntry[] = [
  { icon: GitFork, latency: '4.2 ms', name: 'Neo4j', role: 'graph · Pool' },
  {
    icon: Database,
    latency: '11.8 ms',
    name: 'ClickHouse',
    role: 'operations_log',
  },
  { icon: Zap, latency: '0.9 ms', name: 'Valkey', role: 'cache · client' },
]

const MOCK_SERVICES: { icon: LucideIcon; name: string }[] = [
  { icon: Sparkles, name: 'Assistant' },
  { icon: Webhook, name: 'API' },
  { icon: ArrowLeftRight, name: 'Gateway' },
  { icon: Plug, name: 'MCP' },
  { icon: Hash, name: 'Slackbot' },
]

// uniqExact(performed_by) over operations_log with a time filter.
const MOCK_ACTIVE_USERS = { last7d: 47, last30d: 112 }

// score_history materialized view — avg score over the last 30 days.
const MOCK_SCORE_TREND = [78, 79, 77, 80, 81, 80, 82, 83, 82, 82, 84, 82]

// 7-day deploy sparkline (per-day Deployed counts).
const MOCK_DEPLOY_SPARK = [38, 51, 44, 62, 35, 58, 54]

const LAST_CHECKED = '8s ago'

// ---------------------------------------------------------------------------
// Data hook — real operations-log metrics + project scores.
// ---------------------------------------------------------------------------

interface ScoreBand {
  count: number
  label: string
  range: string
  tone: 'danger' | 'success' | 'warning'
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
      count: valid.filter((p) => p.score < 75).length,
      label: 'At risk',
      range: '< 75',
      tone: 'danger',
    },
  ]
  const attention = [...valid].sort((a, b) => a.score - b.score).slice(0, 6)
  return { attention, average, bands, total }
}

function nfmt(n: number): string {
  return n.toLocaleString('en-US')
}

function sevenDaysAgoIso(): string {
  return new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString()
}

function titleCase(slug: string): string {
  return slug
    .split(/[-_\s]+/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

function useOverviewData(orgSlug: string) {
  const metricsQuery = useQuery({
    queryFn: ({ signal }) =>
      listOperationsLog(
        { filters: { since: sevenDaysAgoIso() }, limit: 1 },
        signal,
      ),
    queryKey: ['admin-overview', 'metrics'],
    staleTime: 60_000,
  })

  const projectsQuery = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => getProjectsSlim(orgSlug, signal),
    queryKey: ['admin-overview', 'projects', orgSlug],
    staleTime: 60_000,
  })

  const metrics = metricsQuery.data?.metrics

  const deploysByEnv = useMemo(() => {
    const raw = metrics?.deploys_by_environment ?? {}
    return Object.entries(raw)
      .map(([slug, count]) => ({ count, label: titleCase(slug), slug }))
      .sort((a, b) => b.count - a.count)
  }, [metrics])

  const scores = useMemo(
    () => deriveScores(projectsQuery.data ?? []),
    [projectsQuery.data],
  )

  return {
    deploysByEnv,
    metrics,
    metricsError: metricsQuery.isError,
    metricsLoading: metricsQuery.isLoading,
    projectCount: projectsQuery.data?.length ?? null,
    scores,
    scoresError: projectsQuery.isError,
    scoresLoading: projectsQuery.isLoading,
  }
}

// ---------------------------------------------------------------------------
// Shared bits
// ---------------------------------------------------------------------------

const TONE_TEXT: Record<string, string> = {
  danger: 'text-danger',
  success: 'text-success',
  warning: 'text-warning',
}
const TONE_BG: Record<string, string> = {
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
  const orgName = selectedOrganization?.name ?? 'Organization'
  const {
    deploysByEnv,
    metrics,
    metricsError,
    metricsLoading,
    projectCount,
    scores,
    scoresError,
    scoresLoading,
  } = useOverviewData(orgSlug)

  return (
    <div className="max-w-dashboard">
      <div className="mb-5 flex items-center justify-between gap-3">
        <p className="text-secondary text-sm">
          {orgName} tenant · operations metrics for the last 7 days
        </p>
        <span className="bg-secondary text-secondary inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 font-mono text-xs">
          <GitBranch className="size-3" />v{__APP_VERSION__}
        </span>
      </div>

      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        {/* Main column */}
        <div className="flex flex-col gap-6">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <MetricTile
              icon={Rocket}
              isError={metricsError}
              isLoading={metricsLoading}
              label="Deploys"
              spark={MOCK_DEPLOY_SPARK}
              sub="7 days"
              value={metrics?.deploys ?? null}
            />
            <MetricTile
              icon={Activity}
              isError={metricsError}
              isLoading={metricsLoading}
              label="Events"
              sub="7 days"
              value={metrics?.event_count ?? null}
            />
            <MetricTile
              icon={Users}
              label="Active users"
              sub={`${MOCK_ACTIVE_USERS.last30d} · 30d`}
              value={MOCK_ACTIVE_USERS.last7d}
            />
            <MetricTile
              icon={FolderKanban}
              isError={scoresError}
              isLoading={scoresLoading}
              label="Projects"
              sub="in catalog"
              value={projectCount}
            />
          </div>

          <section className="grid grid-cols-1 gap-5 md:grid-cols-2">
            <div>
              <SectionLabel
                right={
                  <span className="text-tertiary text-xs">
                    {nfmt(metrics?.deploys ?? 0)} total
                  </span>
                }
              >
                Deploys by environment
              </SectionLabel>
              <Card className="p-4">
                <DeploysByEnv
                  data={deploysByEnv}
                  isError={metricsError}
                  isLoading={metricsLoading}
                  total={metrics?.deploys ?? 0}
                />
              </Card>
            </div>
            <div>
              <SectionLabel
                right={
                  <span className="text-tertiary text-xs">
                    avg {scores.average ?? '—'}
                  </span>
                }
              >
                Project health
              </SectionLabel>
              <Card className="p-4">
                <ProjectHealth
                  isError={scoresError}
                  isLoading={scoresLoading}
                  scores={scores}
                />
              </Card>
            </div>
          </section>

          {scores.attention.length > 0 && (
            <section>
              <SectionLabel>Lowest scores</SectionLabel>
              <Card className="grid grid-cols-1 gap-x-7 gap-y-2 p-4 sm:grid-cols-2">
                {scores.attention.map((a) => (
                  <div className="flex items-center gap-2.5" key={a.slug}>
                    <span className="text-secondary flex-1 truncate font-mono text-[12.5px]">
                      {a.slug}
                    </span>
                    <ScorePip score={a.score} />
                  </div>
                ))}
              </Card>
            </section>
          )}

          <section>
            <SectionLabel
              right={
                <span className="text-tertiary text-xs">11 entity types</span>
              }
            >
              Catalog
            </SectionLabel>
            <CatalogGrid
              environments={metrics?.environments ?? null}
              projects={projectCount}
            />
          </section>
        </div>

        {/* Status rail */}
        <div className="flex flex-col gap-3.5">
          <SystemHealthRail />
          <ResourcesCard />
        </div>
      </div>
    </div>
  )
}

function CatalogGrid({
  environments,
  projects,
}: {
  environments: null | number
  projects: null | number
}) {
  // Real where the operations-log metrics expose it (Project, Environment);
  // the rest need a per-label Cypher count and are MOCKED for now.
  const entities: { count: null | number; icon: LucideIcon; label: string }[] =
    [
      { count: projects, icon: FolderKanban, label: 'Project' },
      { count: 47, icon: Box, label: 'Component' },
      { count: 14, icon: Shapes, label: 'ProjectType' },
      { count: 32, icon: FileCode2, label: 'Blueprint' },
      { count: environments, icon: Layers, label: 'Environment' },
      { count: 18, icon: Users, label: 'Team' },
      { count: 96, icon: User, label: 'User' },
      { count: 4, icon: Building2, label: 'Organization' },
      { count: 11, icon: Webhook, label: 'Webhook' },
      { count: 6, icon: Plug, label: 'MCPServer' },
      { count: 9, icon: KeyRound, label: 'OAuthClient' },
    ]
  return (
    <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-4">
      {entities.map((e) => (
        <div
          className="bg-primary border-tertiary hover:border-secondary flex flex-col gap-1.5 rounded-md border p-3 transition-colors"
          key={e.label}
        >
          <e.icon className="text-tertiary size-3.5" />
          <div>
            <div className="text-primary text-xl font-semibold tracking-tight tabular-nums">
              {e.count == null ? '—' : nfmt(e.count)}
            </div>
            <div className="text-tertiary mt-0.5 text-xs">{e.label}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

function DeploysByEnv({
  data,
  isError,
  isLoading,
  total,
}: {
  data: { count: number; label: string; slug: string }[]
  isError?: boolean
  isLoading?: boolean
  total: number
}) {
  if (isLoading) {
    return (
      <div className="flex flex-col gap-3">
        {[0, 1, 2].map((i) => (
          <Skeleton className="h-2.5 w-full" key={i} />
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
        No deploys in the last 7 days.
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-3">
      {data.map((d, i) => {
        const color = ENV_COLORS[i % ENV_COLORS.length]
        return (
          <div className="flex items-center gap-3" key={d.slug}>
            <span
              className="flex w-24 shrink-0 items-center gap-2 text-[12.5px] font-medium"
              style={{ color }}
            >
              <span
                className="size-[7px] rounded-full"
                style={{ background: color }}
              />
              {d.label}
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
            <Skeleton
              aria-label={`Loading ${label}`}
              className="h-8 w-20"
              role="status"
            />
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

function ProjectHealth({
  isError,
  isLoading,
  scores,
}: {
  isError?: boolean
  isLoading?: boolean
  scores: ReturnType<typeof deriveScores>
}) {
  if (isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-9 w-24" />
        <Skeleton className="h-2.5 w-full" />
        <Skeleton className="h-16 w-full" />
      </div>
    )
  }
  if (isError) {
    return <p className="text-danger text-sm">Unavailable</p>
  }
  const { average, bands, total } = scores
  return (
    <div>
      <div className="mb-3.5 flex items-end gap-3.5">
        <div>
          <div className="text-primary text-[34px] leading-none font-semibold tracking-tight tabular-nums">
            {average ?? '—'}
          </div>
          <div className="text-tertiary mt-1 text-xs">average score</div>
        </div>
        <div className="ml-auto text-right">
          <TrendLine data={MOCK_SCORE_TREND} />
          <div className="text-tertiary mt-0.5 text-xs">30-day trend</div>
        </div>
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
      <div className="flex flex-col gap-2">
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
    { icon: Webhook, name: 'REST API', url: `${base}/api/` },
    { icon: Plug, name: 'MCP server', url: `${base}/mcp/` },
    { icon: ArrowLeftRight, name: 'Webhook gateway', url: `${base}/gateway/` },
  ]
  const snippet = `claude mcp add imbi \\\n  --url ${base}/mcp/`
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
              <span className="bg-secondary text-secondary flex size-[30px] shrink-0 items-center justify-center rounded-md">
                <r.icon className="size-[15px]" />
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
        <div className="bg-secondary border-tertiary mt-2.5 rounded-md border px-3 py-2.5">
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

function ScorePip({ score }: { score: number }) {
  const tone = scorePipTone(score)
  return (
    <span
      className={`inline-flex h-[22px] min-w-[30px] items-center justify-center rounded-md px-[7px] font-mono text-[12.5px] font-semibold tabular-nums ${TONE_BG[tone]} ${TONE_TEXT[tone]}`}
    >
      {Math.round(score)}
    </span>
  )
}

function scorePipTone(score: number): string {
  if (score >= 85) return 'success'
  if (score >= 75) return 'warning'
  return 'danger'
}

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

function StatusDot({ size = 8 }: { size?: number }) {
  return (
    <span
      className="bg-success inline-block shrink-0 rounded-full"
      style={{
        boxShadow: '0 0 0 3px var(--ds-bg-success)',
        height: size,
        width: size,
      }}
    />
  )
}

function SystemHealthRail() {
  return (
    <Card className="overflow-hidden p-0">
      <div className="border-tertiary flex items-center gap-2.5 border-b px-4 py-3">
        <StatusDot size={9} />
        <span className="flex-1 text-[15px] font-semibold">System health</span>
        <span className="text-tertiary text-xs">{LAST_CHECKED}</span>
      </div>
      <div className="flex flex-col gap-2 p-3">
        {MOCK_DATASTORES.map((ds) => (
          <div
            className="bg-secondary flex items-center gap-3 rounded-md px-2.5 py-2.5"
            key={ds.name}
          >
            <span className="bg-success text-success flex size-[30px] shrink-0 items-center justify-center rounded-md">
              <ds.icon className="size-[15px]" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-[13px] font-semibold">{ds.name}</span>
                <StatusDot size={7} />
              </div>
              <span className="text-tertiary font-mono text-[11px]">
                {ds.role}
              </span>
            </div>
            <span className="font-mono text-xs font-semibold">
              {ds.latency}
            </span>
          </div>
        ))}
      </div>
      <div className="px-3 pb-3">
        <div className="text-tertiary mx-1 mb-2 text-xs font-semibold tracking-wider uppercase">
          Services
        </div>
        <div className="border-tertiary divide-tertiary divide-y overflow-hidden rounded-md border">
          {MOCK_SERVICES.map((s) => (
            <div
              className="bg-primary flex items-center gap-2.5 px-3 py-2.5"
              key={s.name}
            >
              <s.icon className="text-tertiary size-[15px]" />
              <span className="flex-1 text-[13.5px]">{s.name}</span>
              <StatusDot />
              <span className="text-success text-xs font-medium">Up</span>
            </div>
          ))}
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
