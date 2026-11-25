import { describe, expect, it, vi } from 'vitest'

import { renderHook } from '@/test/utils'

import { gapsOf, useVirtualRows } from '../virtualRows'

describe('useVirtualRows', () => {
  it('corrects the scroll only for a row that ends above the view', () => {
    const el = document.createElement('div')
    const scrollTo = vi.fn()
    el.scrollTo = scrollTo
    const { result } = renderHook(() =>
      useVirtualRows({
        count: 10,
        estimateSize: () => 100,
        getItemKey: (i) => i,
        scroller: { current: el },
      }),
    )
    const virtualizer = result.current
    virtualizer.getVirtualItems()
    virtualizer.scrollOffset = 250
    scrollTo.mockClear()
    virtualizer.resizeItem(2, 150)
    expect(scrollTo).not.toHaveBeenCalled()
    virtualizer.resizeItem(1, 150)
    expect(scrollTo).toHaveBeenCalled()
  })
})

describe('gapsOf', () => {
  it('measures gaps from the rows, not the content above them', () => {
    const item = (index: number, start: number) => ({
      end: start + 40,
      index,
      key: index,
      lane: 0,
      size: 40,
      start,
    })
    const { after, rows } = gapsOf([item(0, 300), item(1, 340)], 200, 2, 300)
    expect(rows.map((r) => r.before)).toEqual([0, 0])
    expect(after).toBe(120)
  })
})
