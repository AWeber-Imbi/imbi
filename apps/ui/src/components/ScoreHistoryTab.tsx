import { useEffect, useMemo, useRef, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import {
  ArrowRight,
  Download,
  Filter,
  LayoutTemplate,
  LucideProps,
  PencilLine,
  RefreshCw,
  Server,
  SlidersHorizontal,
} from 'lucide-react'

import {
  EventRecord,
  getScoreHistory,
  getScoreTrend,
  listProjectEvents,
  ScoreChangeReason,
  ScoreHistoryPoint,
} from '@/api/endpoints'
import { formatFieldKey } from '@/lib/project-field-formatting'

type Granularity = 'day' | 'hour' | 'raw'
type LucideIcon = React.FC<LucideProps>

interface Props {
  orgSlug: string
  projectId: string
}

type Range = '1y' | '30d' | '90d' | 'all'

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

interface ChartProps {
  annotations: Map<number, ScoreChangeReason>
  eventCorrelations: Map<number, ProjectChangePayload>
  hoveredIdx: null | number
  points: ScoreHistoryPoint[]
  setHoveredIdx: (i: null | number) => void
}

interface EventTimelineProps {
  eventCorrelations: Map<number, ProjectChangePayload>
  events: ScoreHistoryPoint[]
  hoveredIdx: null | number
  setHoveredIdx: (i: null | number) => void
}

interface ProjectChangePayload {
  field: string
  new: unknown
  old: unknown
}

interface SegmentedItem {
  key: string
  label: string
}

// ---------- Segmented control ----------

export function ScoreHistoryTab({ orgSlug, projectId }: Props) {
  const [range, setRange] = useState<Range>('1y')
  const [granularity, setGranularity] = useState<Granularity>('day')
  const [hoveredChart, setHoveredChart] = useState<null | number>(null)
  const [hoveredEvent, setHoveredEvent] = useState<null | number>(null)

  const rangeParams = useMemo(() => getRangeParams(range), [range])

  const { data: chartData, isLoading: chartLoading } = useQuery({
    enabled: !!orgSlug && !!projectId,
    queryFn: ({ signal }) =>
      getScoreHistory(
        orgSlug,
        projectId,
        { granularity, ...rangeParams },
        signal,
      ),
    queryKey: ['scoreHistory', orgSlug, projectId, granularity, range],
  })

  const { data: rawData, isLoading: rawLoading } = useQuery({
    // When granularity is already 'raw', chartData IS the raw data — skip the duplicate request.
    enabled: !!orgSlug && !!projectId && granularity !== 'raw',
    queryFn: ({ signal }) =>
      getScoreHistory(
        orgSlug,
        projectId,
        { granularity: 'raw', ...rangeParams },
        signal,
      ),
    queryKey: ['scoreHistoryRaw', orgSlug, projectId, range],
  })

  const { data: trendData } = useQuery({
    enabled: !!orgSlug && !!projectId,
    queryFn: ({ signal }) => getScoreTrend(orgSlug, projectId, 90, signal),
    queryKey: ['scoreTrend90', orgSlug, projectId],
  })

  const { data: projectEventsPage } = useQuery({
    enabled: !!orgSlug && !!projectId,
    queryFn: ({ signal }) =>
      listProjectEvents(
        { limit: 500, orgSlug, projectId, type: 'project-change' },
        signal,
      ),
    queryKey: ['projectEvents', orgSlug, projectId, 'project-change'],
    staleTime: 30_000,
  })
  const projectChangeEvents = useMemo(
    () => projectEventsPage?.entries ?? [],
    [projectEventsPage],
  )

  const chartPoints = useMemo(() => {
    const pts = chartData?.points ?? []
    if (pts.length === 0) return pts
    const last = pts[pts.length - 1]
    const now = new Date()
    const lastMs = new Date(toUtc(last.timestamp)).getTime()
    // Only append if the last point is more than a minute old
    if (now.getTime() - lastMs > 60_000) {
      return [
        ...pts,
        { ...last, change_reason: null, timestamp: now.toISOString() },
      ]
    }
    return pts
  }, [chartData])
  const rawEvents = useMemo(
    () =>
      ((granularity === 'raw' ? chartData?.points : rawData?.points) ?? [])
        .filter((p) => p.change_reason != null)
        .reverse(),
    [chartData, granularity, rawData],
  )

  // chart index → change_reason
  // Raw granularity: change_reason is on each chart point directly.
  // Day/hour granularity: the SQL aggregation drops change_reason, so map
  // raw events to the nearest chart bucket by timestamp instead.
  const chartAnnotations = useMemo((): Map<number, ScoreChangeReason> => {
    const m = new Map<number, ScoreChangeReason>()
    if (granularity === 'raw') {
      chartPoints.forEach((p, i) => {
        if (p.change_reason != null) m.set(i, p.change_reason)
      })
    } else {
      rawEvents.forEach((e) => {
        if (e.change_reason == null) return
        const i = nearestChartPointIndex(
          new Date(toUtc(e.timestamp)).getTime(),
          chartPoints,
        )
        if (!m.has(i)) m.set(i, e.change_reason)
      })
    }
    return m
  }, [chartPoints, granularity, rawEvents])

  // For annotation hover sync: map raw event index → nearest chart point index by timestamp
  const syncedChartHover = useMemo(() => {
    if (
      hoveredEvent == null ||
      rawEvents.length === 0 ||
      chartPoints.length === 0
    )
      return null
    return nearestChartPointIndex(
      new Date(toUtc(rawEvents[hoveredEvent].timestamp)).getTime(),
      chartPoints,
    )
  }, [hoveredEvent, rawEvents, chartPoints])

  // correlate score events → project-change events by timestamp proximity.
  // The score recomputation is debounced ~5s after the attribute change, so
  // we look for the nearest project-change event in the 90s window before
  // each score event.
  const eventCorrelations = useMemo((): Map<number, ProjectChangePayload> => {
    return buildCorrelations(rawEvents, projectChangeEvents)
  }, [rawEvents, projectChangeEvents])

  // For the chart tooltip: same correlation keyed by chart point index.
  const chartEventCorrelations = useMemo((): Map<
    number,
    ProjectChangePayload
  > => {
    const m = new Map<number, ProjectChangePayload>()
    chartAnnotations.forEach((reason, idx) => {
      if (!isAttributeReason(reason)) return
      const pt = chartPoints[idx]
      if (!pt) return
      // The backend stores user email addresses as the change_reason for attribute edits,
      // so `reason` may be an email string even though ScoreChangeReason only lists known
      // enum values. Pass it as the actor filter when it looks like an email.
      const actor = reason.includes('@') ? reason : undefined
      const payload = nearestProjectChange(
        pt.timestamp,
        projectChangeEvents,
        actor,
      )
      if (payload) m.set(idx, payload)
    })
    return m
  }, [chartAnnotations, chartPoints, projectChangeEvents])

  const currentScore =
    trendData?.current ?? chartPoints[chartPoints.length - 1]?.score ?? null

  const rangeItems: SegmentedItem[] = [
    { key: '30d', label: '30d' },
    { key: '90d', label: '90d' },
    { key: '1y', label: '1y' },
    { key: 'all', label: 'All' },
  ]

  const granularityItems: SegmentedItem[] = [
    { key: 'raw', label: 'Raw' },
    { key: 'hour', label: 'Hour' },
    { key: 'day', label: 'Day' },
  ]

  return (
    <div className="flex flex-col gap-5">
      {/* Chart card */}
      <div className="border-tertiary bg-primary rounded-lg border p-[18px]">
        <div className="mb-3.5 flex items-end justify-between gap-6">
          <div className="flex items-baseline gap-1">
            <div className="text-primary font-mono text-[36px] leading-none font-semibold tabular-nums">
              {currentScore != null ? Math.round(currentScore) : '—'}
            </div>
            <div className="text-tertiary text-sm">/ 100</div>
          </div>
          <div className="flex gap-2">
            <Segmented
              items={rangeItems}
              onChange={(k) => setRange(k as Range)}
              value={range}
            />
            <Segmented
              items={granularityItems}
              onChange={(k) => setGranularity(k as Granularity)}
              value={granularity}
            />
          </div>
        </div>

        {chartLoading ? (
          <div className="text-tertiary flex h-40 items-center justify-center text-sm">
            Loading…
          </div>
        ) : (
          <ScoreChart
            annotations={chartAnnotations}
            eventCorrelations={chartEventCorrelations}
            hoveredIdx={hoveredChart ?? syncedChartHover}
            points={chartPoints}
            setHoveredIdx={setHoveredChart}
          />
        )}

        {/* Legend */}
        <div className="border-tertiary text-tertiary mt-2 flex flex-wrap items-center gap-4 border-t pt-2.5 text-sm">
          <span className="text-secondary font-medium">Annotations</span>
          {Object.entries(REASON_META).map(([key, meta]) => (
            <span className="inline-flex items-center gap-1.5" key={key}>
              <span
                className="inline-block size-2 rounded-xs"
                style={{ background: meta.dot }}
              />
              {meta.label}
            </span>
          ))}
        </div>
      </div>

      {/* Change events card */}
      <div className="border-tertiary bg-primary overflow-hidden rounded-lg border">
        <div className="border-tertiary flex items-center justify-between border-b px-[18px] py-3.5">
          <div>
            <div className="text-overline text-tertiary tracking-wide uppercase">
              Change events
            </div>
            <div className="text-tertiary mt-0.5 text-xs">
              Every recomputation that moved the score, newest first.
            </div>
          </div>
          <div className="flex gap-2">
            <button className="text-secondary hover:bg-secondary hover:text-primary inline-flex h-7 items-center gap-1.5 rounded px-2.5 text-xs transition-colors">
              <Filter size={12} />
              All reasons
            </button>
            <button className="border-tertiary text-primary hover:bg-secondary inline-flex h-7 items-center gap-1.5 rounded border px-2.5 text-xs transition-colors">
              <Download size={12} />
              Export CSV
            </button>
          </div>
        </div>
        <div>
          {rawLoading ? (
            <div className="text-tertiary py-10 text-center text-sm">
              Loading…
            </div>
          ) : (
            <EventTimeline
              eventCorrelations={eventCorrelations}
              events={rawEvents}
              hoveredIdx={hoveredEvent}
              setHoveredIdx={setHoveredEvent}
            />
          )}
        </div>
      </div>
    </div>
  )
}

// ---------- Helpers (alphabetical) ----------

function buildCorrelations(
  rawEvents: ScoreHistoryPoint[],
  projectChangeEvents: EventRecord[],
): Map<number, ProjectChangePayload> {
  const m = new Map<number, ProjectChangePayload>()
  rawEvents.forEach((e, i) => {
    if (!isAttributeReason(e.change_reason ?? '')) return
    // If reason is an email address, pass it as the preferred attributed_to
    const actor = e.change_reason?.includes('@') ? e.change_reason : undefined
    const payload = nearestProjectChange(
      e.timestamp,
      projectChangeEvents,
      actor,
    )
    if (payload) m.set(i, payload)
  })
  return m
}

function EventTimeline({
  eventCorrelations,
  events,
  hoveredIdx,
  setHoveredIdx,
}: EventTimelineProps) {
  if (events.length === 0) {
    return (
      <div className="text-tertiary py-10 text-center text-sm">
        No change events for this period.
      </div>
    )
  }
  return (
    <div>
      {events.map((e, i) => {
        const reason = e.change_reason!
        const delta =
          e.previous_score != null ? e.score - e.previous_score : null
        const isHov = hoveredIdx === i
        const correlated = eventCorrelations.get(i)
        return (
          <div
            className={`border-tertiary duration-fast grid items-center gap-3 border-b px-3 py-3.5 transition-colors last:border-0 ${
              isHov ? 'bg-secondary' : ''
            }`}
            key={i}
            onMouseEnter={() => setHoveredIdx(i)}
            onMouseLeave={() => setHoveredIdx(null)}
            style={{
              cursor: 'default',
              gridTemplateColumns: '80px 1fr auto 72px',
            }}
          >
            <div>
              <div className="text-primary text-xs font-medium">
                {fmtRel(e.timestamp)}
              </div>
              <div className="text-tertiary mt-0.5 font-mono text-[11px]">
                {fmtISODate(e.timestamp)}
              </div>
            </div>
            <div>
              <div className="mb-1 flex items-center gap-2">
                <ReasonChip reason={reason} />
              </div>
              {correlated ? (
                <div className="text-tertiary text-[12px]">
                  <span className="text-secondary font-medium">
                    {formatFieldKey(correlated.field)}
                  </span>
                  {correlated.old != null && String(correlated.old) !== '' && (
                    <span className="ml-1 font-mono">
                      <span className="bg-secondary rounded px-1 py-0.5">
                        {String(correlated.old)}
                      </span>
                      {' → '}
                      <span className="bg-secondary rounded px-1 py-0.5">
                        {String(correlated.new)}
                      </span>
                    </span>
                  )}
                  {(correlated.old == null ||
                    String(correlated.old) === '') && (
                    <span className="ml-1 font-mono">
                      {'set to '}
                      <span className="bg-secondary rounded px-1 py-0.5">
                        {String(correlated.new)}
                      </span>
                    </span>
                  )}
                </div>
              ) : (
                <div className="text-tertiary font-mono text-[12px]">
                  score recomputed
                </div>
              )}
            </div>
            <div className="flex items-center justify-end gap-1.5 font-mono tabular-nums">
              {e.previous_score != null && (
                <>
                  <span className="text-tertiary text-xs">
                    {Math.round(e.previous_score)}
                  </span>
                  <ArrowRight className="text-tertiary" size={11} />
                </>
              )}
              <span className="text-primary text-sm font-semibold">
                {Math.round(e.score)}
              </span>
            </div>
            <div className="flex items-center justify-end">
              {delta != null && <DeltaBadge delta={delta} />}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function fmtDate(iso: string, withTime = false): string {
  const d = new Date(toUtc(iso))
  if (withTime) {
    return d.toLocaleString('en-US', {
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      month: 'short',
    })
  }
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

function isAttributeReason(reason: string): boolean {
  return !NON_ATTRIBUTE_REASONS.has(reason)
}

function nearestChartPointIndex(
  timestampMs: number,
  pts: ScoreHistoryPoint[],
): number {
  let bestI = 0
  let bestDiff = Infinity
  pts.forEach((p, i) => {
    const d = Math.abs(new Date(toUtc(p.timestamp)).getTime() - timestampMs)
    if (d < bestDiff) {
      bestDiff = d
      bestI = i
    }
  })
  return bestI
}

function nearestProjectChange(
  scoreTimestamp: string,
  events: EventRecord[],
  attributedTo?: string,
): null | ProjectChangePayload {
  const scoreMs = new Date(toUtc(scoreTimestamp)).getTime()
  let best: null | ProjectChangePayload = null
  let bestDiff = 90_000 // 90s look-back window
  for (const e of events) {
    const peMs = new Date(toUtc(e.recorded_at)).getTime()
    const diff = scoreMs - peMs
    if (diff >= 0 && diff < bestDiff) {
      // If reason is a user email, prefer events attributed to that same user
      if (attributedTo && e.attributed_to !== attributedTo) continue
      const p = e.payload
      if (typeof p.field === 'string') {
        bestDiff = diff
        best = p as unknown as ProjectChangePayload
      }
    }
  }
  return best
}

// Ensure bare ISO strings (no tz offset) are treated as UTC
function toUtc(iso: string): string {
  return /[Z+]|\d{2}:\d{2}$/.test(iso) ? iso : iso + 'Z'
}

// Reasons that represent bulk/policy operations — correlating these with a
// specific attribute change would produce false positives.
const NON_ATTRIBUTE_REASONS = new Set([
  'blueprint_change',
  'bulk_rescore',
  'migration_backfill',
  'policy_change',
  'system',
])

// ---------- Event timeline ----------

function DeltaBadge({ delta }: { delta: number }) {
  const positive = delta > 0
  const zero = delta === 0
  const bg = zero
    ? 'var(--background-color-secondary)'
    : positive
      ? 'var(--background-color-success)'
      : 'var(--background-color-danger)'
  const color = zero
    ? 'var(--text-color-secondary)'
    : positive
      ? 'var(--text-color-success)'
      : 'var(--text-color-danger)'
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
  // User email → show as an Attribute chip with the username portion
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
  // Service name (sonarqube, github, etc.) → capitalise
  return (
    <span className="bg-secondary text-secondary inline-flex h-5 items-center rounded px-1.5 text-[11px] font-medium">
      {reason.charAt(0).toUpperCase() + reason.slice(1)}
    </span>
  )
}

// ---------- Delta badge ----------

function ScoreChart({
  annotations,
  eventCorrelations,
  hoveredIdx,
  points,
  setHoveredIdx,
}: ChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [W, setW] = useState(720)

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

  const H = 220
  const padL = 40
  const padR = 14
  const padT = 14
  const padB = 28
  const innerW = W - padL - padR
  const innerH = H - padT - padB

  const yMin = 50
  const yMax = 100

  const xFor = (i: number) =>
    padL + (i / Math.max(points.length - 1, 1)) * innerW
  const yFor = (s: number) => padT + (1 - (s - yMin) / (yMax - yMin)) * innerH

  const pathD = points
    .map(
      (p, i) =>
        `${i === 0 ? 'M' : 'L'}${xFor(i).toFixed(1)},${yFor(p.score).toFixed(1)}`,
    )
    .join(' ')
  const areaD =
    points.length < 2
      ? ''
      : `${pathD} L${xFor(points.length - 1).toFixed(1)},${(padT + innerH).toFixed(1)} L${padL},${(padT + innerH).toFixed(1)} Z`

  // Annotation markers: chart indices that have a mapped raw event
  const annotated = Array.from(annotations.entries()).map(([idx, reason]) => ({
    idx,
    reason,
  }))

  const yTicks = [50, 60, 70, 80, 90, 100]

  // 6 evenly spaced x-axis labels
  const xTickIndices =
    points.length <= 6
      ? points.map((_, i) => i)
      : [0, 1, 2, 3, 4, 5].map((n) => Math.round((n * (points.length - 1)) / 5))

  if (points.length === 0) {
    return (
      <div className="text-tertiary flex h-40 items-center justify-center text-sm">
        No score data for this period.
      </div>
    )
  }

  return (
    <div ref={containerRef} style={{ width: '100%' }}>
      <svg
        height={H}
        style={{ display: 'block', overflow: 'visible' }}
        width={W}
      >
        <defs>
          <linearGradient id="sh-area-grad" x1="0" x2="0" y1="0" y2="1">
            <stop
              offset="0%"
              stopColor="var(--background-color-action)"
              stopOpacity="0.18"
            />
            <stop
              offset="100%"
              stopColor="var(--background-color-action)"
              stopOpacity="0"
            />
          </linearGradient>
        </defs>

        {/* y-axis grid */}
        {yTicks.map((t) => (
          <g key={t}>
            <line
              stroke="var(--border-color-tertiary)"
              strokeWidth="1"
              x1={padL}
              x2={W - padR}
              y1={yFor(t)}
              y2={yFor(t)}
            />
            <text
              fill="var(--text-color-tertiary)"
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
            fill="var(--text-color-tertiary)"
            fontFamily="var(--font-sans)"
            fontSize="11"
            key={i}
            textAnchor="middle"
            x={xFor(i)}
            y={H - 6}
          >
            {fmtDate(points[i].timestamp)}
          </text>
        ))}

        {/* area fill + line */}
        {areaD && <path d={areaD} fill="url(#sh-area-grad)" />}
        <path
          d={pathD}
          fill="none"
          stroke="var(--background-color-action)"
          strokeWidth="1"
        />

        {/* annotation verticals */}
        {annotated.map(({ idx, reason }) => {
          const meta = REASON_META[reason]
          if (!meta) return null
          const isHov = hoveredIdx === idx
          const x = xFor(idx)
          const y = yFor(points[idx].score)
          return (
            <g
              key={idx}
              onMouseEnter={() => setHoveredIdx(idx)}
              onMouseLeave={() => setHoveredIdx(null)}
              style={{ cursor: 'pointer' }}
            >
              <line
                opacity={isHov ? 0.85 : 0.45}
                stroke={meta.dot}
                strokeDasharray="3 3"
                strokeWidth={isHov ? 1.5 : 1}
                x1={x}
                x2={x}
                y1={padT}
                y2={padT + innerH}
              />
              <rect
                fill="transparent"
                height={innerH}
                width="16"
                x={x - 8}
                y={padT}
              />
              <circle
                cx={x}
                cy={y}
                fill="var(--background-color-primary)"
                r={isHov ? 5 : 3.5}
                stroke={meta.dot}
                strokeWidth="1.5"
              />
            </g>
          )
        })}

        {/* hover tooltip */}
        {hoveredIdx != null &&
          (() => {
            const entry = annotated.find((a) => a.idx === hoveredIdx)
            if (!entry) return null
            const reason = entry.reason
            const meta = REASON_META[reason]
            if (!meta) return null
            const point = points[entry.idx]
            const x = xFor(entry.idx)
            const y = yFor(point.score)
            const correlated = eventCorrelations.get(entry.idx)
            const tipW = 220
            const hasDetail = !!correlated
            const tipH = hasDetail ? 86 : 68
            const flip = x + tipW + 12 > W - padR
            const tx = flip ? x - tipW - 12 : x + 12
            const ty = Math.max(
              padT,
              Math.min(y - tipH / 2, padT + innerH - tipH),
            )
            const delta =
              point.previous_score != null
                ? point.score - point.previous_score
                : null
            return (
              <g style={{ pointerEvents: 'none' }}>
                <rect
                  fill="var(--background-color-primary)"
                  filter="drop-shadow(0 4px 10px rgba(26,26,24,0.10))"
                  height={tipH}
                  rx="8"
                  stroke="var(--border-color-secondary)"
                  width={tipW}
                  x={tx}
                  y={ty}
                />
                <text
                  fill={meta.dot}
                  fontFamily="var(--font-sans)"
                  fontSize="8"
                  fontWeight="600"
                  letterSpacing="0.06em"
                  x={tx + 12}
                  y={ty + 18}
                >
                  {meta.label.toUpperCase()} ·{' '}
                  {fmtDate(point.timestamp, true).toUpperCase()}
                </text>
                {hasDetail ? (
                  <>
                    <text
                      fill="var(--text-color-secondary)"
                      fontFamily="var(--font-sans)"
                      fontSize="10"
                      x={tx + 12}
                      y={ty + 34}
                    >
                      {formatFieldKey(correlated.field)}
                      {correlated.old != null && String(correlated.old) !== ''
                        ? `  ${String(correlated.old)} → ${String(correlated.new)}`
                        : `  → ${String(correlated.new)}`}
                    </text>
                    <text
                      fill="var(--text-color-primary)"
                      fontFamily="var(--font-sans)"
                      fontSize="12.5"
                      fontWeight="600"
                      x={tx + 12}
                      y={ty + 54}
                    >
                      {point.previous_score != null
                        ? `${Math.round(point.previous_score)} → ${Math.round(point.score)}`
                        : Math.round(point.score)}
                    </text>
                    {delta != null && (
                      <text
                        fill={
                          delta >= 0
                            ? 'var(--text-color-success)'
                            : 'var(--text-color-danger)'
                        }
                        fontFamily="var(--font-sans)"
                        fontSize="11"
                        x={tx + 12}
                        y={ty + 74}
                      >
                        {delta >= 0 ? '+' : ''}
                        {Math.round(delta)} pts
                      </text>
                    )}
                  </>
                ) : (
                  <>
                    <text
                      fill="var(--text-color-primary)"
                      fontFamily="var(--font-sans)"
                      fontSize="12.5"
                      fontWeight="600"
                      x={tx + 12}
                      y={ty + 38}
                    >
                      {point.previous_score != null
                        ? `${Math.round(point.previous_score)} → ${Math.round(point.score)}`
                        : Math.round(point.score)}
                    </text>
                    {delta != null && (
                      <text
                        fill={
                          delta >= 0
                            ? 'var(--text-color-success)'
                            : 'var(--text-color-danger)'
                        }
                        fontFamily="var(--font-sans)"
                        fontSize="11"
                        x={tx + 12}
                        y={ty + 56}
                      >
                        {delta >= 0 ? '+' : ''}
                        {Math.round(delta)} pts
                      </text>
                    )}
                  </>
                )}
              </g>
            )
          })()}
      </svg>
    </div>
  )
}

// ---------- Main tab ----------

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
    <div className="border-tertiary bg-primary inline-flex gap-0.5 rounded-md border p-0.5">
      {items.map((it) => (
        <button
          className={`duration-fast inline-flex h-6 items-center rounded px-2.5 text-xs transition-colors ${
            value === it.key
              ? 'bg-secondary text-primary font-medium'
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
