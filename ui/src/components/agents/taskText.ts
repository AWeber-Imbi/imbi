import type { TicketEvent, TicketStatus } from '@/types'

import { useAgentList } from './agentQueries'
import { formatTokens, statusLabel, type TaskRequestView } from './taskEvents'

// Text for task log events, shared by the Conversation and Input
// required tabs.

export const RESOLVED: Record<TaskRequestView['status'], string> = {
  answered: 'Answered',
  approved: 'Approved',
  expired: 'Expired',
  open: 'Open',
  rejected: 'Rejected',
  withdrawn: 'Withdrawn',
}

/** One line for an event that is not a turn. */
export function systemText(e: TicketEvent): string {
  const p = e.payload
  switch (e.type) {
    case 'check.reported':
      return `Check ${p.name}: ${p.verdict ?? 'reported'}${p.value != null ? ` (${typeof p.value === 'string' ? p.value : JSON.stringify(p.value)})` : ''}`
    case 'control.changed':
      return `Control ${p.from} → ${p.to} by ${e.actor_id ?? 'system'}`
    case 'custom_fields.changed':
      return `Custom fields changed: ${listText(changedKeys(p.from, p.to))}`
    case 'dependency.added':
      return `Dependency added: ${p.dependent_short_id} waits on ${p.prerequisite_short_id}`
    case 'dependency.removed':
      return `Dependency removed: ${p.dependent_short_id} no longer waits on ${p.prerequisite_short_id}`
    case 'due_date.changed':
      return p.to ? `Due ${p.to}` : 'Due date removed'
    case 'egress.destination_pending':
      return `Network access pending: ${String(p.slug ?? p.name ?? p.hostname ?? 'a destination')}`
    case 'labels.changed':
      return `Labels: ${listText(p.to as string[] | undefined)}`
    case 'outcome.set':
      return `Closed as ${statusLabel({ outcome: String(p.outcome), status: 'closed' }).toLowerCase()}${p.reason ? `: ${String(p.reason).replace(/_/g, ' ')}` : ''}`
    case 'owner.changed':
      return `Owner ${p.from} → ${p.to}`
    case 'parent.changed':
      return p.to
        ? `Moved under ${p.to}`
        : p.from
          ? `Moved from ${p.from} to the root`
          : 'Parent changed'
    case 'phase.changed':
      return `Phase ${p.phase}`
    case 'priority.changed':
      return `Priority ${p.from} → ${p.to}`
    case 'project.associated':
      return `Linked to project ${String(p.project_slug ?? p.project_id)}`
    case 'project.dissociated':
      return `Unlinked from project ${String(p.project_slug ?? p.project_id)}`
    case 'rank.changed':
      return p.after
        ? `Moved in the backlog after ${p.after}`
        : 'Moved to the top of the backlog'
    case 'reopened':
      return `Reopened${p.reason ? `: ${p.reason}` : ''}`
    case 'request.opened':
      return `Asked for ${p.kind === 'approval' ? 'approval' : 'input'}: ${p.title}`
    case 'request.resolved':
      return `${RESOLVED[p.status as TaskRequestView['status']] ?? p.status} by ${p.resolved_by ?? e.actor_id}`
    case 'roles.changed':
      return `Roles: ${listText(Object.entries(p.to ?? {}).map(([r, e]) => `${r} ${String(e)}`))}`
    case 'secret.resolution':
      return `Secret ${String(p.action ?? 'resolved')}: ${String(p.reference ?? p.purpose ?? '')}`
    case 'session.closed':
      return 'Session closed'
    case 'session.opened':
      return 'Session opened'
    case 'state.changed':
      return stateText(String(p.from), String(p.to), p.reason)
    case 'task.created':
    case 'ticket.created':
      return 'Ticket created'
    case 'team.changed':
      return p.to ? 'Team changed' : 'Team removed'
    case 'todos.updated':
      return 'Plan updated'
    case 'type.changed':
      return `Type ${p.from} → ${p.to}`
    case 'usage.reported':
      return `Usage ${p.model_id}: ${formatTokens(Number(p.tokens_in ?? 0))} in, ${formatTokens(Number(p.tokens_out ?? 0))} out${p.cost != null ? `, $${Number(p.cost).toFixed(2)}` : ''}`
    default:
      return words(e.type)
  }
}

/** The agent name for an agent actor id; other ids as they are. */
export function useActorName(orgSlug: string) {
  const { data: agents } = useAgentList(orgSlug)
  return (id: null | string | undefined) =>
    agents?.find((a) => a.id === id)?.name ?? id ?? 'Unknown'
}

const ROUTINE = new Set([
  'control_changed',
  'request_opened',
  'request_resolved',
  'session_closed',
  'session_opened',
])

/** The keys of two value maps whose values are not the same. */
function changedKeys(from: unknown, to: unknown): string[] {
  const a = (from ?? {}) as Record<string, unknown>
  const b = (to ?? {}) as Record<string, unknown>
  return [...new Set([...Object.keys(a), ...Object.keys(b)])]
    .filter((k) => JSON.stringify(a[k]) !== JSON.stringify(b[k]))
    .sort()
}

function listText(values: string[] | undefined): string {
  return values?.length ? values.join(', ') : 'none'
}

function stateText(from: string, to: string, reason: unknown): string {
  const why =
    reason && !ROUTINE.has(String(reason))
      ? `: ${String(reason).replace(/_/g, ' ')}`
      : ''
  return `${stateWord(from, to)}${why}`
}

function stateWord(from: string, to: string): string {
  if (to === 'running') return from === 'queued' ? 'Started' : 'Resumed'
  if (to === 'paused') return 'Paused'
  if (to === 'blocked') return 'Waiting for input'
  if (to === 'queued') return 'Queued'
  if (to === 'closed') return 'Stopped'
  return (
    statusLabel({ status: to as TicketStatus }) ?? `Moved from ${from} to ${to}`
  )
}

function words(type: string): string {
  const text = type.replace(/[._]+/g, ' ').trim()
  return text.charAt(0).toUpperCase() + text.slice(1)
}
