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
}

export interface StatsTotals extends StatsCells {
  steps: number
  turns: number
}

export interface StatsTurn extends StatsCells {
  contextDelta: null | number
  number: number
  steps: StatsStep[]
  trigger: { badge: boolean; text: string }
}

export interface TaskStatistics {
  totals: StatsTotals
  turns: StatsTurn[]
}

export function taskStatistics(
  task: AgentTask,
  trajectory: Trajectory,
  basis: ContextBasis,
): TaskStatistics {
  const byId = new Map(trajectory.records.map((r) => [r.id, r]))
  const groups = new Map<number, StatsStep[]>()
  for (const request of trajectory.requests) {
    const step = stepOf(request, trajectory.records, byId)
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
      steps,
      trigger: triggerOf(task, number, trajectory.records),
    })
    if (cells.context !== null) lastTurnContext = cells.context
  }
  const all = turns.flatMap((t) => t.steps)
  const totals = sumCells(all, 'cumulative')
  return {
    totals: {
      ...totals,
      steps: all.length,
      totalMs: totals.modelMs + totals.toolMs,
      turns: turns.length,
    },
    turns,
  }
}

function didText(tools: TrajectoryRecord[], answer: string): string {
  if (!tools.length) return answer ? preview(answer) : ''
  const counts = new Map<string, number>()
  for (const r of tools) {
    const name = r.tool?.name ?? 'tool'
    counts.set(name, (counts.get(name) ?? 0) + 1)
  }
  return [...counts]
    .map(([name, n]) => (n > 1 ? `${name} ×${n}` : name))
    .join(', ')
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
  records: TrajectoryRecord[],
  byId: Map<string, TrajectoryRecord>,
): StatsStep {
  const u = usageOf(request.usage)
  const tools = records.filter(
    (r) => r.kind === 'tool' && r.request === request.number,
  )
  const answer = byId.get(request.assistant)?.body.reply ?? ''
  const modelMs = span(request.startedAt, request.endedAt)
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
    did: didText(tools, answer),
    input: u.input,
    modelMs,
    number: request.step,
    output: u.output,
    outputPerSecond: speed(u.output, modelMs),
    startedAt: request.startedAt,
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
  const input = sum((s) => s.input)
  const cacheRead = sum((s) => s.cacheRead)
  const cacheWrite = sum((s) => s.cacheWrite)
  const output = sum((s) => s.output)
  const modelMs = sum((s) => s.modelMs)
  const measured = steps.filter((s) => s.context !== null)
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
      : basis === 'latest'
        ? measured[measured.length - 1].context
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
  records: TrajectoryRecord[],
): StatsTurn['trigger'] {
  const kind = task.origin?.kind as keyof typeof TRIGGERS | undefined
  if (turn === 1 && kind && kind !== 'human')
    return { badge: true, text: TRIGGERS[kind]?.label ?? 'Automation' }
  const user = records.find((r) => r.kind === 'user' && r.turn === turn)
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
    reported: e !== null,
  }
}
