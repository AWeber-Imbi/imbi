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

/** CI roll-up status → Tailwind dot background class. */
const CI_DOT_CLASSES: Record<string, string> = {
  fail: 'bg-danger',
  pass: 'bg-success',
  unknown: 'bg-tertiary',
  warn: 'bg-warning',
}

export function ciStatusDotClass(status: null | string | undefined): string {
  return (status && CI_DOT_CLASSES[status]) || CI_DOT_CLASSES.unknown
}
