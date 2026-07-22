import {
  Check,
  CircleDashed,
  type LucideIcon,
  TriangleAlert,
  X,
} from 'lucide-react'

import { cn } from '@/lib/utils'
import type { DeploymentCommitCiStatus } from '@/types'

interface CiStatusDotProps {
  className?: string
  size?: number
  status: DeploymentCommitCiStatus | null | string
}

const MAP: Record<string, { color: string; icon: LucideIcon; title: string }> =
  {
    fail: { color: 'text-danger', icon: X, title: 'CI failed' },
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

/** A small, colour-independent CI status indicator (icon carries meaning). */
export function CiStatusDot({
  className,
  size = 14,
  status,
}: CiStatusDotProps) {
  const s = MAP[status ?? 'unknown'] ?? MAP.unknown
  const Icon = s.icon
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-full border',
        s.color,
        className,
      )}
      style={{ height: size + 2, width: size + 2 }}
      title={s.title}
    >
      <Icon size={size - 4} strokeWidth={3} />
    </span>
  )
}
