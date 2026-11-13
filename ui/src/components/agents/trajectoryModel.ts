import type { AgentTaskEvent } from '@/types'

import { systemText } from './taskText'
import { isError, timeline, type TimelineEntry } from './taskTimeline'
import { isRecord, toolLabel, toolSummary } from './toolCalls'

export type Fold =
  | { key: number; type: 'turn' }
  | { key: string; type: 'calls' | 'subcalls' }

export type FoldButton = 'calls' | 'subcalls' | 'turns'

export interface Folds {
  calls: Set<string>
  subcalls: Set<string>
  turns: Set<number>
}

export interface Trajectory {
  records: TrajectoryRecord[]
  requests: TrajectoryRequest[]
  turns: TrajectoryTurn[]
}

export type TrajectoryKind =
  | 'assistant'
  | 'context'
  | 'subtool'
  | 'system'
  | 'tool'
  | 'user'

export type TrajectoryMode = 'duration' | 'sequence'

export interface TrajectoryRecord {
  /** For an assistant: its thinking and its reply. */
  body: { reply: string; thinking: string }
  /** Ms since the epoch; null while it runs. */
  endedAt: null | number
  error: boolean
  events: AgentTaskEvent[]
  id: string
  kind: TrajectoryKind
  /** The tool record a subtool ran under. */
  parent: null | string
  /** The number of the model request that produced it. */
  request: null | number
  seqs: number[]
  startedAt: null | number
  step: null | number
  text: string
  tool: null | TrajectoryTool
  turn: number
}

export interface TrajectoryRequest {
  assistant: string
  endedAt: null | number
  number: number
  startedAt: null | number
  status: 'completed' | 'pending'
  step: number
  subtoolCalls: number
  toolCalls: number
  turn: number
  usage: AgentTaskEvent | null
}

export type TrajectoryRow =
  | { fold: Fold; id: string; kind: 'summary'; text: string }
  | { kind: 'record'; record: TrajectoryRecord }

export interface TrajectorySpan {
  end: number
  id: string
  lane: 0 | 1 | 2
  start: number
}

export interface TrajectoryTool {
  args: string
  arguments: unknown
  callId: null | string
  durationMs: null | number
  name: string
  result: string
  resultValue: unknown
  tool: string
}

export interface TrajectoryTurn {
  first: string
  number: number
  steps: number
  toolCalls: number
}

export const KIND_LABEL: Record<TrajectoryKind, string> = {
  assistant: 'ASSISTANT',
  context: 'CONTEXT',
  subtool: 'SUBTOOL',
  system: 'SYSTEM',
  tool: 'TOOL',
  user: 'USER',
}

const LANE: Record<TrajectoryKind, 0 | 1 | 2> = {
  assistant: 1,
  context: 0,
  subtool: 2,
  system: 0,
  tool: 2,
  user: 0,
}

/**
 * The trajectory of a task log. The brief and each human turn start a
 * turn. A `usage.reported` opens a model request, and the agent turns
 * and tool calls after it belong to that request.
 */
