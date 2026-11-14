import { useCallback, useRef } from 'react'

import {
  defaultRangeExtractor,
  observeElementRect,
  type Range,
  useVirtualizer,
  type VirtualItem,
  type Virtualizer,
} from '@tanstack/react-virtual'

interface Options {
  count: number
  estimateSize: (index: number) => number
  gap?: number
  getItemKey: (index: number) => number | string
  /** Rows to keep rendered out of view, like the focused or selected one. */
  keep?: number[]
  onChange?: (virtualizer: Virtualizer<HTMLDivElement, Element>) => void
  overscan?: number
  paddingEnd?: number
  paddingStart?: number
  scroller: React.RefObject<HTMLDivElement | null>
}

/** Each rendered row with the empty space before it, and the space after. */
export function gapsOf(
  items: VirtualItem[],
  total: number,
): { after: number; rows: { before: number; item: VirtualItem }[] } {
  let end = 0
  const rows = items.map((item) => {
    const before = Math.max(0, item.start - end)
    end = item.end
    return { before, item }
  })
  return { after: Math.max(0, total - end), rows }
}

/** Whether the scroller has no layout, so every row renders. */
export function unlaidOf(virtualizer: Virtualizer<HTMLDivElement, Element>) {
  return (virtualizer.scrollRect?.height ?? 0) <= 1
}

/**
 * A virtualizer over the rows of `scroller`. A scroller with no layout
 * (hidden, or under jsdom) keeps every row, so there is something to show
 * and to find before it has a height.
 */
export function useVirtualRows({
  count,
  estimateSize,
  gap,
  getItemKey,
  keep = [],
  onChange,
  overscan = 8,
  paddingEnd,
  paddingStart,
  scroller,
}: Options) {
  const unlaid = useRef(false)
  const kept = keep.join(',')
  const rangeExtractor = useCallback(
    (range: Range) => {
      if (unlaid.current)
        return Array.from({ length: range.count }, (_, i) => i)
      const indexes = new Set(defaultRangeExtractor(range))
      for (const i of kept ? kept.split(',').map(Number) : [])
        if (i >= 0 && i < range.count) indexes.add(i)
      return [...indexes].sort((a, b) => a - b)
    },
    [kept],
  )
  return useVirtualizer({
    count,
    estimateSize,
    gap,
    getItemKey,
    getScrollElement: () => scroller.current,
    observeElementRect: (instance, cb) =>
      observeElementRect(instance, (rect) => {
        unlaid.current = rect.height === 0
        cb(unlaid.current ? { ...rect, height: 1 } : rect)
      }),
    onChange,
    overscan,
    paddingEnd,
    paddingStart,
    rangeExtractor,
  })
}
