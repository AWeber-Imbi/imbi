import type { TicketEvent } from '@/types'

import { isError, type TimelineEntry } from './taskTimeline'
import { isRecord } from './toolCalls'

export interface SubagentRun {
  description: string
  end: number
  entry: TimelineEntry
  errors: number
  kind: string
  prompt: string
  result: string
  running: boolean
  start: number
  steps: number
  usage: SubagentUsage
}

export interface SubagentUsage {
  cacheRead: number
  cacheWrite: number
  cost: number
  input: number
  output: number
  requests: number
}

/** A row of the work group: one entry, or subagents that ran at once. */
export type WorkSlot =
  | { entry: TimelineEntry; kind: 'entry' }
  | { kind: 'parallel'; runs: SubagentRun[] }

const EMPTY: SubagentUsage = {
  cacheRead: 0,
  cacheWrite: 0,
  cost: 0,
  input: 0,
  output: 0,
  requests: 0,
}

export function isAgentTool(tool: unknown): boolean {
  return tool === 'Agent' || tool === 'Task'
}

export function isSubagent(entry: TimelineEntry): boolean {
  const e = entry.event
  if (!e) return entry.children.length > 0
  return e.type === 'tool.called' && isAgentTool(e.payload.tool)
}

/**
 * Splits items, kept in display order, into groups whose spans overlap.
 * Overlap is found by start time, so the display order cannot split a
 * group; groups that interleave in display order are merged to stay
 * contiguous.
 */
export function overlapGroups<T>(
  items: readonly T[],
  span: (item: T) => readonly [number, number],
): T[][] {
  const order = items
    .map((_, i) => i)
    .sort((a, b) => span(items[a])[0] - span(items[b])[0])
  const group: number[] = []
  let id = -1
  let until = -Infinity
  for (const i of order) {
    const [start, end] = span(items[i])
    if (start >= until) id += 1
    group[i] = id
    until = Math.max(until, end)
  }
  const last = new Map<number, number>()
  group.forEach((g, i) => last.set(g, i))
  const out: T[][] = []
  let from = 0
  let reach = 0
  for (let i = 0; i < items.length; i += 1) {
    reach = Math.max(reach, last.get(group[i])!)
    if (i === reach) {
      out.push(items.slice(from, i + 1))
      from = i + 1
    }
  }
  return out
}

/** Wall time from the first start to the last end, and the summed run time. */
export function spanOf(runs: SubagentRun[]): { wall: number; work: number } {
  const start = Math.min(...runs.map((r) => r.start))
  const end = Math.max(...runs.map((r) => r.end))
  return {
    wall: end - start,
    work: runs.reduce((n, r) => n + (r.end - r.start), 0),
  }
}

/** A subagent's answer, without the harness's hand-back preamble. */
export function stripHandBack(text: string): string {
  return text.replace(HAND_BACK, '').trim()
}

export function subagentRun(
  entry: TimelineEntry,
  usage: ReadonlyMap<string, SubagentUsage>,
  live: boolean,
): SubagentRun {
  const p = entry.event?.payload ?? {}
  const args = isRecord(p.arguments) ? p.arguments : {}
  const text = (v: unknown) => (typeof v === 'string' ? v : '')
  const times = flat(entry)
    .map((child) => (child.event ? Date.parse(child.event.at) : NaN))
    .filter((t) => !Number.isNaN(t))
  const ms = typeof p.duration_ms === 'number' ? p.duration_ms : null
  const end = entry.event
    ? Date.parse(entry.event.at)
    : live
      ? Date.now()
      : Math.max(...times)
  const start =
    ms === null ? Math.min(...times.filter((t) => t <= end), end) : end - ms
  const calls = flat(entry).filter(
    (child) => !child.event || child.event.type === 'tool.called',
  )
  return {
    description: text(args.description),
    end,
    entry,
    errors: calls.filter(isError).length,
    kind: text(args.subagent_type),
    prompt: typeof p.arguments === 'string' ? p.arguments : text(args.prompt),
    result: answerOf(p.result),
    running: !entry.event && live,
    start,
    steps: calls.length,
    usage: (entry.parentOf && usage.get(entry.parentOf)) || EMPTY,
  }
}