export function buildTrajectory(
  events: AgentTaskEvent[],
  live: boolean,
): Trajectory {
  const records: TrajectoryRecord[] = []
  const requests: TrajectoryRequest[] = []
  const byId = new Map<string, TrajectoryRecord>()
  const state = {
    current: null as null | TrajectoryRequest,
    lastEnd: null as null | number,
    step: 0,
    turn: 0,
  }

  const push = (record: TrajectoryRecord) => {
    records.push(record)
    byId.set(record.id, record)
    const end = record.endedAt ?? record.startedAt
    if (end !== null && (state.lastEnd === null || end > state.lastEnd))
      state.lastEnd = end
  }
  const startTurn = () => {
    state.current = null
    state.turn += 1
    state.step = 0
  }
  const open = (usage: AgentTaskEvent | null, seq: number) => {
    if (state.turn === 0) state.turn = 1
    state.step += 1
    const request: TrajectoryRequest = {
      assistant: usage ? usage.event_id : `request:${seq}`,
      endedAt: null,
      number: requests.length + 1,
      startedAt: state.lastEnd,
      status: usage ? 'completed' : 'pending',
      step: state.step,
      subtoolCalls: 0,
      toolCalls: 0,
      turn: state.turn,
      usage,
    }
    requests.push(request)
    push({
      body: { reply: '', thinking: '' },
      endedAt: null,
      error: false,
      events: usage ? [usage] : [],
      id: request.assistant,
      kind: 'assistant',
      parent: null,
      request: request.number,
      seqs: usage ? [usage.seq] : [],
      startedAt: state.lastEnd,
      step: state.step,
      text: '',
      tool: null,
      turn: state.turn,
    })
    state.current = request
    return request
  }

  for (const entry of timeline(events, () => true)) {
    const e = entry.event
    if (e?.type === 'usage.reported') {
      const pending = state.current
      if (pending && !pending.usage && pending.toolCalls === 0) {
        pending.usage = e
        pending.status = 'completed'
        const a = byId.get(pending.assistant)!
        a.events.unshift(e)
        a.seqs.unshift(e.seq)
      } else open(e, e.seq)
      continue
    }
    if (e?.type === 'task.created') {
      startTurn()
      const brief = String(e.payload.description || e.payload.title || '')
      push(instant(e, 'user', preview(brief), state.turn))
      continue
    }
    if (e?.type === 'turn' && e.actor_kind === 'human') {
      startTurn()
      const body = String(e.payload.body ?? '')
      push(instant(e, 'user', preview(body), state.turn))
      continue
    }
    if (e?.type === 'turn') {
      const request = state.current ?? open(null, e.seq)
      const a = byId.get(request.assistant)!
      const body = String(e.payload.body ?? '')
      if (e.payload.kind === 'thinking')
        a.body.thinking = join(a.body.thinking, body)
      else a.body.reply = join(a.body.reply, body)
      a.events.push(e)
      a.seqs.push(e.seq)
      continue
    }
    if (!e || e.type === 'tool.called') {
      const request = state.current ?? open(null, entry.seq)
      request.toolCalls += 1
      const tool = toolRecord(entry, 'tool', null, request, state.turn)
      push(tool)
      for (const child of subcalls(entry)) {
        request.subtoolCalls += 1
        push(toolRecord(child, 'subtool', tool.id, request, state.turn))
      }
      continue
    }
    if (state.turn === 0) state.turn = 1
    const kind =
      e.type === 'request.opened' || e.type === 'request.resolved'
        ? 'context'
        : 'system'
    push(instant(e, kind, lineFor(e), state.turn))
  }

  for (const request of requests) finishRequest(request, records, byId, live)
  return { records, requests, turns: turnsOf(records) }
}

/** The turns, assistants or tools that a fold button folds. */
export function foldKeys(
  trajectory: Trajectory,
  type: FoldButton,
): (number | string)[] {
  const { records, turns } = trajectory
  if (type === 'turns')
    return turns
      .filter(
        (t) =>
          records.filter((r) => r.turn === t.number && r.kind !== 'system')
            .length > 1,
      )
      .map((t) => t.number)
  if (type === 'calls')
    return records
      .filter(
        (r) =>
          r.kind === 'assistant' &&
          records.some((x) => x.request === r.request && x.kind === 'tool'),
      )
      .map((r) => r.id)
  return records
    .filter((r) => r.kind === 'tool' && records.some((x) => x.parent === r.id))
    .map((r) => r.id)
}

/** Ms as `412 ms`, `1.25 s`, `12.4 s`. */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`
  if (ms < 10_000) return `${(ms / 1000).toFixed(2)} s`
  return `${(ms / 1000).toFixed(1)} s`
}

/** The lane of a record in the overview: input, model, or tools. */
export function laneOf(kind: TrajectoryKind): 0 | 1 | 2 {
  return LANE[kind]
}

/** One line of Markdown as text: at most 512 characters. */
export function preview(markdown: string): string {
  const text = markdown
    .slice(0, 2048)
    .replace(/```[\s\S]*?(```|$)/g, ' ')
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/[*_`#>]+/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  return text.length > 512 || markdown.length > 2048
    ? `${text.slice(0, 512)}…`
    : text
}

/** The record that a `#e<seq>` link points at: it, or the one before. */
export function recordForSeq(
  records: TrajectoryRecord[],
  seq: number,
): null | TrajectoryRecord {
  const own = records.find((r) => r.seqs.includes(seq))
  if (own) return own
  let best: null | TrajectoryRecord = null
  let bestSeq = -Infinity
  for (const r of records) {
    const first = r.seqs.length ? Math.min(...r.seqs) : Infinity
    if (first <= seq && first > bestSeq) {
      best = r
      bestSeq = first
    }
  }
  return best ?? records[0] ?? null
}

