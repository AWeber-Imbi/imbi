import type { AgentTaskEvent } from '@/types'

import type { Trajectory } from './trajectoryModel'

export interface ModelUsage {
  cacheRead: number
  cacheWrite: number
  calls: number
  cost: null | number
  input: number
  model: string
  output: number
}

export interface TaskActivity {
  failedCalls: number
  modelMs: number
  outputPerSecond: null | number
  requests: number
  toolCalls: number
  toolMs: number
  turns: number
}

export interface TaskStats {
  activity: TaskActivity
  usage: TaskUsage
}

export interface TaskUsage {
  cacheHit: null | number
  cacheRead: number
  cacheWrite: number
  cost: null | number
  input: number
  models: ModelUsage[]
  output: number
  total: number
}

export function taskActivity(
  trajectory: Trajectory,
  output: number,
): TaskActivity {
  const modelMs = trajectory.records
    .filter((r) => r.kind === 'assistant')
    .reduce((n, r) => n + span(r.startedAt, r.endedAt), 0)
  const tools = trajectory.records.filter((r) => r.kind === 'tool')
  const timed = trajectory.subrequests.length
    ? trajectory.requests.reduce(
        (n, r) => n + num(r.usage?.payload.tokens_out),
        0,
      )
    : output
  return {
    failedCalls: tools.filter((r) => r.error).length,
    modelMs,
    outputPerSecond: modelMs > 0 && timed > 0 ? timed / (modelMs / 1000) : null,
    requests: trajectory.requests.length + trajectory.subrequests.length,
    toolCalls: tools.length,
    toolMs: tools.reduce((n, r) => n + span(r.startedAt, r.endedAt), 0),
    turns: trajectory.turns.length,
  }
}

export function taskStats(
  events: AgentTaskEvent[],
  trajectory: Trajectory,
): TaskStats {
  const usage = taskUsage(events)
  return { activity: taskActivity(trajectory, usage.output), usage }
}

export function taskUsage(events: AgentTaskEvent[]): TaskUsage {
  const byModel = new Map<string, ModelUsage>()
  for (const e of events) {
    if (e.type !== 'usage.reported') continue
    const p = e.payload
    const model = String(p.model_id ?? 'Unknown model')
    const m = byModel.get(model) ?? {
      cacheRead: 0,
      cacheWrite: 0,
      calls: 0,
      cost: null,
      input: 0,
      model,
      output: 0,
    }
    m.calls++
    m.input += num(p.tokens_in)
    m.output += num(p.tokens_out)
    m.cacheRead += num(p.cache_read_tokens)
    m.cacheWrite += num(p.cache_write_tokens)
    if (p.cost != null) m.cost = (m.cost ?? 0) + num(p.cost)
    byModel.set(model, m)
  }
  const models = [...byModel.values()].sort((a, b) => tokensOf(b) - tokensOf(a))
  const sum = (pick: (m: ModelUsage) => number) =>
    models.reduce((n, m) => n + pick(m), 0)
  const input = sum((m) => m.input)
  const cacheRead = sum((m) => m.cacheRead)
  const cacheWrite = sum((m) => m.cacheWrite)
  const output = sum((m) => m.output)
  const prompt = input + cacheRead + cacheWrite
  const priced = models.filter((m) => m.cost !== null)
  return {
    cacheHit: prompt > 0 ? cacheRead / prompt : null,
    cacheRead,
    cacheWrite,
    cost: priced.length ? sum((m) => m.cost ?? 0) : null,
    input,
    models,
    output,
    total: prompt + output,
  }
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

function tokensOf(m: ModelUsage): number {
  return m.input + m.output + m.cacheRead + m.cacheWrite
}
