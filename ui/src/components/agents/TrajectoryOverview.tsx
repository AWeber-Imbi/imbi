import {
  type PointerEvent as ReactPointerEvent,
  useEffect,
  useRef,
  useState,
} from 'react'

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

import {
  KIND_LABEL,
  type TrajectoryKind,
  type TrajectoryMode,
  type TrajectoryRecord,
  type TrajectorySpan,
} from './trajectoryModel'

export type TrajectoryRange = [number, number]

interface View {
  size: number
  start: number
}

const DRAG_PX = 3
const LANES = ['Input', 'Model', 'Tools']
const SPAN_COLOR: Record<TrajectoryKind, string> = {
  assistant: 'bg-(--tj-assistant) opacity-100',
  context: 'bg-(--tj-context)',
  subtool: 'bg-(--tj-warn)',
  system: 'bg-(--tj-label-2)',
  tool: 'bg-(--tj-warn)',
  user: 'bg-(--tj-business)',
}

/** The records a range covers: active at any point inside it. */
export function focusedBy(
  spans: TrajectorySpan[],
  range: null | TrajectoryRange,
): null | Set<string> {
  if (!range) return null
  const [start, end] = range
  return new Set(
    spans.filter((s) => s.start <= end && s.end >= start).map((s) => s.id),
  )
}

/** `Total 1,234 ms`. */
export function totalText(ms: number): string {
  return `Total ${Math.round(ms).toLocaleString('en-US')} ms`
}

/**
 * The timing overview: three lanes of spans with no axis. Drag selects
 * a range, a click on a span selects its record, the wheel zooms, the
 * right button clears or pans, and a double-click or Escape resets.
 */
