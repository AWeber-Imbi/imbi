import { useCallback, useLayoutEffect, useRef, useState } from 'react'

// Vertical gap between the two right-column cards (Tailwind `gap-6`).
const COLUMN_GAP = 24
// Default cap on the Recent-activity card height in the nested layout, and the
// activity height the layout decision is computed against.
const ACTIVITY_MAX = 600
// Hysteresis band (px) so near-equal heights don't oscillate between layouts.
const DEADBAND = 8

export interface BalancedEnvLayout {
  // Recent-activity card header.
  activityHeaderRef: React.RefObject<HTMLDivElement | null>
  // Wrapper around the Recent-activity list content; measured at its intrinsic
  // height regardless of how tall the card is stretched, which keeps the
  // decision stable (no feedback loop) when the column is bottom-aligned.
  activityInnerRef: React.RefObject<HTMLDivElement | null>
  // ``max-height`` (px) to apply to the Recent-activity card. In the nested
  // layout this is the 600px default; in the full-width layout it is exactly
  // the height that bottom-aligns the right column with Project details
  // (details − health − gap), so the card grows to meet details when it has
  // the content to fill it.
  activityMaxHeightPx: number
  // Project details card (left column, top). Its height is the bar the right
  // column is compared against.
  detailsRef: React.RefObject<HTMLDivElement | null>
  // Health & compliance card (right column, top).
  healthRef: React.RefObject<HTMLDivElement | null>
  recompute: () => void
  // When true the right column's *natural* height is shorter than the details
  // card, so the Environments card should span the full width below both
  // columns (and the right column should stretch to align its bottom).
  spanFull: boolean
}

/**
 * Decide whether the Environments card nests under Project details (left
 * column) or spans the full width below both columns.
 *
 * Rule: span full width when the right column's *natural* height (Health +
 * Recent activity, capped) is shorter than the Project details card. In that
 * case nesting the Environments card under details would leave a tall empty
 * gap on the right, so we drop it to a full-width row and let the right column
 * stretch to bottom-align with details. When the right column already extends
 * past details (e.g. the score breakdown is open, or activity is long), the
 * Environments card stays nested to balance the columns.
 *
 * The decision is computed from intrinsic content heights only, never from the
 * stretched right-column height, so stretching can't feed back and oscillate.
 */
export function useBalancedEnvLayout(): BalancedEnvLayout {
  const detailsRef = useRef<HTMLDivElement | null>(null)
  const healthRef = useRef<HTMLDivElement | null>(null)
  const activityHeaderRef = useRef<HTMLDivElement | null>(null)
  const activityInnerRef = useRef<HTMLDivElement | null>(null)
  const [spanFull, setSpanFull] = useState(false)
  const [detailsHeight, setDetailsHeight] = useState(0)
  const [healthHeight, setHealthHeight] = useState(0)

  // fallow-ignore-next-line complexity
  const recompute = useCallback(() => {
    const details = detailsRef.current
    const health = healthRef.current
    const header = activityHeaderRef.current
    const inner = activityInnerRef.current
    if (!details || !health || !header || !inner) return

    // Only balance at the `lg` breakpoint, where the two-column grid applies.
    if (!window.matchMedia('(min-width: 1024px)').matches) {
      setSpanFull(false)
      return
    }

    const detailsH = details.offsetHeight
    const activityNatural = Math.min(
      header.offsetHeight + inner.offsetHeight,
      ACTIVITY_MAX,
    )
    const rightNatural = health.offsetHeight + COLUMN_GAP + activityNatural

    setDetailsHeight(detailsH)
    setHealthHeight(health.offsetHeight)
    setSpanFull((prev) =>
      prev
        ? rightNatural < detailsH + DEADBAND
        : rightNatural < detailsH - DEADBAND,
    )
  }, [])

  // Full-width layout: cap the activity card at the exact height that
  // bottom-aligns the right column with Project details, so it stretches to
  // meet details (limited only by available content). Nested: the 600 default.
  const activityMaxHeightPx = spanFull
    ? Math.max(0, detailsHeight - healthHeight - COLUMN_GAP)
    : ACTIVITY_MAX

  useLayoutEffect(() => {
    recompute()
    const observed = [
      detailsRef.current,
      healthRef.current,
      activityHeaderRef.current,
      activityInnerRef.current,
    ].filter((el): el is HTMLDivElement => el !== null)
    const observer = new ResizeObserver(recompute)
    for (const el of observed) observer.observe(el)
    window.addEventListener('resize', recompute)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', recompute)
    }
  }, [recompute])

  return {
    activityHeaderRef,
    activityInnerRef,
    activityMaxHeightPx,
    detailsRef,
    healthRef,
    recompute,
    spanFull,
  }
}
