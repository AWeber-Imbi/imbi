import type { AgentTaskEvent } from '@/types'

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
}

/** One line for an event that is not a turn. */
export function systemText(e: AgentTaskEvent): string {
  const p = e.payload
  switch (e.type) {
    case 'check.reported':
      return `Check ${p.name}: ${p.verdict ?? 'reported'}${p.value != null ? ` (${typeof p.value === 'string' ? p.value : JSON.stringify(p.value)})` : ''}`
    case 'control.changed':
      return `Control ${p.from} → ${p.to} by ${e.actor_id ?? 'system'}`
    case 'outcome.set':
      return `Closed as ${statusLabel({ outcome: String(p.outcome), status: 'closed' }).toLowerCase()}${p.reason ? `: ${String(p.reason).replace(/_/g, ' ')}` : ''}`
    case 'owner.changed':
      return `Owner ${p.from} → ${p.to}`
    case 'phase.changed':
      return `Phase ${p.phase}`
    case 'request.opened':
      return `Asked for ${p.kind === 'approval' ? 'approval' : 'input'}: ${p.title}`
    case 'request.resolved':
      return `${RESOLVED[p.status as TaskRequestView['status']] ?? p.status} by ${p.resolved_by ?? e.actor_id}`
    case 'state.changed':
      return stateText(String(p.from), String(p.to))
    case 'usage.reported':
      return `Usage ${p.model_id}: ${formatTokens(Number(p.tokens_in ?? 0))} in, ${formatTokens(Number(p.tokens_out ?? 0))} out${p.cost != null ? `, $${Number(p.cost).toFixed(2)}` : ''}`
    default:
      return e.type
  }
}

/** The agent name for an agent actor id; other ids as they are. */
export function useActorName(orgSlug: string) {
  const { data: agents } = useAgentList(orgSlug)
  return (id: null | string | undefined) =>
    agents?.find((a) => a.id === id)?.name ?? id ?? 'Unknown'
}

function stateText(from: string, to: string): string {
  if (to === 'running') return from === 'queued' ? 'Started' : 'Resumed'
  if (to === 'paused') return 'Paused'
  if (to === 'blocked') return 'Waiting for input'
  if (to === 'queued') return 'Queued'
  if (to === 'closed') return 'Stopped'
  return `Moved from ${from} to ${to}`
}
