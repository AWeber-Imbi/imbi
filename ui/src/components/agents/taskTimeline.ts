import type { AgentTaskEvent } from '@/types'

// The Conversation tab is one timeline over the task log: turns, tool
// calls, requests, and state changes in seq order. Subagent events nest
// under the tool call that started them, and the continuation parts of
// a large turn or tool result are joined back into one event.

export interface TimelineEntry {
  children: TimelineEntry[]
  /**
   * The event, or null for a subagent whose call has not finished: the
   * harness writes a call when its result arrives, so its subagent
   * events are in the log before it.
   */
  event: AgentTaskEvent | null
  /** `event_id`, or `pending:<call id>` for a call not yet written. */
  id: string
  /** The call id that `children` name as their `parent_call_id`. */
  parentOf: null | string
  seq: number
}

/** The event types that the timeline shows. */
const SHOWN = new Set([
  'check.reported',
  'control.changed',
  'outcome.set',
  'owner.changed',
  'phase.changed',
  'request.opened',
  'request.resolved',
  'state.changed',
  'todos.updated',
  'tool.called',
  'turn',
  'usage.reported',
])

/** The payload field that continuation parts split, by event type. */
const SPLIT_FIELD: Record<string, string> = {
  'tool.called': 'result',
  turn: 'body',
}

/** A tool call that policy denied before it ran. */
export function isDenied(payload: Record<string, unknown>): boolean {
  const policy = payload.policy as undefined | { decision?: unknown }
  return policy?.decision === 'deny'
}

/** A failed tool call, or one that policy denied. */
export function isError(entry: TimelineEntry): boolean {
  const p = entry.event?.payload
  if (!p || entry.event?.type !== 'tool.called') return false
  return p.is_error === true || isDenied(p)
}

/**
 * Join the continuation parts of each large turn or tool result into
 * the event of its first part. A part that has not arrived yet leaves
 * a gap: the parts that are in the log are joined in order.
 */
export function joinParts(events: AgentTaskEvent[]): AgentTaskEvent[] {
  const groups = new Map<string, AgentTaskEvent[]>()
  for (const e of events) {
    const key = partKey(e)
    if (key) groups.set(key, [...(groups.get(key) ?? []), e])
  }
  const out: AgentTaskEvent[] = []
  for (const e of events) {
    const key = partKey(e)
    if (!key) {
      out.push(e)
      continue
    }
    const parts = groups.get(key)!
    const first = parts.reduce((a, b) =>
      Number(b.payload.part) < Number(a.payload.part) ? b : a,
    )
    if (e !== first) continue
    const field = SPLIT_FIELD[e.type]
    const ordered = [...parts].sort(
      (a, b) => Number(a.payload.part) - Number(b.payload.part),
    )
    const payload: Record<string, unknown> = {
      ...first.payload,
      [field]: ordered.map((p) => String(p.payload[field] ?? '')).join(''),
    }
    delete payload.part
    delete payload.parts
    out.push({ ...first, payload })
  }
  return out
}

/**
 * The timeline of a task log. Each subagent event is a child of the
 * tool call whose `call_id` is its `parent_call_id`; that call takes
 * the place of its first child, so it reads where the work started.
 */
export function timeline(
  events: AgentTaskEvent[],
  show: (type: string) => boolean = (type) => SHOWN.has(type),
): TimelineEntry[] {
  const shown = joinParts(events).filter((e) => show(e.type))
  const callId = (e: AgentTaskEvent) =>
    e.type === 'tool.called' && typeof e.payload.call_id === 'string'
      ? e.payload.call_id
      : null
  const byCall = new Map<string, TimelineEntry>()
  const entries = shown.map((event): TimelineEntry => {
    const entry: TimelineEntry = {
      children: [],
      event,
      id: event.event_id,
      parentOf: callId(event),
      seq: event.seq,
    }
    if (entry.parentOf) byCall.set(entry.parentOf, entry)
    return entry
  })
  const roots: TimelineEntry[] = []
  for (const entry of entries) {
    const parent = entry.event?.payload.parent_call_id
    if (typeof parent !== 'string' || parent === entry.parentOf) {
      roots.push(entry)
      continue
    }
    let owner = byCall.get(parent)
    if (!owner) {
      owner = {
        children: [],
        event: null,
        id: `pending:${parent}`,
        parentOf: parent,
        seq: entry.seq,
      }
      byCall.set(parent, owner)
      roots.push(owner)
    }
    owner.children.push(entry)
    owner.seq = Math.min(owner.seq, entry.seq)
  }
  const sort = (list: TimelineEntry[]) => {
    list.sort((a, b) => a.seq - b.seq)
    for (const entry of list) sort(entry.children)
    return list
  }
  return sort(roots)
}

function partKey(e: AgentTaskEvent): null | string {
  const p = e.payload
  if (!(e.type in SPLIT_FIELD) || p.parts == null) return null
  return `${e.type}:${String(p.call_id)}`
}
