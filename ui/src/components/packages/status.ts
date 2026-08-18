import type { ComponentStatus } from '@/types'

export type StatusValue = 'current' | ComponentStatus

/**
 * Badge variant per governance status. `current` is the absence of a
 * mark rather than a stored value, so it only ever renders inside the
 * status menu — a table full of green "Current" badges says nothing.
 */
export const STATUS_VARIANT: Record<
  StatusValue,
  'danger' | 'success' | 'warning'
> = {
  current: 'success',
  deprecated: 'warning',
  forbidden: 'danger',
}

export const STATUS_LABEL: Record<StatusValue, string> = {
  current: 'Current',
  deprecated: 'Deprecated',
  forbidden: 'Forbidden',
}

/** The three options a status menu offers, strictest last. */
export const STATUS_OPTIONS: StatusValue[] = [
  'current',
  'deprecated',
  'forbidden',
]

export function statusLabel(status: ComponentStatus | null | undefined) {
  return STATUS_LABEL[status ?? 'current']
}

export function statusVariant(status: ComponentStatus | null | undefined) {
  return STATUS_VARIANT[status ?? 'current']
}
