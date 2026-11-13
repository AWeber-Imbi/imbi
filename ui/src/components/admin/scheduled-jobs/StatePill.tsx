import { Badge, type BadgeProps } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { ScheduledRun } from '@/types/scheduler'

import {
  type DisplayState,
  runDisplayState,
  STATE_LABELS,
} from './scheduledJobs'

const VARIANT: Record<DisplayState, BadgeProps['variant']> = {
  busy: 'warning',
  cancelled: 'neutral',
  failed: 'danger',
  never: 'neutral',
  no_effect: 'neutral',
  paused: 'neutral',
  running: 'info',
  skipped: 'neutral',
  succeeded: 'success',
  timed_out: 'danger',
}

const DOT: Record<DisplayState, string> = {
  busy: 'text-amber-border',
  cancelled: 'text-tertiary',
  failed: 'text-danger',
  never: 'text-tertiary',
  no_effect: 'text-tertiary',
  paused: 'text-tertiary',
  running: 'text-info',
  skipped: 'text-tertiary',
  succeeded: 'text-success',
  timed_out: 'text-danger',
}

// The newest runs as dots, oldest on the left.
export function RecentRuns({ runs }: { runs: ScheduledRun[] }) {
  const recent = runs.slice(0, 8).reverse()
  return (
    <span
      aria-label={`Last ${recent.length} runs`}
      className="inline-flex items-center gap-1"
    >
      {recent.map((run) => {
        const state = runDisplayState(run)
        return (
          <span
            className={cn('size-2 rounded-full bg-current', DOT[state])}
            key={run.run_id}
            title={STATE_LABELS[state]}
          />
        )
      })}
    </span>
  )
}

export function StatePill({ state }: { state: DisplayState }) {
  return <Badge variant={VARIANT[state]}>{STATE_LABELS[state]}</Badge>
}
