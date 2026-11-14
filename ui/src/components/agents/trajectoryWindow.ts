import type { TrajectorySpan } from './trajectoryModel'

/** The records the ledger shows in its scroll viewport, in row order. */
export interface TrajectoryWindow {
  from: string
  ids: string[]
  to: string
}

/** Where the window sits on the overview, in domain units. */
export function frameOf(
  spans: TrajectorySpan[],
  visible: null | TrajectoryWindow,
): [number, number] | null {
  if (!visible) return null
  const ids = new Set(visible.ids)
  const shown = spans.filter((s) => ids.has(s.id))
  if (!shown.length) return null
  return [
    Math.min(...shown.map((s) => s.start)),
    Math.max(...shown.map((s) => s.end)),
  ]
}

/** Whether two windows show the same records in the same order. */
export function sameWindow(
  a: null | TrajectoryWindow,
  b: null | TrajectoryWindow,
): boolean {
  if (!a || !b) return a === b
  return (
    a.ids.length === b.ids.length && a.ids.every((id, i) => id === b.ids[i])
  )
}

/**
 * The rows that show between `top` and `bottom`, given each row's
 * offsets in the same scroll box. Rows are in order.
 */
export function windowOf(
  rows: { bottom: number; id: string; top: number }[],
  top: number,
  bottom: number,
): null | TrajectoryWindow {
  const shown = rows.filter((r) => r.bottom > top && r.top < bottom)
  if (!shown.length) return null
  return {
    from: shown[0].id,
    ids: shown.map((r) => r.id),
    to: shown[shown.length - 1].id,
  }
}
