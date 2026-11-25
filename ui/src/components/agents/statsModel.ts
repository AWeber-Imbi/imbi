import type { Ticket, TicketEvent } from '@/types'

import { TRIGGERS } from './taskEvents'
import {
  isAgentCall,
  preview,
  type Trajectory,
  type TrajectoryRecord,
  type TrajectoryRequest,
} from './trajectoryModel'

export type ContextBasis = 'cumulative' | 'latest'

/** Where the task's time and money went, for the summary. */
export interface StatsBreakdown {
  context: { step: number; turn: number; value: number }[]
  cost: { main: number; subagents: number }
  time: {
    idle: number
    model: number
    other: number
    subagents: number
    tools: number
  }
}

export interface StatsCells {
  cacheHit: null | number
  cacheRead: number
  cacheWrite: number
  context: null | number
  cost: number
  input: number
  modelMs: number
  output: number
  outputPerSecond: null | number
  toolMs: number
  totalMs: null | number
}

/** A step or subagent ranked by cost or time. */
export interface StatsRanked {
  label: string
  step: number
  subagent: null | string
  turn: number
  value: number
}

export interface StatsStep extends StatsCells {
  answer: string
  contextDelta: null | number
  did: string
  number: number
  /** An event of the step, which the trajectory opens it by. */
  seq: null | number
  startedAt: null | number
  subagents: StatsSubagent[]
}

/**
 * A subagent the step started. Its context is its last request's prompt;
 * its model time is an estimate, its run time minus its tool time.
 */
export interface StatsSubagent extends StatsCells {
  description: string
  errors: number
  id: string
  requests: number
  /** The Agent call's event, which the trajectory opens it by. */
  seq: null | number
  startedAt: null | number
  tools: number
  type: string
}

export interface StatsTotals extends StatsCells {
  steps: number
  subagents: number
  turns: number
}

export interface StatsTurn extends StatsCells {
  contextDelta: null | number
  number: number
  /** The first event of the turn, which the conversation shows it by. */
  seq: null | number
  steps: StatsStep[]
  trigger: { badge: boolean; text: string }
}

export interface TaskStatistics {
  breakdown: StatsBreakdown
  costliest: StatsRanked[]
  slowest: StatsRanked[]
  totals: StatsTotals
  turns: StatsTurn[]
}

/**
 * The steps are the main agent's model requests. A subagent's requests
 * have their own context, so they stay out of the steps, the context
 * and its deltas; each step lists the subagents its Agent calls started.
 * Their tokens and cost still count in the task total.
 */
