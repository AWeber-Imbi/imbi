import { useEffect, useMemo, useRef, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import {
  LayoutTemplate,
  LucideProps,
  PencilLine,
  RefreshCw,
  Server,
  SlidersHorizontal,
} from 'lucide-react'

import {
  getScoreHistoryByTeam,
  getScoreHistoryFeed,
  GlobalScoreEvent,
  listTeams,
  ScoreChangeReason,
  TeamScoreSeries,
} from '@/api/endpoints'
import { useOrganization } from '@/contexts/OrganizationContext'
import { Team } from '@/types'

interface ChartSeries {
  color: string
  key: string
  name: string
  points: { score: number; timestamp: string }[]
}

type LucideIcon = React.FC<LucideProps>

type Range = '1y' | '30d' | '90d' | 'all'

interface SegmentedItem {
  key: string
  label: string
}

export function ScoreHistoryReport() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''

  const [range, setRange] = useState<Range>('1y')

  const rangeParams = useMemo(() => getRangeParams(range), [range])

  const { data: historyData, isLoading: historyLoading } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) =>
      getScoreHistoryByTeam({ granularity: 'day', ...rangeParams }, signal),
    queryKey: ['scoreHistoryByTeam', orgSlug, range],
    staleTime: 120_000,
  })

  const { data: feedData, isLoading: feedLoading } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) =>
      getScoreHistoryFeed({ ...rangeParams, limit: 200 }, signal),
    queryKey: ['scoreHistoryFeed', orgSlug, range],
    staleTime: 120_000,
  })

  const { data: teams, isLoading: teamsLoading } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listTeams(orgSlug, signal),
    queryKey: ['teams', orgSlug],
    staleTime: 120_000,
  })

  const isLoading = historyLoading || teamsLoading

  const teamBySlug = useMemo(
    () => new Map<string, Team>((teams ?? []).map((t) => [t.slug, t])),
    [teams],
  )

  const series: (TeamScoreSeries & { color: string; name: string })[] =
    useMemo(() => {
      const raw = historyData?.teams ?? []
      return raw.map((s, i) => ({
        ...s,
        color: TEAM_COLORS[i % TEAM_COLORS.length],
        name: teamBySlug.get(s.key)?.name ?? s.key,
      }))
    }, [historyData, teamBySlug])

  const rangeItems: SegmentedItem[] = [
    { key: '30d', label: '30d' },
    { key: '90d', label: '90d' },
    { key: '1y', label: '1y' },
    { key: 'all', label: 'All' },
  ]

  return (
    <div className="flex flex-col gap-5">
      {/* Chart card */}
      <div className="rounded-lg border border-tertiary bg-primary p-[18px]">
        <div className="mb-3.5 flex items-end justify-between gap-6">
          <div className="text-overline uppercase tracking-wide text-tertiary">
            Avg score by team
          </div>
          <Segmented
            items={rangeItems}
            onChange={(k) => setRange(k as Range)}
            value={range}
          />
        </div>

        {isLoading ? (
          <div className="flex h-56 items-center justify-center text-sm text-tertiary">
            Loading…
          </div>
        ) : series.length === 0 ? (
          <div className="flex h-56 items-center justify-center text-sm text-tertiary">
            No score data for this period.
          </div>
        ) : (
          <MultiLineChart series={series} />
        )}
      </div>

      {/* Feed card */}
      <div className="rounded-lg border border-tertiary bg-primary">
        <div className="border-b border-tertiary px-[18px] py-3.5">
          <div className="text-overline uppercase tracking-wide text-tertiary">
            Change events
          </div>
          <div className="mt-0.5 text-xs text-tertiary">
            Recent score recomputations across all projects, newest first.
          </div>
        </div>
        <div>
          {feedLoading ? (
            <div className="py-10 text-center text-sm text-tertiary">
              Loading…
            </div>
          ) : (
            <GlobalEventFeed events={feedData ?? []} teamBySlug={teamBySlug} />
          )}
        </div>
      </div>
    </div>
  )
}

