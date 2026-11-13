import type { Turn } from './conversationTurns'
import { isError, type TimelineEntry } from './taskTimeline'

/** One tool call on the timing overview; `end` is null while it runs. */
export interface Span {
  end: null | number
  entry: TimelineEntry
  error: boolean
  lane: 0 | 1
  start: number
}

export interface Trajectory {
  end: number
  marks: TurnMark[]
  spans: Span[]
  start: number
}

export interface TurnMark {
  at: number
  label: string
}

/** The entry with this seq, at any depth. */
export function findEntry(
  entries: TimelineEntry[],
  seq: number,
): null | TimelineEntry {
  for (const entry of entries) {
    if (entry.event?.seq === seq) return entry
    const found = findEntry(entry.children, seq)
    if (found) return found
  }
  return null
}

/**
 * Tool calls placed on the task's clock: a call ends when its event was
 * written and started `duration_ms` before. A subagent call still running
 * starts at its first step and has no end yet.
 */
export function trajectory(
  entries: TimelineEntry[],
  list: Turn[],
  now: null | number,
): null | Trajectory {
  const spans: Span[] = []
  const visit = (entry: TimelineEntry, lane: 0 | 1) => {
    const e = entry.event
    if (e && e.type !== 'tool.called') {
      for (const child of entry.children) visit(child, 1)
      return
    }
    const start = earliest(entry)
    if (start !== null)
      spans.push({
        end: e ? Date.parse(e.at) : null,
        entry,
        error: isError(entry),
        lane,
        start,
      })
    for (const child of entry.children) visit(child, 1)
  }
  for (const entry of entries) visit(entry, 0)
  if (!spans.length) return null

  const times = entries.flatMap(timesOf)
  if (now !== null && spans.some((s) => s.end === null)) times.push(now)
  const start = Math.min(...times)
  const end = Math.max(...times)
  if (end <= start) return null

  const marks: TurnMark[] = []
  list.forEach((turn, i) => {
    const first = turn.opening[0] ?? firstEntry(turn)
    if (first?.event)
      marks.push({ at: Date.parse(first.event.at), label: `T${i + 1}` })
  })
  return { end, marks, spans, start }
}

function earliest(entry: TimelineEntry): null | number {
  const times = timesOf(entry)
  return times.length ? Math.min(...times) : null
}

function firstEntry(turn: Turn): TimelineEntry | undefined {
  const item = turn.items[0]
  if (!item) return undefined
  return item.kind === 'group' ? item.entries[0] : item.entry
}

function timesOf(entry: TimelineEntry): number[] {
  const own: number[] = []
  const e = entry.event
  if (e) {
    const at = Date.parse(e.at)
    const ms = e.payload.duration_ms
    own.push(at)
    if (e.type === 'tool.called' && typeof ms === 'number') own.push(at - ms)
  }
  return [...own, ...entry.children.flatMap(timesOf)]
}
