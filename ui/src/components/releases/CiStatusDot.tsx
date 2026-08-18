import {
  Check,
  CircleDashed,
  type LucideIcon,
  Minus,
  TriangleAlert,
  X,
} from 'lucide-react'

import { IconTooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import type { DeploymentCommitCiStatus, ReleaseCiStatus } from '@/types'

interface CiStatusDotProps {
  className?: string
  size?: number
  status: DeploymentCommitCiStatus | null | ReleaseCiStatus | string
}

const MAP: Record<string, { color: string; icon: LucideIcon; title: string }> =
  {
    fail: { color: 'text-danger', icon: X, title: 'CI failed' },
    // A project with no environments has no synced deployment history to
    // read a CI status from. Saying "unknown" there claimed a question
    // had been asked and come back empty when nothing had been asked, so
    // a green build read the same as an unverified one (#211).
    not_applicable: {
      color: 'text-tertiary',
      icon: Minus,
      title: 'No CI status — this project has no environments',
    },
    pass: { color: 'text-success', icon: Check, title: 'CI passed' },
    unknown: {
      color: 'text-tertiary',
      icon: CircleDashed,
      title: 'CI status unknown',
    },
    warn: {
      color: 'text-warning',
      icon: TriangleAlert,
      title: 'CI passed with warnings',
    },
  }

/**
 * A small, colour-independent CI status indicator (icon carries meaning).
 * Hovering names the status in words, through the design-system tooltip
 * rather than a native ``title``.
 */
export function CiStatusDot({
  className,
  size = 14,
  status,
}: CiStatusDotProps) {
  const s = MAP[status ?? 'unknown'] ?? MAP.unknown
  const Icon = s.icon
  return (
    <IconTooltip label={s.title}>
      <span
        aria-label={s.title}
        className={cn(
          'inline-flex shrink-0 items-center justify-center rounded-full border',
          s.color,
          className,
        )}
        role="img"
        style={{ height: size + 2, width: size + 2 }}
      >
        <Icon size={size - 4} strokeWidth={3} />
      </span>
    </IconTooltip>
  )
}
