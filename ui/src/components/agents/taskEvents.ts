import { CornerDownRight, Play, Timer, Webhook } from 'lucide-react'

import type {
  AgentTaskEvent,
  AgentTaskListItem,
  AgentTaskStatus,
} from '@/types'

// Pure helpers for the Tasks inbox and the task detail. The detail reads
// everything from the event log (ADR 0020), so the requests, the phase
// timeline, the transcript, and the tool calls are folds over events.

export interface InboxGroup {
  id: InboxGroupId
  label: string
  tasks: AgentTaskListItem[]
}

export type InboxGroupId = 'closed' | 'input' | 'queued' | 'running'

export interface PhaseSpan {
  at: string
  /** Milliseconds in the phase; the current phase counts up to `now`. */
  ms: number
  phase: string
}

export interface TaskRequestView {
  answer: null | string
  artifact_digests: null | string[]
  artifacts: unknown[]
  expires_at: null | string
  id: string
  kind: 'approval' | 'feedback'
  opened_at: string
  opened_by: null | string
  options: unknown[]
  resolved_at: null | string
  resolved_by: null | string
  status: 'answered' | 'approved' | 'expired' | 'open' | 'rejected'
  title: string
  why: null | string
}

export interface ToolCallRow {
  depth: number
  event: AgentTaskEvent
}

const GROUPS: { id: InboxGroupId; label: string }[] = [
  { id: 'input', label: 'Human input required' },
  { id: 'running', label: 'Running' },
  { id: 'queued', label: 'Queued' },
  { id: 'closed', label: 'Recently closed' },
]

const GROUP_OF: Record<AgentTaskStatus, InboxGroupId> = {
  blocked: 'input',
  closed: 'closed',
  paused: 'running',
  queued: 'queued',
  running: 'running',
}

/**
 * The inbox group of a task. A task that waits on a person (it has
 * `blocked_since`: it is not closed and a request is open) needs human
 * input whatever its status, also when it is paused.
 */
function groupOf(task: AgentTaskListItem): InboxGroupId {
  return task.blocked_since ? 'input' : GROUP_OF[task.status]
}

/** The event types that the Conversation tab shows (O5). */
const CONVERSATION_TYPES = new Set([
  'control.changed',
  'outcome.set',
  'owner.changed',
  'request.opened',
  'request.resolved',
  'state.changed',
  'turn',
])

/** What started a task, by origin kind. */
export const TRIGGERS = {
  human: { icon: Play, label: 'Manual' },
  schedule: { icon: Timer, label: 'Schedule' },
  task: { icon: CornerDownRight, label: 'Delegation' },
  webhook: { icon: Webhook, label: 'Webhook' },
} as const

const OUTCOME_LABELS: Record<string, string> = {
  cancelled_by_human: 'Cancelled',
  done_acted: 'Completed',
  done_nothing_to_act_on: 'Nothing to do',
  exceeded_ceiling: 'Over budget',
  failed_at_gate: 'Failed',
  failed_external: 'Failed',
  interrupted_by_operator: 'Interrupted',
  no_reason_to_run: 'Not needed',
  partial_capped: 'Partly done',
  refused_rate_ceiling: 'Refused',
  request_expired: 'Request expired',
  superseded: 'Superseded',
  suppressed_duplicate: 'Duplicate',
  unhandled_no_actor: 'Unhandled',
  unmapped_subject: 'Unmapped',
}

const STATUS_LABELS: Record<AgentTaskStatus, string> = {
  blocked: 'Needs input',
  closed: 'Closed',
  paused: 'Paused',
  queued: 'Queued',
  running: 'Running',
}

/** Events in the Conversation tab: turns, with state changes inline. */
export function conversation(events: AgentTaskEvent[]): AgentTaskEvent[] {
  return events.filter((e) => CONVERSATION_TYPES.has(e.type))
}

/** `9m 12s`, `2h 4m`, `3d 2h`: the two largest units. */
export function formatElapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000))
  const units: [string, number][] = [
    ['d', Math.floor(s / 86400)],
    ['h', Math.floor(s / 3600) % 24],
    ['m', Math.floor(s / 60) % 60],
    ['s', s % 60],
  ]
  const first = units.findIndex(([, n]) => n > 0)
  if (first === -1) return '0s'
  return units
    .slice(first, first + 2)
    .filter(([, n]) => n > 0)
    .map(([u, n]) => `${n}${u}`)
    .join(' ')
}

/** `412k`, `1.2M`. */
export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1000) return `${Math.round(n / 1000)}k`
  return String(n)
}

/**
 * The inbox groups that have tasks, in order. The tasks that wait on a
 * person are oldest block first (O2); the closed group is newest close first; the
 * others keep the list order (newest first).
 */
