import { describe, expect, it, vi } from 'vitest'

import { renderHook } from '@/test/utils'

import { useVirtualRows } from '../virtualRows'

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
