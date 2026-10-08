import type { Agent, AgentUsage, AgentUsageTotals } from '@/types'

export interface CapStatus {
  cap: number
  level: 'over' | 'warning'
  share: number
  spent: number
}

type Counts = Omit<AgentUsageTotals, 'agent_id' | 'cost'> & { cost: number }

/** Cache reads as a share of input tokens, or null with no input. */
export function cacheHit(t: AgentUsageTotals | Counts): null | number {
  const input = inputTokens(t)
  return input > 0 ? t.cache_read_tokens / input : null
}

/**
 * The advisory monthly cost cap of an agent: `warning` from 80% of the
 * cap, `over` from 100%. Null below 80%, or when the agent has no cap.
 * The cap never stops an agent (ADR 0020).
 */
export function capStatus(agent: Agent, spent: number): CapStatus | null {
  const raw = agent.settings?.monthly_cost_cap
  const cap = raw == null ? NaN : Number(raw)
  if (!(cap > 0)) return null
  const share = spent / cap
  if (share < 0.8) return null
  return { cap, level: share >= 1 ? 'over' : 'warning', share, spent }
}

/** One value for each day, from the day rows of the usage response. */
export function dailyValues(
  usage: AgentUsage,
  value: (row: AgentUsage['days'][number]) => number,
  agentIds?: Set<string>,
): number[] {
  const byDay = new Map<string, number>()
  for (const row of usage.days) {
    if (agentIds && !agentIds.has(row.agent_id)) continue
    byDay.set(row.day, (byDay.get(row.day) ?? 0) + value(row))
  }
  return daysBetween(usage.start, usage.end).map((d) => byDay.get(d) ?? 0)
}

/** Every UTC day from `start` to `end` (YYYY-MM-DD), both included. */
export function daysBetween(start: string, end: string): string[] {
  const days: string[] = []
  const day = new Date(`${start}T00:00:00Z`)
  const last = new Date(`${end}T00:00:00Z`)
  while (day <= last) {
    days.push(day.toISOString().slice(0, 10))
    day.setUTCDate(day.getUTCDate() + 1)
  }
  return days
}

export function formatCount(n: number): string {
  return n.toLocaleString('en-US')
}

/** A short day label, such as "Oct 8". */
export function formatDay(day: string): string {
  return new Date(`${day}T00:00:00Z`).toLocaleDateString('en-US', {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  })
}

export function formatShare(share: null | number): string {
  return share == null ? '—' : `${Math.round(share * 100)}%`
}

/** Input tokens: uncached input plus cache reads and cache writes. */
export function inputTokens(t: AgentUsageTotals | Counts): number {
  return t.tokens_in + t.cache_read_tokens + t.cache_write_tokens
}

/** The sum of rows. A task is of one agent, so `tasks` adds up. */
export function sumTotals(rows: AgentUsageTotals[]): Counts {
  const total: Counts = {
    cache_read_tokens: 0,
    cache_write_tokens: 0,
    cost: 0,
    tasks: 0,
    tokens_in: 0,
    tokens_out: 0,
  }
  for (const row of rows) {
    total.cache_read_tokens += row.cache_read_tokens
    total.cache_write_tokens += row.cache_write_tokens
    total.cost += Number(row.cost)
    total.tasks += row.tasks
    total.tokens_in += row.tokens_in
    total.tokens_out += row.tokens_out
  }
  return total
}
