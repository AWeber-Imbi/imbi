import {
  Activity,
  GitFork,
  type LucideIcon,
  MessageCircleQuestion,
  ShieldQuestion,
  TriangleAlert,
} from 'lucide-react'

import { cn } from '@/lib/utils'
import type { TicketListItem } from '@/types'

type AgentActivity = NonNullable<TicketListItem['agent_activity']>

const ACTIVITY: Record<
  AgentActivity,
  { className: string; icon: LucideIcon; label: string }
> = {
  approval: {
    className: 'text-warning',
    icon: ShieldQuestion,
    label: 'Agent waits on an approval',
  },
  person: {
    className: 'text-warning',
    icon: MessageCircleQuestion,
    label: 'Agent waits on a person',
  },
  stalled: {
    className: 'text-danger',
    icon: TriangleAlert,
    label: 'Agent stalled: no recent heartbeat',
  },
  subagent: {
    className: 'text-info',
    icon: GitFork,
    label: 'Agent waits on a subagent',
  },
  working: {
    className: 'text-info animate-pulse',
    icon: Activity,
    label: 'Agent is working',
  },
}

/** What the agent of a ticket does now; nothing when it is not active. */
export function AgentActivityIcon({
  activity,
  className,
}: {
  activity?: AgentActivity | null
  className?: string
}) {
  if (!activity) return null
  const { className: color, icon: Icon, label } = ACTIVITY[activity]
  return (
    <span className="flex shrink-0" title={label}>
      <Icon aria-hidden className={cn('size-3', color, className)} />
      <span className="sr-only">{label}</span>
    </span>
  )
}
