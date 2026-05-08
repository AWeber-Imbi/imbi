import type { BadgeProps } from '@/components/ui/badge'

/** Map third-party-service status strings to semantic Badge variants. */
const STATUS_VARIANTS: Record<string, BadgeProps['variant']> = {
  active: 'success',
  deprecated: 'warning',
  evaluating: 'info',
  inactive: 'neutral',
  revoked: 'danger',
}

export function statusBadgeVariant(
  status: null | string | undefined,
): BadgeProps['variant'] {
  return (status && STATUS_VARIANTS[status]) || 'neutral'
}