export function TrajectoryOverview({
  boundaries,
  domain,
  matches,
  mode,
  onRange,
  onSelect,
  range,
  records,
  selected,
  spans,
}: {
  /** Where each turn after the first starts, in domain units. */
  boundaries: number[]
  domain: number
  /** The ids that match the search; null when there is no search. */
  matches: null | Set<string>
  mode: TrajectoryMode
  onRange: (range: null | TrajectoryRange) => void
  onSelect: (id: string) => void
  range: null | TrajectoryRange
  records: Map<string, TrajectoryRecord>
  selected: null | string
  spans: TrajectorySpan[]
}) {
  const track = useRef<HTMLDivElement>(null)
  const full = Math.max(domain, 1e-9)
  const [view, setView] = useState<null | View>(null)
  const [draft, setDraft] = useState<null | TrajectoryRange>(null)
  const [hoverX, setHoverX] = useState<null | number>(null)
  const [panning, setPanning] = useState(false)
  const drag = useRef<null | {
    button: number
    moved: boolean
    span: null | string
    startView: View
    x: number
  }>(null)
  const v: View = view ?? { size: full, start: 0 }
  const minSize = spans.length ? full / spans.length : full

  const toDomain = (clientX: number) => {
    const rect = track.current!.getBoundingClientRect()
    const ratio = rect.width ? (clientX - rect.left) / rect.width : 0
    return v.start + Math.min(Math.max(ratio, 0), 1) * v.size
  }
  const pct = (value: number) => ((value - v.start) / v.size) * 100

  useEffect(() => {
    const el = track.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      setView((prev) => {
        const cur = prev ?? { size: full, start: 0 }
        const rect = el.getBoundingClientRect()
        const ratio = rect.width ? (e.clientX - rect.left) / rect.width : 0.5
        const at = cur.start + ratio * cur.size
        const smallest = Math.min(full, mode === 'sequence' ? 4 : 20)
        const size = Math.min(
          full,
          Math.max(smallest, cur.size * Math.exp(e.deltaY * 0.0015)),
        )
        if (size >= full * 0.999) return null
        const start = Math.min(Math.max(at - ratio * size, 0), full - size)
        return { size, start }
      })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [full, mode])

  useEffect(() => {
    if (!view || !selected) return
    const span = spans.find((s) => s.id === selected)
    if (!span) return
    if (span.start >= view.start && span.end <= view.start + view.size) return
    const start = Math.min(
      Math.max((span.start + span.end) / 2 - view.size / 2, 0),
      full - view.size,
    )
    setView({ size: view.size, start })
  }, [selected, spans, view, full])

  const commit = (a: number, b: number) => {
    let [start, end] = a < b ? [a, b] : [b, a]
    if (end - start < minSize) {
      const mid = (start + end) / 2
      start = Math.max(0, mid - minSize / 2)
      end = Math.min(full, start + minSize)
    }
    onRange([start, end])
  }

  const onPointerDown = (e: ReactPointerEvent) => {
    if (e.button !== 0 && e.button !== 2) return
    track.current?.setPointerCapture?.(e.pointerId)
    const span =
      (e.target as HTMLElement).closest<HTMLElement>('[data-span]')?.dataset
        .span ?? null
    drag.current = {
      button: e.button,
      moved: false,
      span,
      startView: v,
      x: e.clientX,
    }
  }
  const onPointerMove = (e: ReactPointerEvent) => {
    const d = drag.current
    if (!d) {
      setHoverX(e.target === track.current ? toDomain(e.clientX) : null)
      return
    }
    if (Math.abs(e.clientX - d.x) >= DRAG_PX) d.moved = true
    if (!d.moved) return
    const rect = track.current!.getBoundingClientRect()
    if (d.button === 2 && view) {
      setPanning(true)
      const delta = ((d.x - e.clientX) / rect.width) * d.startView.size
      const start = Math.min(
        Math.max(d.startView.start + delta, 0),
        full - d.startView.size,
      )
      setView({ size: d.startView.size, start })
      return
    }
    if (d.button !== 0) return
    if (view) {
      const edge = Math.min(32, rect.width * 0.08)
      const step = full * 0.025
      if (e.clientX < rect.left + edge)
        setView({ size: view.size, start: Math.max(0, view.start - step) })
      else if (e.clientX > rect.right - edge)
        setView({
          size: view.size,
          start: Math.min(full - view.size, view.start + step),
        })
    }
    const from =
      d.startView.start + ((d.x - rect.left) / rect.width) * d.startView.size
    setDraft([from, toDomain(e.clientX)])
  }
  const onPointerUp = (e: ReactPointerEvent) => {
    const d = drag.current
    drag.current = null
    setPanning(false)
    if (!d) return
    if (d.button === 2) {
      if (!d.moved) onRange(null)
      return
    }
    if (d.moved && draft) {
      commit(draft[0], draft[1])
      setDraft(null)
      return
    }
    setDraft(null)
    if (d.span) {
      onRange(null)
      onSelect(d.span)
      return
    }
    const at = toDomain(e.clientX)
    commit(at, at)
  }

  return (
    <div className="hairline-b grid h-12.5 shrink-0 grid-cols-[44px_minmax(0,1fr)] border-(--tj-border-2) bg-(--tj-bg-2) text-[11px] leading-[14px]">
      <div
        aria-hidden
        className="hairline-r relative border-(--tj-border-1) text-[10px] text-(--tj-caption)"
      >
        {LANES.map((lane, i) => (
          <span
            className="absolute right-1.5 leading-[8px]"
            key={lane}
            style={{ top: 7 + i * 14 }}
          >
            {lane}
          </span>
        ))}
      </div>
      <div
        aria-label="Timing overview"
        className={cn(
          'relative overflow-hidden outline-none select-none',
          panning && 'cursor-grabbing',
        )}
        onContextMenu={(e) => e.preventDefault()}
        onDoubleClick={() => onRange(null)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onRange(null)
        }}
        onPointerDown={onPointerDown}
        onPointerLeave={() => setHoverX(null)}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        ref={track}
        role="application"
        tabIndex={0}
      >
        {spans.length === 0 ? (
          <span className="absolute inset-0 flex items-center justify-center text-(--tj-caption)">
            No timing data
          </span>
        ) : (
          <TooltipProvider delayDuration={500}>
            {boundaries.map((b) => (
              <span
                aria-hidden
                className="hairline-l absolute inset-y-0 w-0 border-(--tj-border-2)"
                key={b}
                style={{ left: `${pct(b)}%` }}
              />
            ))}
            <div className="pointer-events-none absolute inset-x-0 top-1.75 bottom-1.75">
              {spans.map((span) => {
                const record = records.get(span.id)
                if (!record) return null
                const outside =
                  range && !(span.start <= range[1] && span.end >= range[0])
                return (
                  <SpanBar
                    current={selected === span.id}
                    dim={
                      matches && !matches.has(span.id)
                        ? 'search'
                        : outside
                          ? 'range'
                          : null
                    }
                    key={span.id}
                    left={pct(span.start)}
                    record={record}
                    span={span}
                    width={((span.end - span.start) / v.size) * 100}
                  />
                )
              })}
            </div>
          </TooltipProvider>
        )}
        {hoverX !== null && !draft && (
          <span
            aria-hidden
            className="pointer-events-none absolute inset-y-0 w-0.5 -translate-x-1/2 bg-(--tj-brand)"
            style={{ left: `${pct(hoverX)}%` }}
          />
        )}
        {draft && <Band dim={false} range={draft} toPct={pct} />}
        {range && !draft && <Band dim range={range} toPct={pct} />}
      </div>
    </div>
  )
}

