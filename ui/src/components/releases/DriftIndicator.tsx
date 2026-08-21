import { CircleSlash, Package } from 'lucide-react'

import { IconTooltip } from '@/components/ui/tooltip'
import { commitDrifted } from '@/lib/deployment-drift'
import { cn } from '@/lib/utils'

interface DriftIndicatorProps {
  className?: string
  /** Raw per-commit verdict: `true`, `null`, and absent all render as
   *  drifted — the rule fails closed on unanswered commits. */
  drift: boolean | null | undefined
  size?: number
}

/**
 * Per-commit drift marker: amber package icon when the commit drifted
 * (or CI never answered), muted circle-slash when CI explicitly
 * answered `false`. Distinct shapes and one colour, so the two states
 * differ on both axes. Hovering names the state in words.
 */
export function DriftIndicator({
  className,
  drift,
  size = 15,
}: DriftIndicatorProps) {
  const drifted = commitDrifted({ drift_detected: drift })
  const label = drifted ? 'Drift Detected' : 'No Drift Detected'
  const Icon = drifted ? Package : CircleSlash
  return (
    <IconTooltip label={label}>
      <span
        aria-label={label}
        className={cn(
          'inline-flex shrink-0 items-center justify-center',
          drifted ? 'text-warning' : 'text-tertiary',
          className,
        )}
        role="img"
      >
        <Icon size={size} strokeWidth={1.5} />
      </span>
    </IconTooltip>
  )
}