export function taskStatistics(
  task: Ticket,
  trajectory: Trajectory,
  basis: ContextBasis,
): TaskStatistics {
  const byId = new Map(trajectory.records.map((r) => [r.id, r]))
  const toolsOf = new Map<number, TrajectoryRecord[]>()
  const userOf = new Map<number, TrajectoryRecord>()
  const seqOf = new Map<number, number>()
  const childrenOf = new Map<string, TrajectoryRecord[]>()
  for (const r of trajectory.records) {
    if (r.parent !== null) {
      const list = childrenOf.get(r.parent) ?? []
      list.push(r)
      childrenOf.set(r.parent, list)
    }
    if (r.kind === 'tool' && r.request !== null) {
      const list = toolsOf.get(r.request) ?? []
      list.push(r)
      toolsOf.set(r.request, list)
    }
    if (r.kind === 'user' && !userOf.has(r.turn)) userOf.set(r.turn, r)
    for (const e of r.events)
      if (e.type !== 'usage.reported')
        seqOf.set(r.turn, Math.min(e.seq, seqOf.get(r.turn) ?? e.seq))
  }
  for (const request of trajectory.requests)
    if (!seqOf.has(request.turn) && request.usage)
      seqOf.set(request.turn, request.usage.seq)
  const groups = new Map<number, StatsStep[]>()
  const time = { idle: 0, model: 0, other: 0, subagents: 0, tools: 0 }
  for (const request of trajectory.requests) {
    const tools = toolsOf.get(request.number) ?? []
    const step = stepOf(request, tools, byId, childrenOf)
    time.model += step.modelMs
    time.subagents += busy(tools.filter(isAgentCall))
    time.tools += busy(tools.filter((r) => !isAgentCall(r)))
    const list = groups.get(request.turn) ?? []
    list.push(step)
    groups.set(request.turn, list)
  }
  const turns: StatsTurn[] = []
  let lastTurnContext: null | number = null
  for (const [number, steps] of [...groups].sort((a, b) => a[0] - b[0])) {
    let last: null | number = null
    for (const step of steps) {
      if (step.context === null) continue
      step.contextDelta = last === null ? null : step.context - last
      last = step.context
    }
    const cells = sumCells(steps, basis)
    turns.push({
      ...cells,
      contextDelta:
        lastTurnContext === null || cells.context === null
          ? null
          : cells.context - lastTurnContext,
      number,
      seq: seqOf.get(number) ?? null,
      steps,
      trigger: triggerOf(task, number, userOf.get(number)),
    })
    if (cells.context !== null) lastTurnContext = cells.context
  }
  const all = turns.flatMap((t) => t.steps)
  const totals = sumCells(all, 'cumulative')
  const sub = trajectory.subrequests.map((s) => usageOf(s.usage))
  const plus = (main: number, pick: (u: (typeof sub)[number]) => number) =>
    sub.reduce((n, u) => n + pick(u), main)
  const input = plus(totals.input, (u) => u.input)
  const cacheRead = plus(totals.cacheRead, (u) => u.cacheRead)
  const cacheWrite = plus(totals.cacheWrite, (u) => u.cacheWrite)
  const totalMs = turns.reduce((n, turn) => n + (turn.totalMs ?? 0), 0)
  time.other = Math.max(0, totalMs - time.model - time.tools - time.subagents)
  if (task.closed_at)
    time.idle = Math.max(
      0,
      Date.parse(task.closed_at) - Date.parse(task.created_at) - totalMs,
    )
  const ranked = turns.flatMap(({ number: turn, steps }) =>
    steps.flatMap((step) => [
      { cells: step as StatsCells, label: step.did, step, sub: null, turn },
      ...step.subagents.map((s) => ({
        cells: s as StatsCells,
        label: s.description,
        step,
        sub: s.id,
        turn,
      })),
    ]),
  )
  const top = (
    pick: (c: StatsCells) => number,
    keep: (r: (typeof ranked)[number]) => boolean = () => true,
  ) =>
    ranked
      .filter(keep)
      .map(({ cells, label, step, sub: subagent, turn }) => ({
        label: label || `Step ${step.number}`,
        step: step.number,
        subagent,
        turn,
        value: pick(cells),
      }))
      .filter((r) => r.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 5)
  const subCost = sub.reduce((n, u) => n + u.cost, 0)
  const mainCost = all.reduce((n, s) => n + s.cost, 0)
  return {
    breakdown: {
      context: turns.flatMap((t) =>
        t.steps.flatMap((s) =>
          s.context === null
            ? []
            : [{ step: s.number, turn: t.number, value: s.context }],
        ),
      ),
      cost: { main: mainCost, subagents: subCost },
      time,
    },
    costliest: top((c) => c.cost),
    slowest: top(
      (c) => c.totalMs ?? 0,
      (r) => r.sub !== null || !r.step.subagents.length,
    ),
    totals: {
      ...totals,
      cacheHit: hit(cacheRead, input + cacheRead + cacheWrite),
      cacheRead,
      cacheWrite,
      cost: mainCost + subCost,
      input,
      output: plus(totals.output, (u) => u.output),
      steps: all.length,
      subagents: all.reduce((n, s) => n + s.subagents.length, 0),
      totalMs,
      turns: turns.length,
    },
    turns,
  }
}

/** How long at least one of the records was running. */
function busy(records: TrajectoryRecord[]): number {
  const spans = records
    .flatMap((r) =>
      r.startedAt !== null && r.endedAt !== null && r.endedAt > r.startedAt
        ? [[r.startedAt, r.endedAt] as const]
        : [],
    )
    .sort((a, b) => a[0] - b[0])
  let total = 0
  let end = -Infinity
  for (const [start, stop] of spans) {
    if (stop <= end) continue
    total += stop - Math.max(start, end)
    end = stop
  }
  return total
}

function didText(tools: TrajectoryRecord[], answer: string): string {
  if (!tools.length) return answer ? preview(answer) : ''
  const counts = new Map<string, number>()
  const agents = tools.filter(isAgentCall)
  for (const r of tools) {
    if (isAgentCall(r)) continue
    const name = r.tool?.name ?? 'tool'
    counts.set(name, (counts.get(name) ?? 0) + 1)
  }
  const did = [...counts].map(([name, n]) => (n > 1 ? `${name} ×${n}` : name))
  if (agents.length === 1) did.push('1 subagent')
  else if (agents.length > 1) {
    const parallel =
      busy(agents) <
      agents.reduce((n, r) => n + span(r.startedAt, r.endedAt), 0)
    did.push(`${agents.length} subagents${parallel ? ' in parallel' : ''}`)
  }
  return did.join(', ')
}

function hit(read: number, prompt: number): null | number {
  return prompt > 0 ? read / prompt : null
}

function num(v: unknown): number {
  if (typeof v === 'number') return v
  if (typeof v === 'string' && v.trim() !== '') {
    const n = Number(v)
    return Number.isFinite(n) ? n : 0
  }
  return 0
}

function span(start: null | number, end: null | number): number {
  return start !== null && end !== null && end > start ? end - start : 0
}

function speed(output: number, ms: number): null | number {
  return ms > 0 && output > 0 ? output / (ms / 1000) : null
}