/** The ledger rows: search ignores folds; folds add summary rows. */
export function rowsOf(
  trajectory: Trajectory,
  folds: Folds,
  query: string,
): TrajectoryRow[] {
  const { records, turns } = trajectory
  const q = query.trim().toLowerCase()
  if (q)
    return records
      .filter((r) => searchText(r).includes(q))
      .map((record) => ({ kind: 'record', record }))
  const assistantOf = new Map(
    records.filter((r) => r.kind === 'assistant').map((r) => [r.request, r.id]),
  )
  const rows: TrajectoryRow[] = []
  for (const record of records) {
    const turn = turns.find((t) => t.number === record.turn)
    if (turn && folds.turns.has(turn.number)) {
      if (record.id === turn.first) {
        rows.push({ kind: 'record', record })
        rows.push({
          fold: { key: turn.number, type: 'turn' },
          id: `fold:turn:${turn.number}`,
          kind: 'summary',
          text: `${turn.steps} ${turn.steps === 1 ? 'step' : 'steps'} · ${calls(turn.toolCalls)}`,
        })
      }
      continue
    }
    if (record.kind === 'tool' || record.kind === 'subtool') {
      const owner = assistantOf.get(record.request)
      if (owner && folds.calls.has(owner)) continue
      if (record.parent && folds.subcalls.has(record.parent)) continue
    }
    rows.push({ kind: 'record', record })
    if (record.kind === 'assistant' && folds.calls.has(record.id))
      rows.push({
        fold: { key: record.id, type: 'calls' },
        id: `fold:calls:${record.id}`,
        kind: 'summary',
        text: summary(
          records.filter(
            (r) =>
              r.request === record.request &&
              (r.kind === 'tool' || r.kind === 'subtool'),
          ),
        ),
      })
    if (record.kind === 'tool' && folds.subcalls.has(record.id))
      rows.push({
        fold: { key: record.id, type: 'subcalls' },
        id: `fold:subcalls:${record.id}`,
        kind: 'summary',
        text: summary(records.filter((r) => r.parent === record.id)),
      })
  }
  return rows
}

/** The text that search matches in a record. */
export function searchText(record: TrajectoryRecord): string {
  const parts = [
    KIND_LABEL[record.kind],
    record.text,
    record.body.thinking,
    record.body.reply,
  ]
  if (record.tool)
    parts.push(
      record.tool.tool,
      record.tool.name,
      record.tool.args,
      resultText(record.tool.resultValue),
      record.tool.callId ?? '',
      JSON.stringify(record.tool.arguments ?? ''),
    )
  return parts.join(' ').toLowerCase()
}

/**
 * The overview spans. In `sequence` mode each record is one unit wide;
 * in `duration` mode spans use real time with idle gaps cut out, and
 * records without a start are left out.
 */
export function spansOf(
  records: TrajectoryRecord[],
  mode: TrajectoryMode,
): { domain: number; spans: TrajectorySpan[] } {
  if (mode === 'sequence')
    return {
      domain: records.length,
      spans: records.map((r, i) => ({
        end: i + 1,
        id: r.id,
        lane: LANE[r.kind],
        start: i,
      })),
    }
  const timed = records.filter((r) => r.startedAt !== null)
  const intervals = timed
    .map((r) => [r.startedAt!, Math.max(r.startedAt!, r.endedAt ?? 0)])
    .sort((a, b) => a[0] - b[0])
  const segments: number[][] = []
  for (const [s, e] of intervals) {
    const last = segments[segments.length - 1]
    if (last && s <= last[1]) last[1] = Math.max(last[1], e)
    else segments.push([s, e])
  }
  const offsets: number[] = []
  let total = 0
  for (const [s, e] of segments) {
    offsets.push(total)
    total += e - s
  }
  const position = (t: number) => {
    let i = segments.length - 1
    while (i > 0 && segments[i][0] > t) i -= 1
    const [s, e] = segments[i]
    return offsets[i] + Math.min(Math.max(t - s, 0), e - s)
  }
  return {
    domain: total,
    spans: timed.map((r) => {
      const start = position(r.startedAt!)
      const end =
        r.endedAt === null ? start : position(Math.max(r.endedAt, r.startedAt!))
      return { end, id: r.id, lane: LANE[r.kind], start }
    }),
  }
}

function at(e: AgentTaskEvent): number {
  return Date.parse(e.at)
}

function calls(n: number): string {
  return `${n} ${n === 1 ? 'tool call' : 'tool calls'}`
}

/**
 * The model of a request runs from the end of the work before it until
 * its first tool call starts, or until its usage report.
 */
