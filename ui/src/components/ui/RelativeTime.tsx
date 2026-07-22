import { formatDistanceToNow } from 'date-fns'

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { absTime, formatRelativeDate, relTime } from '@/lib/formatDate'
import { cn } from '@/lib/utils'

interface RelativeTimeProps {
  className?: string
  /** Show a tooltip with the full absolute timestamp on hover. Defaults to true. */
  tooltip?: boolean
  /** ISO string or millisecond timestamp. */
  value?: null | number | string
  /**
   * Controls verbosity of the relative time display.
   * - "narrow": "4d"
   * - "short" (default): "4d ago"
   * - "long": "about 4 days ago"
   */
  variant?: RelativeTimeVariant
}

type RelativeTimeVariant = 'long' | 'narrow' | 'short'

export function RelativeTime({
  className,
  tooltip = true,
  value,
  variant = 'short',
}: RelativeTimeProps) {
  if (value == null) return <span className={cn(className)}>—</span>

  const isoString =
    typeof value === 'number' ? new Date(value).toISOString() : value
  const displayText = formatValue(value, variant)
  const absoluteText = absTime(value)

  const timeEl = (
    <time
      className={cn(className)}
      dateTime={isoString}
      title={tooltip ? undefined : absoluteText}
    >
      {displayText}
    </time>
  )

  if (!tooltip) return timeEl

  return (
    <TooltipProvider delayDuration={250}>
      <Tooltip>
        <TooltipTrigger asChild>{timeEl}</TooltipTrigger>
        <TooltipContent>{absoluteText}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

function formatValue(
  value: number | string,
  variant: RelativeTimeVariant,
): string {
  try {
    if (variant === 'narrow') return relTime(value)
    if (variant === 'long') {
      return formatDistanceToNow(new Date(value), { addSuffix: true })
    }
    return formatRelativeDate(
      typeof value === 'number' ? new Date(value).toISOString() : value,
    )
  } catch {
    return '—'
  }
}
