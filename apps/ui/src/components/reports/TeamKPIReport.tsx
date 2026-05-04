import { useEffect, useRef, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'

import { getScoreRollup, listTeams, ScoreRollupRow } from '@/api/endpoints'
import { useOrganization } from '@/contexts/OrganizationContext'
import { Team } from '@/types'

interface BarChartProps {
  rows: TeamRow[]
}

interface TeamRow extends ScoreRollupRow {
  name: string
  project_count?: number
}

export function TeamKPIReport() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''

  const {
    data: rollup,
    error: rollupError,
    isLoading: rollupLoading,
    refetch: refetchRollup,
  } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => getScoreRollup('team', signal),
    queryKey: ['scoreRollup', 'team', orgSlug],
    staleTime: 60_000,
  })

  const {
    data: teams,
    error: teamsError,
    isLoading: teamsLoading,
    refetch: refetchTeams,
  } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listTeams(orgSlug, signal),
    queryKey: ['teams', orgSlug],
    staleTime: 120_000,
  })

  const isLoading = rollupLoading || teamsLoading
  const hasError = !!(rollupError || teamsError)

  function refetchAll() {
    void refetchRollup()
    void refetchTeams()
  }

  const rows: TeamRow[] = (() => {
    if (!rollup) return []
    const teamBySlug = new Map<string, Team>(
      (teams ?? []).map((t) => [t.slug, t]),
    )
    return rollup.map((r) => ({
      ...r,
      name: teamBySlug.get(r.key)?.name ?? r.key,
    }))
  })()

  const sorted = [...rows].sort((a, b) => b.avg_score - a.avg_score)

  const avgOfAvgs =
    rows.length > 0
      ? rows.reduce((s, r) => s + r.avg_score, 0) / rows.length
      : null

  return (
    <div className="flex flex-col gap-5">
      {/* Summary stat row */}
      <div className="grid grid-cols-3 gap-4">
        <StatCard
          label="Teams tracked"
          value={isLoading || hasError ? '—' : String(rows.length)}
        />
        <StatCard
          label="Org avg score"
          value={
            isLoading || hasError || avgOfAvgs == null
              ? '—'
              : fmtScore(avgOfAvgs)
          }
          valueColor={avgOfAvgs != null ? scoreColor(avgOfAvgs) : undefined}
        />
        <StatCard
          label="Top team score"
          value={
            isLoading || hasError || sorted.length === 0
              ? '—'
              : fmtScore(sorted[0].avg_score)
          }
          valueColor={
            sorted.length > 0 ? scoreColor(sorted[0].avg_score) : undefined
          }
        />
      </div>

      {/* Bar chart card */}
      <div className="rounded-lg border border-tertiary bg-primary p-[18px]">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <div className="text-overline uppercase tracking-wide text-tertiary">
              Avg score by team
            </div>
            <div className="mt-0.5 text-xs text-tertiary">
              Bar = avg across all projects · tick = best project score
            </div>
          </div>
          <button
            className="inline-flex h-7 items-center gap-1.5 rounded border border-tertiary px-2.5 text-xs text-primary transition-colors hover:bg-secondary"
            onClick={refetchAll}
          >
            <RefreshCw size={11} />
            Refresh
          </button>
        </div>

        {isLoading ? (
          <div className="flex h-40 items-center justify-center text-sm text-tertiary">
            Loading…
          </div>
        ) : hasError ? (
          <div className="flex h-40 items-center justify-center text-sm text-danger">
            Failed to load report data. Please try again.
          </div>
        ) : rows.length === 0 ? (
          <div className="flex h-40 items-center justify-center text-sm text-tertiary">
            No score data yet. Projects need to be scored first.
          </div>
        ) : (
          <TeamBarChart rows={rows} />
        )}
      </div>

      {/* Table card */}
      <div className="rounded-lg border border-tertiary bg-primary">
        <div className="border-b border-tertiary px-[18px] py-3.5">
          <div className="text-overline uppercase tracking-wide text-tertiary">
            Team details
          </div>
        </div>

        {isLoading ? (
          <div className="py-10 text-center text-sm text-tertiary">
            Loading…
          </div>
        ) : hasError ? (
          <div className="py-10 text-center text-sm text-danger">
            Failed to load report data.{' '}
            <button className="underline" onClick={refetchAll}>
              Retry
            </button>
          </div>
        ) : sorted.length === 0 ? (
          <div className="py-10 text-center text-sm text-tertiary">
            No data available.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-tertiary">
                <th className="px-[18px] py-2.5 text-left text-overline font-normal uppercase tracking-wide text-tertiary">
                  Team
                </th>
                <th className="px-4 py-2.5 text-right text-overline font-normal uppercase tracking-wide text-tertiary">
                  Avg score
                </th>
                <th className="px-4 py-2.5 text-right text-overline font-normal uppercase tracking-wide text-tertiary">
                  Best project
                </th>
                <th className="px-[18px] py-2.5 text-right text-overline font-normal uppercase tracking-wide text-tertiary">
                  Last scored
                </th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((row, i) => (
                <tr
                  className={`border-b border-tertiary transition-colors hover:bg-secondary ${
                    i === sorted.length - 1 ? 'border-0' : ''
                  }`}
                  key={row.key}
                >
                  <td className="px-[18px] py-3 font-medium text-primary">
                    {row.name}
                    <span className="ml-2 font-mono text-[11px] text-tertiary">
                      {row.key}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <ScorePill score={row.avg_score} />
                  </td>
                  <td className="px-4 py-3 text-right">
                    <ScorePill score={row.latest_score} />
                  </td>
                  <td className="px-[18px] py-3 text-right font-mono text-xs text-tertiary">
                    {fmtRelative(row.last_updated)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

function fmtRelative(iso: null | string): string {
  if (!iso) return '—'
  const ms =
    Date.now() - new Date(iso.endsWith('Z') ? iso : iso + 'Z').getTime()
  const min = Math.round(ms / 60000)
  if (min < 60) return `${min}m ago`
  const hr = Math.round(min / 60)
  if (hr < 24) return `${hr}h ago`
  return `${Math.round(hr / 24)}d ago`
}

function fmtScore(n: number): string {
  return n.toFixed(1)
}

function scoreBgColor(score: number): string {
  if (score >= 85) return 'var(--color-background-success)'
  if (score >= 70) return 'var(--color-background-warning)'
  return 'var(--color-background-danger)'
}

function scoreColor(score: number): string {
  if (score >= 85) return 'var(--color-text-success)'
  if (score >= 70) return 'var(--color-text-warning)'
  return 'var(--color-text-danger)'
}

function ScorePill({ score }: { score: number }) {
  return (
    <span
      className="inline-flex h-6 items-center rounded px-2 font-mono text-xs font-medium tabular-nums"
      style={{
        background: scoreBgColor(score),
        color: scoreColor(score),
      }}
    >
      {fmtScore(score)}
    </span>
  )
}

function StatCard({
  label,
  value,
  valueColor,
}: {
  label: string
  value: string
  valueColor?: string
}) {
  return (
    <div className="rounded-lg border border-tertiary bg-primary p-[18px]">
      <div className="text-overline uppercase tracking-wide text-tertiary">
        {label}
      </div>
      <div
        className="mt-2 font-mono text-[28px] tabular-nums leading-none"
        style={{ color: valueColor ?? 'var(--color-text-primary)' }}
      >
        {value}
      </div>
    </div>
  )
}

function TeamBarChart({ rows }: BarChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [W, setW] = useState(640)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const obs = new ResizeObserver(([entry]) => {
      const w = entry.contentRect.width
      if (w > 0) setW(Math.round(w))
    })
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  if (rows.length === 0) return null

  const BAR_H = 22
  const GAP = 10
  const PAD_TOP = 20
  const PAD_LEFT = 140
  const PAD_RIGHT = 60
  const PAD_BOTTOM = 32
  const innerW = W - PAD_LEFT - PAD_RIGHT

  const sorted = [...rows].sort((a, b) => b.avg_score - a.avg_score)
  const H = PAD_TOP + sorted.length * (BAR_H + GAP) - GAP + PAD_BOTTOM

  const xFor = (score: number) => (score / 100) * innerW

  const xTicks = [0, 25, 50, 75, 100]

  return (
    <div ref={containerRef} style={{ width: '100%' }}>
      <svg
        height={H}
        style={{ display: 'block', overflow: 'visible' }}
        width={W}
      >
        {/* x-axis grid lines */}
        {xTicks.map((t) => (
          <g key={t}>
            <line
              stroke="var(--color-border-tertiary)"
              strokeWidth="1"
              x1={PAD_LEFT + xFor(t)}
              x2={PAD_LEFT + xFor(t)}
              y1={PAD_TOP}
              y2={H - PAD_BOTTOM}
            />
            <text
              fill="var(--color-text-tertiary)"
              fontFamily="var(--font-sans)"
              fontSize="10"
              textAnchor="middle"
              x={PAD_LEFT + xFor(t)}
              y={H - PAD_BOTTOM + 14}
            >
              {t}
            </text>
          </g>
        ))}

        {sorted.map((row, i) => {
          const y = PAD_TOP + i * (BAR_H + GAP)
          const barW = Math.max(2, xFor(row.avg_score))
          const latestX = PAD_LEFT + xFor(row.latest_score)

          return (
            <g key={row.key}>
              {/* Team label */}
              <text
                fill="var(--color-text-primary)"
                fontFamily="var(--font-sans)"
                fontSize="12"
                textAnchor="end"
                x={PAD_LEFT - 8}
                y={y + BAR_H / 2 + 4}
              >
                {row.name.length > 18 ? row.name.slice(0, 17) + '…' : row.name}
              </text>

              {/* Avg score bar background */}
              <rect
                fill="var(--color-background-secondary)"
                height={BAR_H}
                rx="3"
                width={innerW}
                x={PAD_LEFT}
                y={y}
              />

              {/* Avg score bar fill */}
              <rect
                fill={scoreBgColor(row.avg_score)}
                height={BAR_H}
                rx="3"
                width={barW}
                x={PAD_LEFT}
                y={y}
              />

              {/* Latest score tick (max) */}
              <line
                stroke={scoreColor(row.latest_score)}
                strokeWidth="2"
                x1={latestX}
                x2={latestX}
                y1={y + 3}
                y2={y + BAR_H - 3}
              />

              {/* Score label */}
              <text
                fill={scoreColor(row.avg_score)}
                fontFamily="var(--font-mono)"
                fontSize="11"
                fontWeight="500"
                textAnchor="start"
                x={PAD_LEFT + barW + 6}
                y={y + BAR_H / 2 + 4}
              >
                {fmtScore(row.avg_score)}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
