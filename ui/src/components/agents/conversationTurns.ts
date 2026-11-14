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

/** The router state that asks the conversation to show an event's turn. */
export interface RevealState {
  revealSeq: number
}

/**
 * A key that survives a call being written: a still-running subagent call
 * is a placeholder until its own event lands with a new id.
 */
export function entryKey(entry: TimelineEntry): string {
  return entry.parentOf ? `call:${entry.parentOf}` : entry.id
}

/** The event seq of an `#e<seq>` permalink, if the hash is one. */
export function hashSeqOf(hash: string): null | number {
  const match = /^#e(\d+)$/.exec(hash)
  return match ? Number(match[1]) : null
}

/** The event seq a view asked the conversation to show, if any. */
export function revealSeqOf(state: unknown): null | number {
  if (!state || typeof state !== 'object' || !('revealSeq' in state))
    return null
  const { revealSeq } = state
  return typeof revealSeq === 'number' ? revealSeq : null
}

/**
 * Where an event shows in the conversation: the turn that holds it, with
 * a subagent's events in the turn of their Agent call, the work group it
 * sits in, and the keys of the calls it is nested in. An event the conversation leaves out, such as a usage
 * report, belongs to the last turn that started before it, and one from
 * before every turn, such as the task's creation, to the first turn.
 */
export function turnForSeq(
  list: Turn[],
  seq: number,
): null | { calls: string[]; group: null | string; turn: Turn } {
  let before: Turn | undefined = list[0]
  for (const turn of list) {
    if (turn.opening.flatMap(eventsOf).some((e) => seqOf(e) === seq))
      return { calls: [], group: null, turn }
    for (const item of turn.items)
      for (const entry of entriesOf([item])) {
        const path = pathTo(entry, seq)
        if (path)
          return {
            calls: path.slice(0, -1).map(entryKey),
            group: item.kind === 'group' ? item.id : null,
            turn,
          }
      }
    const seqs = [...turn.opening, ...entriesOf(turn.items)]
      .flatMap(eventsOf)
      .map(seqOf)
    if (seqs.length && Math.min(...seqs) <= seq) before = turn
  }
  return before ? { calls: [], group: null, turn: before } : null
}

/**
 * The turns of a timeline. The harness records no turn start or end, so
 * a turn starts at a person's input once the agent waits on a person
 * (its last reply or request); input while it works steers that turn.
 */
export function turns(
  entries: TimelineEntry[],
  task: { failed?: boolean; live: boolean },
): Turn[] {
  const list: Turn[] = []
  for (const entry of entries) {
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
    const keyed = turnOfInput(list, entry)
    const previous = list[list.length - 2]
    if (keyed) {
      if (keyed === turn) add(turn, entry)
      else addEarlier(keyed, entry)
    } else if (previous && stampedBefore(entry, turn.opening[0]))
      addEarlier(previous, entry)
    else add(turn, entry)
  }

  list.forEach((turn, i) => finish(turn, list[i + 1]))
  const final = last(list)
  if (final && task.live && !waiting(final)) final.status = 'running'
  else if (final && !task.live && task.failed) final.status = 'failed'
  return list
}

