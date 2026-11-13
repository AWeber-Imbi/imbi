import { isError, type TimelineEntry } from './taskTimeline'

/** A human message or a request, after the work of its turn began. */
export interface InputItem {
  entry: TimelineEntry
  id: string
  kind: 'input'
}

/** A state, phase, owner, or outcome change. */
export interface NoteItem {
  entry: TimelineEntry
  id: string
  kind: 'note'
}

/** Consecutive work between two replies: thinking, calls, plans. */
export interface ProcessGroup {
  entries: TimelineEntry[]
  id: string
  kind: 'group'
}

/** What the agent said to the reader. */
export interface ReplyItem {
  entry: TimelineEntry
  id: string
  kind: 'reply'
}

/**
 * One exchange: the human input that started it, then the agent's work
 * and replies until it waits on a person again.
 */
export interface Turn {
  id: string
  items: TurnItem[]
  opening: TimelineEntry[]
  stats: TurnStats
  status: TurnStatus
  /** A person wrote while the work ran, so the turn cannot fold. */
  steered: boolean
}

export type TurnItem = InputItem | NoteItem | ProcessGroup | ReplyItem

export interface TurnStats {
  durationMs: null | number
  errors: number
  tokens: number
  tools: number
}

export type TurnStatus = 'done' | 'failed' | 'running'

const NOTE_TYPES = new Set([
  'check.reported',
  'control.changed',
  'outcome.set',
  'owner.changed',
  'phase.changed',
  'state.changed',
])

/**
 * The turns of a timeline. The harness records no turn start or end, so
 * a turn starts at a person's input once the agent waits on a person
 * (its last reply or request); input while it works steers that turn.
 */
/**
 * A key that survives a call being written: a still-running subagent call
 * is a placeholder until its own event lands with a new id.
 */
export function entryKey(entry: TimelineEntry): string {
  return entry.parentOf ? `call:${entry.parentOf}` : entry.id
}

export function turns(
  entries: TimelineEntry[],
  task: { failed?: boolean; live: boolean },
): Turn[] {
  const list: Turn[] = []
  for (const entry of entries) {
    const e = entry.event
    let turn = last(list)
    if (isPersonInput(entry)) {
      if (!turn || waiting(turn)) list.push(newTurn([entry], entry))
      else if (!turn.items.some(isWork)) turn.opening.push(entry)
      else {
        turn.items.push({ entry, id: entry.id, kind: 'input' })
        turn.steered = true
      }
      continue
    }
    if (!turn) {
      turn = newTurn([], entry)
      list.push(turn)
    }
    if (e?.type === 'usage.reported') turn.stats.tokens += tokensOf(entry)
    else if (e?.type === 'turn' && isReply(entry))
      turn.items.push({ entry, id: entry.id, kind: 'reply' })
    else if (e?.type === 'request.opened')
      turn.items.push({ entry, id: entry.id, kind: 'input' })
    else if (e && NOTE_TYPES.has(e.type))
      turn.items.push({ entry, id: entry.id, kind: 'note' })
    else {
      const group = last(turn.items)
      if (group?.kind === 'group') group.entries.push(entry)
      else
        turn.items.push({
          entries: [entry],
          id: `g:${entryKey(entry)}`,
          kind: 'group',
        })
    }
  }

  for (const turn of list) finish(turn)
  const final = last(list)
  if (final && task.live && !waiting(final)) final.status = 'running'
  else if (final && !task.live && task.failed) final.status = 'failed'
  return list
}

function eventsOf(entry: TimelineEntry): TimelineEntry[] {
  return [entry, ...entry.children.flatMap(eventsOf)]
}

function finish(turn: Turn) {
  const all = [
    ...turn.opening,
    ...turn.items.flatMap((item) =>
      item.kind === 'group' ? item.entries : [item.entry],
    ),
  ].flatMap(eventsOf)
  for (const entry of all) {
    if (!entry.event || entry.event.type === 'tool.called') turn.stats.tools++
    if (isError(entry)) turn.stats.errors++
    if (entry.event?.type === 'usage.reported')
      turn.stats.tokens += tokensOf(entry)
  }
  const times = all
    .map((entry) => (entry.event ? Date.parse(entry.event.at) : NaN))
    .filter((t) => !Number.isNaN(t))
  turn.stats.durationMs =
    times.length > 1 ? Math.max(...times) - Math.min(...times) : null
}

function isPersonInput(entry: TimelineEntry): boolean {
  const e = entry.event
  if (e?.actor_kind !== 'human') return false
  return e.type === 'turn' || e.type === 'request.resolved'
}

function isReply(entry: TimelineEntry): boolean {
  const kind = entry.event?.payload.kind
  return kind !== 'thinking' && kind !== 'warning'
}

function isWork(item: TurnItem): boolean {
  return item.kind !== 'note'
}

function last<T>(list: T[]): T | undefined {
  return list[list.length - 1]
}

function newTurn(opening: TimelineEntry[], first: TimelineEntry): Turn {
  return {
    id: `t:${entryKey(first)}`,
    items: [],
    opening,
    stats: { durationMs: null, errors: 0, tokens: 0, tools: 0 },
    status: 'done',
    steered: false,
  }
}

function tokensOf(entry: TimelineEntry): number {
  const p = entry.event?.payload ?? {}
  const n = (v: unknown) => (typeof v === 'number' ? v : 0)
  return n(p.tokens_in) + n(p.tokens_out)
}

/** The agent's last word was a reply or a request: it waits on a person. */
function waiting(turn: Turn): boolean {
  const work = last(turn.items.filter(isWork))
  if (!work) return false
  return (
    work.kind === 'reply' ||
    (work.kind === 'input' && work.entry.event?.type === 'request.opened')
  )
}