function stepOf(
  request: TrajectoryRequest,
  tools: TrajectoryRecord[],
  byId: Map<string, TrajectoryRecord>,
  childrenOf: Map<string, TrajectoryRecord[]>,
): StatsStep {
  const u = usageOf(request.usage)
  const assistant = byId.get(request.assistant)
  const answer = assistant?.body.reply ?? ''
  const modelMs = assistant ? span(assistant.startedAt, assistant.endedAt) : 0
  const ends = [request.endedAt, ...tools.map((r) => r.endedAt)].filter(
    (t): t is number => t !== null,
  )
  const prompt = u.input + u.cacheRead + u.cacheWrite
  return {
    answer,
    cacheHit: hit(u.cacheRead, prompt),
    cacheRead: u.cacheRead,
    cacheWrite: u.cacheWrite,
    context: u.reported ? prompt : null,
    contextDelta: null,
    cost: u.cost,
    did: didText(tools, answer),
    input: u.input,
    modelMs,
    number: request.step,
    output: u.output,
    outputPerSecond: speed(u.output, modelMs),
    seq: assistant?.seqs[0] ?? request.usage?.seq ?? null,
    startedAt: request.startedAt,
    subagents: tools
      .flatMap((r) => subagentOf(r, childrenOf.get(r.id) ?? []))
      .sort((a, b) => (a.startedAt ?? 0) - (b.startedAt ?? 0)),
    toolMs: busy(tools),
    totalMs:
      request.startedAt !== null && ends.length
        ? span(request.startedAt, Math.max(...ends))
        : null,
  }
}

function subagentOf(
  record: TrajectoryRecord,
  children: TrajectoryRecord[],
): StatsSubagent[] {
  const s = record.subagent
  if (!s) return []
  const reports = record.events.filter((e) => e.type === 'usage.reported')
  const last = reports.length ? usageOf(reports[reports.length - 1]) : null
  const u = s.usage
  const totalMs =
    record.startedAt !== null && record.endedAt !== null
      ? span(record.startedAt, record.endedAt)
      : null
  const toolMs = busy(children)
  const modelMs = totalMs === null ? 0 : Math.max(0, totalMs - toolMs)
  return [
    {
      cacheHit: hit(u.cacheRead, u.input + u.cacheRead + u.cacheWrite),
      cacheRead: u.cacheRead,
      cacheWrite: u.cacheWrite,
      context: last ? last.input + last.cacheRead + last.cacheWrite : null,
      cost: u.cost,
      description: s.description || 'Subagent',
      errors: s.errors,
      id: record.id,
      input: u.input,
      modelMs,
      output: u.output,
      outputPerSecond: speed(u.output, modelMs),
      requests: u.requests,
      seq:
        record.events.find((e) => e.type === 'tool.called')?.seq ??
        record.seqs[0] ??
        null,
      startedAt: record.startedAt,
      toolMs,
      tools: s.steps,
      totalMs,
      type: s.type,
    },
  ]
}

function sumCells(steps: StatsStep[], basis: ContextBasis): StatsCells {
  const sum = (pick: (s: StatsStep) => number) =>
    steps.reduce((n, s) => n + pick(s), 0)
  const measured = steps.filter((s) => s.context !== null)
  const latest = basis === 'latest' ? measured[measured.length - 1] : undefined
  const prompt = latest ? [latest] : basis === 'latest' ? [] : steps
  const input = prompt.reduce((n, s) => n + s.input, 0)
  const cacheRead = prompt.reduce((n, s) => n + s.cacheRead, 0)
  const cacheWrite = prompt.reduce((n, s) => n + s.cacheWrite, 0)
  const output = sum((s) => s.output)
  const modelMs = sum((s) => s.modelMs)
  const starts = steps
    .map((s) => s.startedAt)
    .filter((t): t is number => t !== null)
  const ends = steps
    .map((s) =>
      s.startedAt !== null && s.totalMs !== null
        ? s.startedAt + s.totalMs
        : null,
    )
    .filter((t): t is number => t !== null)
  return {
    cacheHit: hit(cacheRead, input + cacheRead + cacheWrite),
    cacheRead,
    cacheWrite,
    context: !measured.length
      ? null
      : latest
        ? latest.context
        : measured.reduce((n, s) => n + (s.context ?? 0), 0),
    cost: sum((s) => s.cost + s.subagents.reduce((n, a) => n + a.cost, 0)),
    input,
    modelMs,
    output,
    outputPerSecond: speed(output, modelMs),
    toolMs: sum((s) => s.toolMs),
    totalMs:
      starts.length && ends.length
        ? span(Math.min(...starts), Math.max(...ends))
        : null,
  }
}

function triggerOf(
  task: Ticket,
  turn: number,
  user: TrajectoryRecord | undefined,
): StatsTurn['trigger'] {
  const kind = task.origin?.kind as keyof typeof TRIGGERS | undefined
  if (turn === 1 && kind && kind !== 'human')
    return { badge: true, text: TRIGGERS[kind]?.label ?? 'Automation' }
  if (user?.text) return { badge: false, text: user.text }
  return { badge: true, text: turn === 1 ? 'Manual' : 'Resumed' }
}

function usageOf(e: null | TicketEvent) {
  const p = e?.payload ?? {}
  return {
    cacheRead: num(p.cache_read_tokens),
    cacheWrite: num(p.cache_write_tokens),
    cost: num(p.cost),
    input: num(p.tokens_in),
    output: num(p.tokens_out),
    reported:
      p.tokens_in != null ||
      p.cache_read_tokens != null ||
      p.cache_write_tokens != null,
  }
}
