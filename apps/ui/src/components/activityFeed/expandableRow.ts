import type { HTMLAttributes, KeyboardEvent } from 'react'

/**
 * Interactive attributes that make a clustered feed row expandable by both
 * pointer and keyboard (Enter/Space). Single-item rows get nothing
 * interactive, so they stay out of the tab order.
 */
export function expandableRowProps(
  isGroup: boolean,
  expanded: boolean,
  onToggle: () => void,
): HTMLAttributes<HTMLDivElement> {
  if (!isGroup) return {}
  return {
    'aria-expanded': expanded,
    onClick: onToggle,
    onKeyDown: (e: KeyboardEvent<HTMLDivElement>) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        onToggle()
      }
    },
    role: 'button',
    tabIndex: 0,
  }
}
