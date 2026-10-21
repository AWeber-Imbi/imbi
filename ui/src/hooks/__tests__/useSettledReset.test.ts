import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { useSettledReset } from '../useSettledReset'

describe('useSettledReset', () => {
  it('resets a settled mutation', () => {
    const reset = vi.fn()
    const { result } = renderHook(() =>
      useSettledReset({ isPending: false, reset }),
    )
    result.current()
    expect(reset).toHaveBeenCalledTimes(1)
  })

  it('leaves a pending mutation alone', () => {
    const reset = vi.fn()
    const { result } = renderHook(() =>
      useSettledReset({ isPending: true, reset }),
    )
    result.current()
    expect(reset).not.toHaveBeenCalled()
  })

  it('resets once a pending mutation settles', () => {
    const reset = vi.fn()
    const { rerender, result } = renderHook(
      ({ isPending }) => useSettledReset({ isPending, reset }),
      { initialProps: { isPending: true } },
    )
    result.current()
    result.current()
    expect(reset).not.toHaveBeenCalled()
    rerender({ isPending: false })
    expect(reset).toHaveBeenCalledTimes(1)
    rerender({ isPending: true })
    rerender({ isPending: false })
    expect(reset).toHaveBeenCalledTimes(1)
  })

  it('does not reset on settlement when never asked', () => {
    const reset = vi.fn()
    const { rerender } = renderHook(
      ({ isPending }) => useSettledReset({ isPending, reset }),
      { initialProps: { isPending: true } },
    )
    rerender({ isPending: false })
    expect(reset).not.toHaveBeenCalled()
  })

  it('keeps one identity across a pending flip', () => {
    const reset = vi.fn()
    const { rerender, result } = renderHook(
      ({ isPending }) => useSettledReset({ isPending, reset }),
      { initialProps: { isPending: false } },
    )
    const first = result.current
    rerender({ isPending: true })
    expect(result.current).toBe(first)
    rerender({ isPending: false })
    result.current()
    expect(reset).toHaveBeenCalledTimes(1)
  })
})