function add(turn: Turn, entry: TimelineEntry) {
  const e = entry.event
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

/**
 * The harness sends what the agent did before it asked a person only once
 * the person answers, so that work arrives after the answer. It goes back
 * to the turn it was done in, before the items that came after it.
 */
function addEarlier(turn: Turn, entry: TimelineEntry) {
  const at = stampOf(entry)
  let cut = turn.items.length
  while (cut > 0 && stampOf(firstEntry(turn.items[cut - 1])) > at) cut--
  const later = turn.items.splice(cut)
  const group = last(turn.items)
  const rest = group?.kind === 'group' ? splitAfter(group, at) : []
  const size = group?.kind === 'group' ? group.entries.length : 0
  add(turn, entry)
  if (group?.kind === 'group' && group.entries.length > size)
    group.entries.push(...rest)
  else if (rest.length)
    later.unshift({
      entries: rest,
      id: `g:${entryKey(rest[0])}`,
      kind: 'group',
    })
  turn.items.push(...later)
}

function entriesOf(items: TurnItem[]): TimelineEntry[] {
  return items.flatMap((item) =>
    item.kind === 'group' ? item.entries : [item.entry],
  )
}

function eventsOf(entry: TimelineEntry): TimelineEntry[] {
  return [entry, ...entry.children.flatMap(eventsOf)]
}

function finish(turn: Turn, next?: Turn) {
  const work = turn.items.filter(isWork)
  const all = [...turn.opening, ...entriesOf(turn.items)].flatMap(eventsOf)
  for (const entry of all) {
    if (!entry.event || entry.event.type === 'tool.called') turn.stats.tools++
    if (isError(entry)) turn.stats.errors++
    if (entry.event?.type === 'usage.reported')
      turn.stats.tokens += tokensOf(entry)
  }
  const times = entriesOf(work)
    .flatMap(eventsOf)
    .map(timeOf)
    .filter((t) => !Number.isNaN(t))
  const start = startOf(turn) ?? Math.min(...times)
  const stop = next?.opening.length
    ? Math.min(...next.opening.map(timeOf))
    : Infinity
  const ends = times.filter((t) => t >= start && t <= stop)
  turn.stats.durationMs =
    ends.length && (turn.opening.length || ends.length > 1)
      ? Math.max(...ends) - start
      : null
}

function firstEntry(item: TurnItem): TimelineEntry {
  return item.kind === 'group' ? item.entries[0] : item.entry
}

/**
 * The newest person input the harness had when it recorded the entry's
 * earliest work, or null for an older harness that does not say.
 */
function inputSeqOf(entry: TimelineEntry): null | number {
  const seqs = eventsOf(entry).flatMap((e) => {
    const seq = e.event?.payload.input_seq
    return typeof seq === 'number' ? [seq] : []
  })
  return seqs.length ? Math.min(...seqs) : null
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

/**
 * A call that is still running has no event yet and takes its first
 * child's seq, so that child is looked for before the call itself.
 */
function pathTo(entry: TimelineEntry, seq: number): null | TimelineEntry[] {
  if (entry.event?.seq === seq) return [entry]
  for (const child of entry.children) {
    const path = pathTo(child, seq)
    if (path) return [entry, ...path]
  }
  return !entry.event && entry.seq === seq ? [entry] : null
}

/** A call entry takes its first child's seq; match on its own event's. */
function seqOf(entry: TimelineEntry): number {
  return entry.event?.seq ?? entry.seq
}

/** Take a group's entries stamped after a time out of it. */
function splitAfter(group: ProcessGroup, at: number): TimelineEntry[] {
  const split = group.entries.findIndex((e) => stampOf(e) > at)
  return split > 0 ? group.entries.splice(split) : []
}

/** An agent entry the harness stamped before the person's opening. */
function stampedBefore(entry: TimelineEntry, opening?: TimelineEntry): boolean {
  return !!opening && stampOf(entry) < timeOf(opening)
}

/**
 * When an entry's work began: the earliest time over it and its children,
 * since a call is stamped when it ends and a running call has no event.
 */
function stampOf(entry: TimelineEntry): number {
  const times = eventsOf(entry)
    .map(timeOf)
    .filter((t) => !Number.isNaN(t))
  return times.length ? Math.min(...times) : NaN
}

/**
 * When the agent began a turn a person opened: the last time it resumed
 * before its first work, or its first opening message. A paused or
 * queued task waits for a runner, and that wait is not work.
 */
function startOf(turn: Turn): null | number {
  if (!turn.opening.length) return null
  let start = Math.min(...turn.opening.map(timeOf))
  for (const item of turn.items) {
    if (item.kind !== 'note') break
    const e = item.entry.event
    if (e?.type === 'state.changed' && e.payload.to === 'running')
      start = Math.max(start, timeOf(item.entry))
  }
  return start
}

function timeOf(entry: TimelineEntry): number {
  return entry.event ? Date.parse(entry.event.at) : NaN
}

function tokensOf(entry: TimelineEntry): number {
  const p = entry.event?.payload ?? {}
  const n = (v: unknown) => (typeof v === 'number' ? v : 0)
  return n(p.tokens_in) + n(p.tokens_out)
}

/** The turn the person input an entry names opened, if it names one. */
function turnOfInput(list: Turn[], entry: TimelineEntry): Turn | undefined {
  const seq = inputSeqOf(entry)
  if (seq === null) return undefined
  for (let i = list.length - 1; i > 0; i--) {
    const opening = list[i].opening[0]
    if (opening && seqOf(opening) <= seq) return list[i]
  }
  return list[0]
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
