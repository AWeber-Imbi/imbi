import type { AgentTask, AgentTaskEvent } from '@/types'

import { TRIGGERS } from './taskEvents'
import {
  preview,
  type Trajectory,
  type TrajectoryRecord,
  type TrajectoryRequest,
} from './trajectoryModel'

export type ContextBasis = 'cumulative' | 'latest'

export interface StatsCells {
  cacheHit: null | number
  cacheRead: number
  cacheWrite: number
  context: null | number
  input: number
  modelMs: number
  output: number
  outputPerSecond: null | number
  toolMs: number
  totalMs: null | number
}

export interface StatsStep extends StatsCells {
  answer: string
  contextDelta: null | number
  did: string
  number: number
  startedAt: null | number
  /** The model requests of the subagents that the step started. */
  subrequests: number
}

export interface StatsTotals extends StatsCells {
  steps: number
  subrequests: number
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
  totals: StatsTotals
  turns: StatsTurn[]
}

/**
 * The steps are the main agent's model requests. A subagent's requests
 * have their own context, so they stay out of the steps, the context
 * and its deltas; each step counts the ones its Agent calls started.
 * Their tokens still count in the task total.
 */
export function taskStatistics(
  task: AgentTask,
  trajectory: Trajectory,
  basis: ContextBasis,
): TaskStatistics {
  const byId = new Map(trajectory.records.map((r) => [r.id, r]))
  const toolsOf = new Map<number, TrajectoryRecord[]>()
  const userOf = new Map<number, TrajectoryRecord>()
  const seqOf = new Map<number, number>()
  for (const r of trajectory.records) {
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
  const subrequestsOf = new Map<number, number>()
  for (const s of trajectory.subrequests)
    if (s.request !== null)
      subrequestsOf.set(s.request, (subrequestsOf.get(s.request) ?? 0) + 1)
  const groups = new Map<number, StatsStep[]>()
  for (const request of trajectory.requests) {
    const step = stepOf(
      request,
      toolsOf.get(request.number) ?? [],
      byId,
      subrequestsOf.get(request.number) ?? 0,
    )
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
  return {
    totals: {
      ...totals,
      cacheHit: hit(cacheRead, input + cacheRead + cacheWrite),
      cacheRead,
      cacheWrite,
      input,
      output: plus(totals.output, (u) => u.output),
      steps: all.length,
      subrequests: all.reduce((n, s) => n + s.subrequests, 0),
      totalMs: turns.reduce((n, turn) => n + (turn.totalMs ?? 0), 0),
      turns: turns.length,
    },
    turns,
  }
}

function didText(
  tools: TrajectoryRecord[],
  answer: string,
  subrequests: number,
): string {
  if (!tools.length) return answer ? preview(answer) : ''
  const counts = new Map<string, number>()
  for (const r of tools) {
    const name = r.tool?.name ?? 'tool'
    counts.set(name, (counts.get(name) ?? 0) + 1)
  }
  const did = [...counts]
    .map(([name, n]) => (n > 1 ? `${name} ×${n}` : name))
    .join(', ')
  if (!subrequests) return did
  const noun = subrequests === 1 ? 'subagent request' : 'subagent requests'
  return `${did} · ${subrequests} ${noun}`
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
  subrequests: number,
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
    did: didText(tools, answer, subrequests),
    input: u.input,
    modelMs,
    number: request.step,
    output: u.output,
    outputPerSecond: speed(u.output, modelMs),
    startedAt: request.startedAt,
    subrequests,
    toolMs: tools.reduce((n, r) => n + span(r.startedAt, r.endedAt), 0),
    totalMs:
      request.startedAt !== null && ends.length
        ? span(request.startedAt, Math.max(...ends))
        : null,
  }
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
  task: AgentTask,
  turn: number,
  user: TrajectoryRecord | undefined,
): StatsTurn['trigger'] {
  const kind = task.origin?.kind as keyof typeof TRIGGERS | undefined
  if (turn === 1 && kind && kind !== 'human')
    return { badge: true, text: TRIGGERS[kind]?.label ?? 'Automation' }
  if (user?.text) return { badge: false, text: user.text }
  return { badge: true, text: turn === 1 ? 'Manual' : 'Resumed' }
}

function usageOf(e: AgentTaskEvent | null) {
  const p = e?.payload ?? {}
  return {
    cacheRead: num(p.cache_read_tokens),
    cacheWrite: num(p.cache_write_tokens),
    input: num(p.tokens_in),
    output: num(p.tokens_out),
    reported:
      p.tokens_in != null ||
      p.cache_read_tokens != null ||
      p.cache_write_tokens != null,
  }
}
