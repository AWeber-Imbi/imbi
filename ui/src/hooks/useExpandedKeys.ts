import { useCallback, useState } from 'react'

/**
 * Expansion state for table rows that carry a stable identity.
 *
 * The sibling `useExpandableRows` keys off the row's array index, which
 * is only safe while the list is fixed. A filtered or re-sorted table
 * re-indexes under the expansion set, so index 3 stops meaning the row
 * the reader opened — key off the row's own id instead.
 */
export function useExpandedKeys(): {
  expanded: Set<string>
  isExpanded: (key: string) => boolean
  reset: () => void
  toggle: (key: string) => void
} {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const toggle = useCallback((key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])
  const reset = useCallback(() => setExpanded(new Set()), [])
  return {
    expanded,
    isExpanded: (key: string) => expanded.has(key),
    reset,
    toggle,
  }
}
