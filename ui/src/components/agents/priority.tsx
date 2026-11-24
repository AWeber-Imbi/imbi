import { Badge } from '@/components/ui/badge'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@/components/ui/segmented-control'
import { cn } from '@/lib/utils'
import type { Ticket } from '@/types'

export type Priority = Ticket['priority']

export const PRIORITIES: readonly Priority[] = [
  'low',
  'normal',
  'high',
  'urgent',
]

export const priorityLabel = (p: Priority) => p[0].toUpperCase() + p.slice(1)

const VARIANT = {
  high: 'warning',
  low: 'neutral',
  normal: 'neutral',
  urgent: 'danger',
} as const

/** The priority of a ticket, or nothing for `normal`, the default. */
export function PriorityBadge({ priority }: { priority: Priority }) {
  if (priority === 'normal') return null
  return (
    <Badge className="shrink-0 py-0" variant={VARIANT[priority]}>
      {priorityLabel(priority)}
    </Badge>
  )
}

/** Choose one priority. */
export function PriorityPicker({
  className,
  disabled,
  onChange,
  value,
}: {
  className?: string
  disabled?: boolean
  onChange: (p: Priority) => void
  value: Priority
}) {
  return (
    <SegmentedControl
      ariaLabel="Priority"
      className={cn('font-sans', className)}
      onValueChange={(v) => onChange(v as Priority)}
      value={value}
    >
      {PRIORITIES.map((p) => (
        <SegmentedControlItem disabled={disabled} key={p} value={p}>
          {priorityLabel(p)}
        </SegmentedControlItem>
      ))}
    </SegmentedControl>
  )
}
