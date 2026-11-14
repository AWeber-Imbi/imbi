import type { TrajectorySpan } from './trajectoryModel'

/** The first and last records the ledger shows in its scroll viewport. */
export interface TrajectoryWindow {
  from: string
  to: string
}

/** Where the window sits on the overview, in domain units. */
export function frameOf(
  spans: TrajectorySpan[],
  visible: null | TrajectoryWindow,
): [number, number] | null {
  if (!visible) return null
  const from = spans.find((s) => s.id === visible.from)
  const to = spans.find((s) => s.id === visible.to)
  if (!from || !to) return null
  return [Math.min(from.start, to.start), Math.max(from.end, to.end)]
}

/**
 * The first and last rows that show between `top` and `bottom`, given
 * each row's offsets in the same scroll box. Rows are in order.
 */
export function windowOf(
  rows: { bottom: number; id: string; top: number }[],
  top: number,
  bottom: number,
): null | TrajectoryWindow {
  const shown = rows.filter((r) => r.bottom > top && r.top < bottom)
  if (!shown.length) return null
  return { from: shown[0].id, to: shown[shown.length - 1].id }
}