export function groupTasks(tasks: AgentTaskListItem[]): InboxGroup[] {
  const time = (value: null | string | undefined) =>
    value ? Date.parse(value) : 0
  return GROUPS.map(({ id, label }) => {
    const members = tasks.filter((t) => groupOf(t) === id)
    if (id === 'input')
      members.sort((a, b) => time(a.blocked_since) - time(b.blocked_since))
    if (id === 'closed')
      members.sort((a, b) => time(b.closed_at) - time(a.closed_at))
    return { id, label, tasks: members }
  }).filter((g) => g.tasks.length > 0)
}

/** The phases of a task in order, with the time spent in each (F7). */
export function phaseTimeline(
  events: AgentTaskEvent[],
  end: number,
): PhaseSpan[] {
  const changes = events.filter(
    (e) => e.type === 'phase.changed' && typeof e.payload.phase === 'string',
  )
  return changes.map((e, i) => {
    const until = i + 1 < changes.length ? Date.parse(changes[i + 1].at) : end
    return {
      at: e.at,
      ms: Math.max(0, until - Date.parse(e.at)),
      phase: e.payload.phase as string,
    }
  })
}

/**
 * The requests of a task, oldest first, from `request.opened`,
 * `request.resolved`, and `request.expired` events. A request past its
 * `expires_at` is expired even before an event says so.
 */
export function requestsFrom(
  events: AgentTaskEvent[],
  now: number,
): TaskRequestView[] {
  const byId = new Map<string, TaskRequestView>()
  for (const e of events) {
    const p = e.payload
    const id = String(p.request_id ?? '')
    const known = byId.get(id)
    if (e.type === 'request.opened') {
      byId.set(id, {
        answer: null,
        artifact_digests: (p.artifact_digests as null | string[]) ?? null,
        artifacts: (p.artifacts as unknown[]) ?? [],
        expires_at: (p.expires_at as null | string) ?? null,
        id,
        kind: p.kind === 'approval' ? 'approval' : 'feedback',
        opened_at: e.at,
        opened_by: e.actor_id ?? null,
        options: (p.options as unknown[]) ?? [],
        resolved_at: null,
        resolved_by: null,
        status: 'open',
        title: String(p.title ?? ''),
        why: (p.why as null | string) ?? null,
      })
    } else if (e.type === 'request.resolved' && known) {
      known.status = p.status as TaskRequestView['status']
      known.resolved_by = (p.resolved_by as null | string) ?? e.actor_id ?? null
      known.resolved_at = e.at
      known.answer = (p.answer as null | string) ?? null
    } else if (e.type === 'request.expired' && known) {
      known.status = 'expired'
    }
  }
  const requests = [...byId.values()]
  for (const r of requests) {
    if (r.status === 'open' && r.expires_at && Date.parse(r.expires_at) <= now)
      r.status = 'expired'
  }
  return requests
}

/** The badge text of a task: its outcome when closed, else its status. */
export function statusLabel(task: {
  outcome?: null | string
  status: AgentTaskStatus
}): string {
  if (task.status === 'closed' && task.outcome)
    return OUTCOME_LABELS[task.outcome] ?? task.outcome
  return STATUS_LABELS[task.status]
}

/** The badge variant of a task. */
export function statusVariant(task: {
  outcome?: null | string
  status: AgentTaskStatus
}): 'danger' | 'info' | 'neutral' | 'success' | 'warning' {
  if (task.status === 'blocked') return 'warning'
  if (task.status === 'running') return 'info'
  if (task.status !== 'closed') return 'neutral'
  if (task.outcome?.startsWith('done_')) return 'success'
  if (
    task.outcome?.startsWith('failed_') ||
    task.outcome === 'exceeded_ceiling' ||
    task.outcome === 'request_expired'
  )
    return 'danger'
  return 'neutral'
}

/**
 * The tool calls of a task in seq order, each nested call under its
 * parent (N3). `payload.parent_call_id` names the `payload.call_id` of
 * the parent. The harness plan defines these two fields. A call whose
 * parent is not in the log is a top-level row.
 */
export function toolCalls(events: AgentTaskEvent[]): ToolCallRow[] {
  const calls = events.filter((e) => e.type === 'tool.called')
  const idOf = (e: AgentTaskEvent) =>
    typeof e.payload.call_id === 'string' ? e.payload.call_id : null
  const ids = new Set(calls.map(idOf))
  const children = new Map<string, AgentTaskEvent[]>()
  const roots: AgentTaskEvent[] = []
  for (const call of calls) {
    const parent = call.payload.parent_call_id
    if (typeof parent === 'string' && ids.has(parent) && parent !== idOf(call))
      children.set(parent, [...(children.get(parent) ?? []), call])
    else roots.push(call)
  }
  const rows: ToolCallRow[] = []
  const walk = (call: AgentTaskEvent, depth: number) => {
    rows.push({ depth, event: call })
    const id = idOf(call)
    for (const child of (id && children.get(id)) || []) walk(child, depth + 1)
  }
  for (const root of roots) walk(root, 0)
  return rows
}