function DeltaBadge({ delta }: { delta: number }) {
  const positive = delta > 0
  const zero = delta === 0
  const bg = zero
    ? 'var(--color-background-secondary)'
    : positive
      ? 'var(--color-background-success)'
      : 'var(--color-background-danger)'
  const color = zero
    ? 'var(--color-text-secondary)'
    : positive
      ? 'var(--color-text-success)'
      : 'var(--color-text-danger)'
  return (
    <span
      className="inline-flex h-6 items-center rounded px-2 font-mono text-xs font-medium tabular-nums"
      style={{ background: bg, color }}
    >
      {positive ? '+' : ''}
      {Math.round(delta)}
    </span>
  )
}

function fmtDate(iso: string): string {
  const d = new Date(toUtc(iso))
  return d.toLocaleString('en-US', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

function fmtISODate(iso: string): string {
  const d = new Date(toUtc(iso))
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function fmtRel(iso: string): string {
  const ms = Date.now() - new Date(toUtc(iso)).getTime()
  const min = Math.round(ms / 60000)
  if (min < 60) return `${min}m ago`
  const hr = Math.round(min / 60)
  if (hr < 24) return `${hr}h ago`
  const dy = Math.round(hr / 24)
  if (dy < 30) return `${dy}d ago`
  return `${Math.round(dy / 30)}mo ago`
}

function getRangeParams(range: Range): { from?: string; to?: string } {
  if (range === 'all') return {}
  const days = range === '30d' ? 30 : range === '90d' ? 90 : 365
  const from = new Date()
  from.setDate(from.getDate() - days)
  return { from: from.toISOString() }
}

function GlobalEventFeed({
  events,
  teamBySlug,
}: {
  events: GlobalScoreEvent[]
  teamBySlug: Map<string, Team>
}) {
  if (events.length === 0) {
    return (
      <div className="py-10 text-center text-sm text-tertiary">
        No change events for this period.
      </div>
    )
  }
  return (
    <div>
      {events.map((e, i) => {
        const reason = e.change_reason ?? ''
        const delta =
          e.previous_score != null ? e.score - e.previous_score : null
        const teamName = teamBySlug.get(e.team_key)?.name ?? e.team_key
        return (
          <div
            className="grid items-center gap-3 border-b border-tertiary px-3 py-3 transition-colors duration-fast last:border-0 hover:bg-secondary"
            key={i}
            style={{ gridTemplateColumns: '80px 1fr auto 72px' }}
          >
            {/* Timestamp */}
            <div>
              <div className="text-xs font-medium text-primary">
                {fmtRel(e.timestamp)}
              </div>
              <div className="mt-0.5 font-mono text-[11px] text-tertiary">
                {fmtISODate(e.timestamp)}
              </div>
            </div>

            {/* Project + reason */}
            <div className="min-w-0">
              <div className="mb-1 flex flex-wrap items-center gap-1.5">
                <ReasonChip reason={reason} />
                <span className="max-w-[200px] truncate text-[12px] font-medium text-primary">
                  {e.project_name}
                </span>
                <span className="text-[11px] text-tertiary">{teamName}</span>
              </div>
            </div>

            {/* Score */}
            <div className="flex items-center justify-end gap-1.5 font-mono tabular-nums">
              {e.previous_score != null && (
                <span className="text-xs text-tertiary">
                  {Math.round(e.previous_score)}
                  {' → '}
                </span>
              )}
              <span className="text-sm font-semibold text-primary">
                {Math.round(e.score)}
              </span>
            </div>
            {/* Delta */}
            <div className="flex items-center justify-end">
              {delta != null && <DeltaBadge delta={delta} />}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function MultiLineChart({ series }: { series: ChartSeries[] }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [W, setW] = useState(720)
  const [hoveredTsIdx, setHoveredTsIdx] = useState<null | number>(null)

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

  const H = 260
  const padL = 40
  const padR = 16
  const padT = 14
  const padB = 28
  const innerW = W - padL - padR
  const innerH = H - padT - padB

  const allTimestamps = useMemo(() => {
    const tsSet = new Set<string>()
    for (const s of series) {
      for (const pt of s.points) tsSet.add(pt.timestamp)
    }
    return [...tsSet].sort()
  }, [series])

  const minTsMs = useMemo(
    () =>
      allTimestamps.length > 0
        ? new Date(toUtc(allTimestamps[0])).getTime()
        : 0,
    [allTimestamps],
  )
  const maxTsMs = useMemo(
    () =>
      allTimestamps.length > 0
        ? new Date(toUtc(allTimestamps[allTimestamps.length - 1])).getTime()
        : 1,
    [allTimestamps],
  )
  const tsRangeMs = maxTsMs - minTsMs || 1

  const xForTs = (ts: string) => {
    const t = new Date(toUtc(ts)).getTime()
    return padL + ((t - minTsMs) / tsRangeMs) * innerW
  }

  const allScores = series.flatMap((s) => s.points.map((p) => p.score))
  const rawMin = allScores.length > 0 ? Math.min(...allScores) : 0
  const yMin = Math.max(0, Math.floor(rawMin / 10) * 10 - 10)
  const yMax = 100
  const yRange = yMax - yMin || 1

  const yFor = (score: number) => padT + (1 - (score - yMin) / yRange) * innerH

  const yTicks = Array.from(
    { length: Math.floor((yMax - yMin) / 10) + 1 },
    (_, i) => yMin + i * 10,
  )

  const xTickIndices =
    allTimestamps.length <= 6
      ? allTimestamps.map((_, i) => i)
      : [0, 1, 2, 3, 4, 5].map((n) =>
          Math.round((n * (allTimestamps.length - 1)) / 5),
        )

  // Carry-forward: each series line is continuous — gaps use last known score.
  // The pen only lifts before the series has any data at all.
  const seriesPaths = useMemo(
    () =>
      series.map((s) => {
        const ptMap = new Map(s.points.map((p) => [p.timestamp, p.score]))
        let d = ''
        let lastScore: null | number = null
        let pen: 'down' | 'up' = 'up'
        for (const ts of allTimestamps) {
          const score = ptMap.get(ts)
          if (score != null) lastScore = score
          if (lastScore == null) continue
          const x = xForTs(ts).toFixed(1)
          const y = yFor(lastScore).toFixed(1)
          d += pen === 'up' ? `M${x},${y}` : `L${x},${y}`
          pen = 'down'
        }
        return d
      }),
    // xForTs and yFor are derived from the other deps listed here
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      series,
      allTimestamps,
      minTsMs,
      tsRangeMs,
      padL,
      innerW,
      yMin,
      yRange,
      padT,
      innerH,
    ],
  )

  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const mouseX = e.clientX - rect.left
    if (allTimestamps.length === 0) return
    let bestI = 0
    let bestDist = Infinity
    for (let i = 0; i < allTimestamps.length; i++) {
      const dist = Math.abs(xForTs(allTimestamps[i]) - mouseX)
      if (dist < bestDist) {
        bestDist = dist
        bestI = i
      }
    }
    setHoveredTsIdx(bestI)
  }

  const hoveredTs = hoveredTsIdx != null ? allTimestamps[hoveredTsIdx] : null
  const hoveredX = hoveredTs != null ? xForTs(hoveredTs) : null

  // For hover dots, use carry-forward value so dots appear even in gap buckets
  const hoveredValues = useMemo(() => {
    if (hoveredTs == null) return []
    return series.map((s) => {
      const ptMap = new Map(s.points.map((p) => [p.timestamp, p.score]))
      let lastScore: null | number = null
      for (const ts of allTimestamps) {
        const score = ptMap.get(ts)
        if (score != null) lastScore = score
        if (ts === hoveredTs) break
      }
      return { color: s.color, name: s.name, score: lastScore }
    })
  }, [hoveredTs, series, allTimestamps])

  const hoveredScores = hoveredValues.filter(
    (v): v is { color: string; name: string; score: number } => v.score != null,
  )

  if (allTimestamps.length === 0) {
    return (
      <div className="flex h-56 items-center justify-center text-sm text-tertiary">
        No score data for this period.
      </div>
    )
  }

  const tipLineH = 16
  const tipPad = 12
  const tipW = 180
  const tipH = tipPad * 2 + 18 + hoveredScores.length * tipLineH
  const tipX =
    hoveredX != null && hoveredX + tipW + 16 > W - padR
      ? (hoveredX ?? 0) - tipW - 8
      : (hoveredX ?? 0) + 12
  const tipY = padT + 4

  return (
    <div ref={containerRef} style={{ width: '100%' }}>
      <svg
        height={H}
        onMouseLeave={() => setHoveredTsIdx(null)}
        onMouseMove={handleMouseMove}
        style={{ cursor: 'crosshair', display: 'block', overflow: 'visible' }}
        width={W}
      >
        {/* y-axis grid */}
        {yTicks.map((t) => (
          <g key={t}>
            <line
              stroke="var(--color-border-tertiary)"
              strokeWidth="1"
              x1={padL}
              x2={W - padR}
              y1={yFor(t)}
              y2={yFor(t)}
            />
            <text
              fill="var(--color-text-tertiary)"
              fontFamily="var(--font-sans)"
              fontSize="11"
              textAnchor="end"
              x={padL - 4}
              y={yFor(t) + 4}
            >
              {t}
            </text>
          </g>
        ))}

        {/* x-axis labels */}
        {xTickIndices.map((i) => (
          <text
            fill="var(--color-text-tertiary)"
            fontFamily="var(--font-sans)"
            fontSize="11"
            key={i}
            textAnchor="middle"
            x={xForTs(allTimestamps[i])}
            y={H - 6}
          >
            {fmtDate(allTimestamps[i])}
          </text>
        ))}

        {/* Series lines */}
        {seriesPaths.map((d, i) => (
          <path
            d={d}
            fill="none"
            key={series[i].key}
            stroke={series[i].color}
            strokeWidth="1.5"
          />
        ))}

        {/* Hover crosshair */}
        {hoveredX != null && (
          <line
            pointerEvents="none"
            stroke="var(--color-border-secondary)"
            strokeWidth="1"
            x1={hoveredX}
            x2={hoveredX}
            y1={padT}
            y2={padT + innerH}
          />
        )}

        {/* Hover dots */}
        {hoveredTs != null &&
          hoveredValues.map((v) => {
            if (v.score == null) return null
            return (
              <circle
                cx={hoveredX!}
                cy={yFor(v.score)}
                fill="var(--color-background-primary)"
                key={v.name}
                pointerEvents="none"
                r={4}
                stroke={v.color}
                strokeWidth="1.5"
              />
            )
          })}

        {/* Hover tooltip */}
        {hoveredTs != null && hoveredScores.length > 0 && (
          <g pointerEvents="none">
            <rect
              fill="var(--color-background-primary)"
              filter="drop-shadow(0 4px 10px rgba(26,26,24,0.10))"
              height={tipH}
              rx="6"
              stroke="var(--color-border-secondary)"
              width={tipW}
              x={tipX}
              y={tipY}
            />
            <text
              fill="var(--color-text-tertiary)"
              fontFamily="var(--font-sans)"
              fontSize="10"
              fontWeight="500"
              letterSpacing="0.06em"
              x={tipX + tipPad}
              y={tipY + tipPad + 6}
            >
              {fmtDate(hoveredTs).toUpperCase()}
            </text>
            {hoveredScores.map((hs, i) => (
              <g key={hs.name}>
                <circle
                  cx={tipX + tipPad + 4}
                  cy={tipY + tipPad + 20 + i * tipLineH + 3}
                  fill={hs.color}
                  r={3.5}
                />
                <text
                  fill="var(--color-text-secondary)"
                  fontFamily="var(--font-sans)"
                  fontSize="11"
                  x={tipX + tipPad + 14}
                  y={tipY + tipPad + 20 + i * tipLineH + 7}
                >
                  {hs.name.length > 16 ? hs.name.slice(0, 15) + '…' : hs.name}
                </text>
                <text
                  fill="var(--color-text-primary)"
                  fontFamily="var(--font-mono)"
                  fontSize="11"
                  fontWeight="600"
                  textAnchor="end"
                  x={tipX + tipW - tipPad}
                  y={tipY + tipPad + 20 + i * tipLineH + 7}
                >
                  {hs.score.toFixed(1)}
                </text>
              </g>
            ))}
          </g>
        )}
      </svg>

      {/* Legend */}
      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-tertiary pt-3">
        {series.map((s) => (
          <span
            className="inline-flex items-center gap-1.5 text-xs"
            key={s.key}
          >
            <span
              className="inline-block h-[3px] w-5 rounded-full"
              style={{ background: s.color }}
            />
            <span className="text-secondary">{s.name}</span>
          </span>
        ))}
      </div>
    </div>
  )
}

function ReasonChip({ reason }: { reason: string }) {
  const meta = REASON_META[reason as ScoreChangeReason]
  if (meta) {
    const { Icon } = meta
    return (
      <span
        className={`inline-flex h-5 items-center gap-1 rounded px-1.5 text-[11px] font-medium ${meta.bgClass} ${meta.textClass}`}
      >
        <Icon size={10} />
        {meta.label}
      </span>
    )
  }
  if (reason.includes('@')) {
    const { Icon } = REASON_META.attribute_change
    const username = reason.split('@')[0]
    return (
      <span
        className={`inline-flex h-5 items-center gap-1 rounded px-1.5 text-[11px] font-medium ${REASON_META.attribute_change.bgClass} ${REASON_META.attribute_change.textClass}`}
        title={reason}
      >
        <Icon size={10} />
        {username}
      </span>
    )
  }
  return (
    <span className="inline-flex h-5 items-center rounded bg-secondary px-1.5 text-[11px] font-medium text-secondary">
      {reason.charAt(0).toUpperCase() + reason.slice(1)}
    </span>
  )
}

function Segmented({
  items,
  onChange,
  value,
}: {
  items: SegmentedItem[]
  onChange: (k: string) => void
  value: string
}) {
  return (
    <div className="inline-flex gap-0.5 rounded-md border border-tertiary bg-primary p-0.5">
      {items.map((it) => (
        <button
          className={`inline-flex h-6 items-center rounded px-2.5 text-xs transition-colors duration-fast ${
            value === it.key
              ? 'bg-secondary font-medium text-primary'
              : 'text-secondary hover:text-primary'
          }`}
          key={it.key}
          onClick={() => onChange(it.key)}
        >
          {it.label}
        </button>
      ))}
    </div>
  )
}

function toUtc(iso: string): string {
  return /[Z+]|\d{2}:\d{2}$/.test(iso) ? iso : iso + 'Z'
}

const REASON_META: Record<
  ScoreChangeReason,
  {
    bgClass: string
    dot: string
    Icon: LucideIcon
    label: string
    textClass: string
  }
> = {
  attribute_change: {
    bgClass: 'bg-info',
    dot: '#3d86d1',
    Icon: PencilLine,
    label: 'Attribute',
    textClass: 'text-info',
  },
  blueprint_change: {
    bgClass: 'bg-accent',
    dot: '#7f77dd',
    Icon: LayoutTemplate,
    label: 'Blueprint',
    textClass: 'text-accent',
  },
  bulk_rescore: {
    bgClass: 'bg-secondary',
    dot: '#888780',
    Icon: RefreshCw,
    label: 'Rescore',
    textClass: 'text-secondary',
  },
  policy_change: {
    bgClass: 'bg-warning',
    dot: '#ef9f27',
    Icon: SlidersHorizontal,
    label: 'Policy',
    textClass: 'text-warning',
  },
  system: {
    bgClass: 'bg-secondary',
    dot: '#aaa9a5',
    Icon: Server,
    label: 'System',
    textClass: 'text-secondary',
  },
}

const TEAM_COLORS = [
  '#4e79a7',
  '#e15759',
  '#76b7b2',
  '#59a14f',
  '#b07aa1',
  '#f28e2b',
  '#ff9da7',
  '#9c755f',
  '#4bc6d8',
  '#a0b37e',
]
