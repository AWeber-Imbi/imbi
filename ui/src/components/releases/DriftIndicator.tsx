import { CircleSlash, Package } from 'lucide-react'

import { IconTooltip } from '@/components/ui/tooltip'
import { commitDrifted } from '@/lib/deployment-drift'
import { cn } from '@/lib/utils'

interface DriftIndicatorProps {
  /** Raw per-commit verdict: `true`, `null`, and absent all render as
   *  drifted — the rule fails closed on unanswered commits. */
  drift: boolean | null | undefined
}

/**
 * Per-commit drift marker: amber package icon when the commit drifted
 * (or CI never answered), muted circle-slash when CI explicitly
 * answered `false`. Distinct shapes and one colour, so the two states
 * differ on both axes. Hovering names the state in words. Renders as
 * its own fixed-width (`w-5`) column so shas align down a commit list.
 */
export function DriftIndicator({ drift }: DriftIndicatorProps) {
  const drifted = commitDrifted({ drift_detected: drift })
  const label = drifted ? 'Drift Detected' : 'No Drift Detected'
  const Icon = drifted ? Package : CircleSlash
  return (
    <IconTooltip label={label}>
      <span
        aria-label={label}
        className={cn(
          'flex w-5 shrink-0 items-center justify-center',
          drifted ? 'text-warning' : 'text-tertiary',
        )}
        role="img"
      >
        <Icon size={15} strokeWidth={1.5} />
      </span>
    </IconTooltip>
  )
}
