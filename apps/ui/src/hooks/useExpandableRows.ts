import { useCallback, useState } from 'react'

// Tiny shared state for table rows that toggle an inline detail
// panel. Returns a Set of expanded indexes, a stable toggle, and
// ``removeRow`` -- a helper that drops the row at ``idx`` from a
// caller-supplied list state and rebuilds the expanded set so the
// shifted-left indexes still point at the right rows. Extracted out
// of the project-type / project plugin override tables so they can
// both use the same expand-on-click pattern without duplicating the
// boilerplate.
export function useExpandableRows(): {
  expanded: Set<number>
  removeRow: <T>(
    idx: number,
    setList: React.Dispatch<React.SetStateAction<T[]>>,
  ) => void
  setExpanded: React.Dispatch<React.SetStateAction<Set<number>>>
  toggleExpanded: (idx: number) => void
} {
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const toggleExpanded = useCallback((idx: number) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }, [])
  const removeRow = useCallback(
    <T>(idx: number, setList: React.Dispatch<React.SetStateAction<T[]>>) => {
      setList((prev) => prev.filter((_, i) => i !== idx))
      setExpanded((prev) => {
        const next = new Set<number>()
        // Indices shift left by 1 once we drop ``idx``; rebuild the
        // set accordingly so a different row doesn't suddenly appear
        // expanded.
        for (const i of prev) {
          if (i === idx) continue
          next.add(i > idx ? i - 1 : i)
        }
        return next
      })
    },
    [],
  )
  return { expanded, removeRow, setExpanded, toggleExpanded }
}
