import { useMemo } from 'react'

import { Link, useLocation } from 'react-router-dom'

import { cn } from '@/lib/utils'

import { elapsed } from './conversationMode'
import { turns } from './conversationTurns'
import { formatElapsed } from './taskEvents'
import { clock } from './taskText'
import type { TimelineEntry } from './taskTimeline'
import { type Span, trajectory } from './taskTrajectory'
import { toolLabel } from './toolCalls'

/**
 * Every tool call on the task's clock, left to right: the agent's calls
 * on the top lane, subagent calls below, turn starts as dashed lines.
 * A call still running shows where it started and no length.
 */
export function TimingOverview({
  entries,
  live,
  selected,
}: {
  entries: TimelineEntry[]
  live: boolean
  selected: null | number
}) {
  const { pathname, search } = useLocation()
  const t = useMemo(
    () =>
      trajectory(entries, turns(entries, { live }), live ? Date.now() : null),
    [entries, live],
  )
  if (!t) return null
  const total = t.end - t.start
  const pct = (x: number) => `${((x - t.start) / total) * 100}%`
  return (
    <div
      aria-label="Timing"
      className="border-tertiary bg-primary shrink-0 border-b px-6 pt-1 pb-1.5"
      role="group"
    >
      <div className="relative h-11">
        {t.marks.map((mark) => (
          <div
            className="absolute inset-y-0 border-l border-dashed border-(--ds-border-secondary)"
            key={mark.label}
            style={{ left: pct(mark.at) }}
          >
            <span className="text-tertiary absolute top-0 left-1 font-mono text-[10px]">
              {mark.label}
            </span>
          </div>
        ))}
        {t.spans.map((span) => (
          <SpanMark
            href={`${pathname}${search}`}
            key={span.entry.id}
            left={pct(span.start)}
            selected={selected}
            span={span}
            width={span.end === null ? null : (span.end - span.start) / total}
          />
        ))}
      </div>
      <div className="text-tertiary flex justify-between font-mono text-[10px] tabular-nums">
        <span>{clock(new Date(t.start).toISOString())}</span>
        <span>{elapsed(total)}</span>
        <span>{clock(new Date(t.end).toISOString())}</span>
      </div>
    </div>
  )
}

function SpanMark({
  href,
  left,
  selected,
  span,
  width,
}: {
  href: string
  left: string
  selected: null | number
  span: Span
  width: null | number
}) {
  const e = span.entry.event
  const tool = e ? String(e.payload.tool ?? 'tool') : 'Task'
  const lane = span.lane ? 'top-7' : 'top-3.5'
  if (!e || width === null) {
    return (
      <span
        aria-label={`${toolLabel(tool)} running since ${clock(new Date(span.start).toISOString())}`}
        className={cn(
          'absolute size-2.5 -translate-x-1/2 rounded-full border-2 border-current text-accent',
          lane,
        )}
        role="img"
        style={{ left }}
        title={`${toolLabel(tool)} · started ${clock(new Date(span.start).toISOString())} · running`}
      />
    )
  }
  const ms = span.end! - span.start
  const duration = ms < 1000 ? `${ms}ms` : formatElapsed(ms)
  const label = `${toolLabel(tool)} · ${clock(e.at)} · ${duration}`
  return (
    <Link
      aria-label={label}
      className={cn(
        'absolute h-2.5 min-w-1 rounded-xs bg-current',
        lane,
        span.error ? 'text-danger' : span.lane ? 'text-accent' : 'text-teal',
        selected === e.seq && 'ring-2 ring-current ring-offset-1',
      )}
      replace
      style={{ left, width: `${width * 100}%` }}
      title={label}
      to={`${href}#e${e.seq}`}
    />
  )
}
