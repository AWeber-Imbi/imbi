import type { ComponentStatus } from '@/types'

/**
 * Badge variant per governance status.
 *
 * There is no "current" value. An unmarked package or version is the
 * absence of a mark, and the absence renders as an invitation to set
 * one ("Set status") rather than as a green badge asserting a review
 * that never happened.
 */
export const STATUS_VARIANT: Record<ComponentStatus, 'danger' | 'warning'> = {
  deprecated: 'warning',
  forbidden: 'danger',
}

export const STATUS_LABEL: Record<ComponentStatus, string> = {
  deprecated: 'Deprecated',
  forbidden: 'Forbidden',
}

/** The marks a status menu offers, strictest last. */
export const STATUS_OPTIONS: ComponentStatus[] = ['deprecated', 'forbidden']

export function statusLabel(status: ComponentStatus) {
  return STATUS_LABEL[status]
}

export function statusVariant(status: ComponentStatus) {
  return STATUS_VARIANT[status]
}
