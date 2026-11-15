import { useCallback, useEffect, useRef, useState } from 'react'

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
  const [selected, setSelected] = useState('')
  useEffect(() => {
    const update = () => setSelected(selectedSpan(scroller.current))
    document.addEventListener('selectionchange', update)
    return () => document.removeEventListener('selectionchange', update)
  }, [scroller])
  const kept = [...keep, ...spanIndexes(selected)].join(',')
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
  const virtualizer = useVirtualizer({
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
  virtualizer.shouldAdjustScrollPositionOnItemSizeChange = growsAbove
  return virtualizer
}

/** Keep the view still unless a row that changed size ends above it. */
function growsAbove(
  item: VirtualItem,
  _delta: number,
  instance: Virtualizer<HTMLDivElement, Element>,
) {
  return item.end <= (instance.scrollOffset ?? 0)
}

/**
 * The first and last row of `pane` the text selection touches, as
 * `first-last`, so those rows and the ones between stay rendered and
 * the selection can still be copied after they scroll out of view.
 */
function selectedSpan(pane: HTMLElement | null): string {
  const selection = document.getSelection()
  if (!pane || !selection || selection.isCollapsed || !selection.rangeCount)
    return ''
  const range = selection.getRangeAt(0)
  const found = [...pane.querySelectorAll<HTMLElement>('[data-index]')].flatMap(
    (row) => (range.intersectsNode(row) ? [Number(row.dataset.index)] : []),
  )
  if (!found.length) return ''
  return `${Math.min(...found)}-${Math.max(...found)}`
}

function spanIndexes(span: string): number[] {
  if (!span) return []
  const [first, last] = span.split('-').map(Number)
  return Array.from({ length: last - first + 1 }, (_, i) => first + i)
}