function Band({
  dim,
  range,
  toPct,
}: {
  dim: boolean
  range: TrajectoryRange
  toPct: (value: number) => number
}) {
  const [a, b] = range[0] < range[1] ? range : [range[1], range[0]]
  return (
    <span
      aria-hidden
      className={cn(
        'pointer-events-none absolute inset-y-0 border-x-(--tj-brand)',
        dim
          ? 'border-x-[3px] bg-[color-mix(in_srgb,var(--tj-brand)_12%,transparent)] shadow-[0_0_0_9999px_color-mix(in_srgb,var(--tj-bg-1)_58%,transparent)]'
          : 'border-x-2 bg-[color-mix(in_srgb,var(--tj-brand)_18%,transparent)]',
      )}
      data-range={dim ? 'committed' : 'draft'}
      style={{ left: `${toPct(a)}%`, width: `${toPct(b) - toPct(a)}%` }}
    />
  )
}

function clock(ms: number): string {
  const d = new Date(ms)
  const two = (n: number) => String(n).padStart(2, '0')
  return `${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}.${String(d.getMilliseconds()).padStart(3, '0')}`
}

function SpanBar({
  current,
  dim,
  left,
  record,
  span,
  width,
}: {
  current: boolean
  dim: 'range' | 'search' | null
  left: number
  record: TrajectoryRecord
  span: TrajectorySpan
  width: number
}) {
  const { endedAt, startedAt } = record
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            'pointer-events-auto absolute h-2 min-w-0.5 rounded-[1px] opacity-[.78] transition-[left,opacity] duration-180 hover:shadow-[0_0_0_1px_var(--tj-bg-2),0_0_0_3px_color-mix(in_srgb,var(--tj-brand)_80%,transparent)]',
            record.error ? 'bg-(--tj-error)' : SPAN_COLOR[record.kind],
            current && 'shadow-[0_0_0_2px_var(--tj-brand)]',
            dim === 'range' && 'opacity-20',
            dim === 'search' && 'opacity-[.14]',
          )}
          data-current={current || undefined}
          data-dim={dim ?? undefined}
          data-span={span.id}
          style={{
            left: `calc(${left}% + min(${width * 0.08}%, 1px))`,
            top: span.lane * 14,
            width: `calc(${width}% - 2 * min(${width * 0.08}%, 1px))`,
          }}
        />
      </TooltipTrigger>
      <TooltipContent
        className="font-tj-code rounded-[4px] px-2 py-1 text-[11px] leading-[14px]"
        side="bottom"
      >
        <div className="font-semibold">{KIND_LABEL[record.kind]}</div>
        {startedAt !== null && endedAt !== null ? (
          <>
            <div>
              {clock(startedAt)} → {clock(endedAt)}
            </div>
            <div>{totalText(endedAt - startedAt)}</div>
          </>
        ) : startedAt !== null ? (
          <div>Started {clock(startedAt)}</div>
        ) : null}
      </TooltipContent>
    </Tooltip>
  )
}
