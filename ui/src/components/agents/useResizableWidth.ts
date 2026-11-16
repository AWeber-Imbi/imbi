import { type KeyboardEvent, type PointerEvent, useState } from 'react'

import { useStoredState } from './useStoredState'

/** The width change for one arrow key, in px. */
const STEP = 16

/**
 * A sidebar width that the user sets with a drag or with the arrow keys.
 * The width stays in localStorage. Put `handleProps` on an empty div that
 * is the last child of the sidebar. The sidebar must be a positioned
 * element.
 */
export function useResizableWidth(
  key: string,
  fallback: number,
  min: number,
  max: number,
) {
  const clamp = (n: number) => Math.min(max, Math.max(min, n))
  const [width, setWidth] = useStoredState(key, fallback, (raw) =>
    typeof raw === 'number' ? clamp(raw) : undefined,
  )
  // The width less the pointer position at the start of a drag.
  const [grab, setGrab] = useState<null | number>(null)

  return {
    dragging: grab !== null,
    handleProps: {
      'aria-label': 'Resize sidebar',
      'aria-orientation': 'vertical' as const,
      'aria-valuemax': max,
      'aria-valuemin': min,
      'aria-valuenow': width,
      className:
        'hover:after:bg-amber-border focus-visible:after:bg-amber-border absolute inset-y-0 -right-1 z-10 w-2 cursor-col-resize touch-none outline-none select-none after:absolute after:inset-y-0 after:left-1/2 after:w-px after:transition-colors',
      onKeyDown: (e: KeyboardEvent) => {
        if (e.key === 'ArrowLeft') setWidth(clamp(width - STEP))
        if (e.key === 'ArrowRight') setWidth(clamp(width + STEP))
      },
      onLostPointerCapture: () => setGrab(null),
      onPointerDown: (e: PointerEvent) => {
        e.currentTarget.setPointerCapture(e.pointerId)
        setGrab(width - e.clientX)
      },
      onPointerMove: (e: PointerEvent) => {
        if (grab !== null) setWidth(clamp(e.clientX + grab))
      },
      role: 'separator',
      tabIndex: 0,
    },
    width,
  }
}
