import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

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

/**
 * Each rendered row with the empty space before it and the rows that
 * space stands for, and the space and rows after the last one.
 */
export function gapsOf(
  items: VirtualItem[],
  total: number,
  count = 0,
): {
  after: number
  afterSkipped: number[]
  rows: { before: number; item: VirtualItem; skipped: number[] }[]
} {
  let end = 0
  let next = 0
  const rows = items.map((item) => {
    const before = Math.max(0, item.start - end)
    const skipped = between(next, item.index)
    end = item.end
    next = item.index + 1
    return { before, item, skipped }
  })
  return {
    after: Math.max(0, total - end),
    afterSkipped: between(next, count),
    rows,
  }
}

/** Brings a row the browser's find matched while unrendered into view. */
export function scrollToFound(
  virtualizer: Virtualizer<HTMLDivElement, Element>,
  index: number,
  align: 'center' | 'start' = 'center',
) {
  requestAnimationFrame(() => virtualizer.scrollToIndex(index, { align }))
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
    const update = () => setSelected(selectedSpan(scroller.current, getItemKey))
    document.addEventListener('selectionchange', update)
    return () => document.removeEventListener('selectionchange', update)
  }, [getItemKey, scroller])
  const span = useMemo(
    () => spanIndexes(selected, count, getItemKey),
    [count, getItemKey, selected],
  )
  const kept = [...keep, ...span].join(',')
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

function between(from: number, to: number): number[] {
  return Array.from({ length: Math.max(0, to - from) }, (_, i) => from + i)
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
 * The keys of the first and last row of `pane` the text selection
 * touches, so those rows and the ones between stay rendered, even as
 * rows land above them, and the selection can still be copied after
 * they scroll out of view. A caret keeps its row too, so a shift+click
 * far away extends from it.
 */
function selectedSpan(
  pane: HTMLElement | null,
  getItemKey: (index: number) => number | string,
): string {
  const selection = document.getSelection()
  if (!pane || !selection?.rangeCount) return ''
  const range = selection.getRangeAt(0)
  const found = [...pane.querySelectorAll<HTMLElement>('[data-index]')].flatMap(
    (row) => (range.intersectsNode(row) ? [Number(row.dataset.index)] : []),
  )
  if (!found.length) return ''
  return JSON.stringify([
    getItemKey(Math.min(...found)),
    getItemKey(Math.max(...found)),
  ])
}

function spanIndexes(
  span: string,
  count: number,
  getItemKey: (index: number) => number | string,
): number[] {
  if (!span) return []
  const ends = JSON.parse(span) as (number | string)[]
  const found: number[] = []
  for (let i = 0; i < count; i++)
    if (ends.includes(getItemKey(i))) found.push(i)
  if (!found.length) return []
  const first = Math.min(...found)
  return Array.from(
    { length: Math.max(...found) - first + 1 },
    (_, i) => first + i,
  )
}