/** The tokens and cost of each subagent, by its Agent call's `call_id`. */
export function subagentUsage(
  events: readonly TicketEvent[],
): Map<string, SubagentUsage> {
  const reports = new Map<string, TicketEvent[]>()
  for (const [e, agent] of usageAgents(events))
    reports.set(agent, [...(reports.get(agent) ?? []), e])
  return new Map([...reports].map(([agent, r]) => [agent, usageOf(r)]))
}

export function sumUsage(runs: SubagentRun[]): SubagentUsage {
  return runs.reduce(
    (acc, r) => ({
      cacheRead: acc.cacheRead + r.usage.cacheRead,
      cacheWrite: acc.cacheWrite + r.usage.cacheWrite,
      cost: acc.cost + r.usage.cost,
      input: acc.input + r.usage.input,
      output: acc.output + r.usage.output,
      requests: acc.requests + r.usage.requests,
    }),
    { ...EMPTY },
  )
}

export function totalTokens(u: SubagentUsage): number {
  return u.input + u.output + u.cacheRead + u.cacheWrite
}

/**
 * The Agent call each subagent usage report belongs to, by `call_id`. A
 * report joins through the `message_id` it shares with the subagent's own
 * events. A subagent's last reply calls no tool, so nothing shares its
 * `message_id`; that report comes right before its Agent call finishes.
 */
export function usageAgents(
  events: readonly TicketEvent[],
): Map<TicketEvent, string> {
  const agentOf = new Map<string, string>()
  const joined = new Set<string>()
  for (const e of events) {
    const id = e.payload.message_id
    if (e.type === 'usage.reported' || typeof id !== 'string') continue
    joined.add(id)
    const parent = e.payload.parent_call_id
    if (typeof parent === 'string') agentOf.set(id, parent)
  }
  const out = new Map<TicketEvent, string>()
  let unjoined: null | TicketEvent = null
  for (const e of [...events].sort((a, b) => a.seq - b.seq)) {
    const p = e.payload
    if (e.type === 'usage.reported') {
      const id = typeof p.message_id === 'string' ? p.message_id : null
      const agent = id === null ? undefined : agentOf.get(id)
      if (agent) out.set(e, agent)
      unjoined = id !== null && !joined.has(id) ? e : null
    } else if (e.type === 'tool.called' && !p.parent_call_id) {
      if (unjoined && isAgentTool(p.tool) && typeof p.call_id === 'string')
        out.set(unjoined, p.call_id)
      unjoined = null
    }
  }
  return out
}

/** The summed tokens and cost of usage reports. */
export function usageOf(reports: readonly TicketEvent[]): SubagentUsage {
  const u = { ...EMPTY }
  for (const { payload: p } of reports) {
    u.input += num(p.tokens_in)
    u.output += num(p.tokens_out)
    u.cacheRead += num(p.cache_read_tokens)
    u.cacheWrite += num(p.cache_write_tokens)
    u.cost += num(p.cost)
    u.requests++
  }
  return u
}

/**
 * The group's entries, with each run of back-to-back subagents whose
 * times overlap folded into one parallel slot.
 */
export function workSlots(
  entries: TimelineEntry[],
  usage: ReadonlyMap<string, SubagentUsage>,
  live: boolean,
): WorkSlot[] {
  const out: WorkSlot[] = []
  let runs: SubagentRun[] = []
  const flush = () => {
    for (const group of overlapGroups(runs, (r) => [r.start, r.end]))
      out.push(
        group.length > 1
          ? { kind: 'parallel', runs: group }
          : { entry: group[0].entry, kind: 'entry' },
      )
    runs = []
  }
  for (const entry of entries) {
    if (entry.event?.type === 'usage.reported') continue
    if (isSubagent(entry)) {
      runs.push(subagentRun(entry, usage, live))
      continue
    }
    flush()
    out.push({ entry, kind: 'entry' })
  }
  flush()
  return out
}

function answerOf(result: unknown): string {
  if (result == null) return ''
  return stripHandBack(
    typeof result === 'string' ? result : JSON.stringify(result),
  )
}

const HAND_BACK = /^\s*\[Subagent hand-back\][\s\S]*?The report follows:\s*/

function flat(entry: TimelineEntry): TimelineEntry[] {
  return entry.children.flatMap((child) => [child, ...flat(child)])
}

function num(v: unknown): number {
  const x = typeof v === 'string' ? Number(v) : v
  return typeof x === 'number' && Number.isFinite(x) ? x : 0
}