function finishRequest(
  request: TrajectoryRequest,
  records: TrajectoryRecord[],
  byId: Map<string, TrajectoryRecord>,
  live: boolean,
) {
  const a = byId.get(request.assistant)!
  a.text = preview(a.body.reply || a.body.thinking)
  const tools = records.filter(
    (r) => r.request === request.number && r.kind === 'tool',
  )
  const starts = tools
    .map((r) => r.startedAt)
    .filter((t): t is number => t !== null)
  const firstTool = starts.length ? Math.min(...starts) : null
  const turnAts = a.events.filter((e) => e.type === 'turn').map(at)
  const lastTurn = turnAts.length ? Math.max(...turnAts) : null
  const usageAt = request.usage ? at(request.usage) : null
  let end: null | number = null
  if (firstTool !== null)
    end = usageAt === null ? firstTool : Math.min(usageAt, firstTool)
  else if (usageAt !== null)
    end = lastTurn === null ? usageAt : Math.min(usageAt, lastTurn)
  else if (!live && lastTurn !== null) end = lastTurn
  if (!request.usage && !live) request.status = 'completed'
  if (a.startedAt === null)
    a.startedAt = end ?? (a.events.length ? at(a.events[0]) : null)
  if (end !== null && a.startedAt !== null && end < a.startedAt)
    a.startedAt = end
  a.endedAt = end
  request.startedAt = a.startedAt
  const toolEnds = tools.map((r) => r.endedAt)
  request.endedAt =
    end === null || toolEnds.includes(null)
      ? null
      : Math.max(end, ...(toolEnds as number[]))
}

function instant(
  e: AgentTaskEvent,
  kind: TrajectoryKind,
  text: string,
  turn: number,
): TrajectoryRecord {
  return {
    body: { reply: '', thinking: '' },
    endedAt: at(e),
    error: false,
    events: [e],
    id: e.event_id,
    kind,
    parent: null,
    request: null,
    seqs: [e.seq],
    startedAt: at(e),
    step: null,
    text,
    tool: null,
    turn,
  }
}

function join(a: string, b: string): string {
  return a ? `${a}\n\n${b}` : b
}

function lineFor(e: AgentTaskEvent): string {
  const p = e.payload
  switch (e.type) {
    case 'secret.resolution':
      return `Secret ${String(p.action ?? 'resolved')}: ${String(p.reference ?? p.purpose ?? '')}`
    case 'session.closed':
      return 'Session closed'
    case 'session.opened':
      return 'Session opened'
    case 'task.created':
      return 'Task created'
    case 'todos.updated':
      return 'Plan updated'
  }
  return systemText(e)
}

function resultText(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

/** The subagent tool calls under a call, flattened in start order. */
function subcalls(entry: TimelineEntry): TimelineEntry[] {
  const out: TimelineEntry[] = []
  const walk = (e: TimelineEntry) => {
    for (const child of e.children) {
      if (!child.event || child.event.type === 'tool.called') out.push(child)
      walk(child)
    }
  }
  walk(entry)
  return out.sort((a, b) => a.seq - b.seq)
}

function summary(records: TrajectoryRecord[]): string {
  const names = [...new Set(records.map((r) => r.tool?.name ?? ''))].filter(
    Boolean,
  )
  return `${calls(records.length)} · ${names.join(', ')}`
}

function toolRecord(
  entry: TimelineEntry,
  kind: 'subtool' | 'tool',
  parent: null | string,
  request: TrajectoryRequest,
  turn: number,
): TrajectoryRecord {
  const e = entry.event
  const p = e?.payload ?? {}
  const tool = typeof p.tool === 'string' ? p.tool : 'Agent'
  const duration = typeof p.duration_ms === 'number' ? p.duration_ms : null
  const end = e ? at(e) : null
  const childStarts = entry.children.flatMap((c) =>
    c.event ? [at(c.event)] : [],
  )
  const start =
    end !== null
      ? end - (duration ?? 0)
      : childStarts.length
        ? Math.min(...childStarts)
        : null
  const args = isRecord(p.arguments) ? p.arguments : {}
  const summaryText = toolSummary(tool, args)
  return {
    body: { reply: '', thinking: '' },
    endedAt: end,
    error: isError(entry),
    events: e ? [e] : [],
    id: entry.id,
    kind,
    parent,
    request: request.number,
    seqs: e ? [e.seq] : [],
    startedAt: start,
    step: request.step,
    text: `${toolLabel(tool)} ${summaryText}`,
    tool: {
      args: summaryText,
      arguments: p.arguments,
      callId: entry.parentOf,
      durationMs: duration,
      name: toolLabel(tool),
      result: e ? preview(resultText(p.result)) : '',
      resultValue: p.result,
      tool,
    },
    turn,
  }
}

function turnsOf(records: TrajectoryRecord[]): TrajectoryTurn[] {
  const turns: TrajectoryTurn[] = []
  for (const record of records) {
    let t = turns.find((x) => x.number === record.turn)
    if (!t) {
      t = { first: record.id, number: record.turn, steps: 0, toolCalls: 0 }
      turns.push(t)
    }
    if (record.kind === 'assistant') t.steps += 1
    if (record.kind === 'tool' || record.kind === 'subtool') t.toolCalls += 1
  }
  for (const t of turns) {
    const first = records.find(
      (r) => r.turn === t.number && r.kind !== 'system',
    )
    if (first) t.first = first.id
  }
  return turns
}
