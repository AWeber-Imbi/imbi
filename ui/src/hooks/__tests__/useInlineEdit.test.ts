import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { useInlineEdit } from '../useInlineEdit'

describe('useInlineEdit', () => {
  it('starts in display mode', () => {
    const { result } = renderHook(() =>
      useInlineEdit({ initial: 'a', onCommit: vi.fn() }),
    )
    expect(result.current.isEditing).toBe(false)
    expect(result.current.draft).toBe('a')
  })

  it('enter() puts it in edit mode with draft=initial', () => {
    const { result } = renderHook(() =>
      useInlineEdit({ initial: 'a', onCommit: vi.fn() }),
    )
    act(() => result.current.enter())
    expect(result.current.isEditing).toBe(true)
    expect(result.current.draft).toBe('a')
  })

  it('cancel() restores and exits', () => {
    const { result } = renderHook(() =>
      useInlineEdit({ initial: 'a', onCommit: vi.fn() }),
    )
    act(() => result.current.enter())
    act(() => result.current.setDraft('b'))
    act(() => result.current.cancel())
    expect(result.current.isEditing).toBe(false)
    expect(result.current.draft).toBe('a')
  })

  it('commit() calls onCommit and exits on success', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    const { result } = renderHook(() =>
      useInlineEdit({ initial: 'a', onCommit }),
    )
    act(() => result.current.enter())
    act(() => result.current.setDraft('b'))
    await act(async () => {
      await result.current.commit()
    })
    expect(onCommit).toHaveBeenCalledWith('b')
    expect(result.current.isEditing).toBe(false)
    expect(result.current.error).toBeNull()
  })

  it('commit() is a no-op when draft === initial', async () => {
    const onCommit = vi.fn()
    const { result } = renderHook(() =>
      useInlineEdit({ initial: 'a', onCommit }),
    )
    act(() => result.current.enter())
    await act(async () => {
      await result.current.commit()
    })
    expect(onCommit).not.toHaveBeenCalled()
    expect(result.current.isEditing).toBe(false)
  })

  it('commit() keeps edit mode and sets error on rejection', async () => {
    const onCommit = vi.fn().mockRejectedValue(new Error('boom'))
    const { result } = renderHook(() =>
      useInlineEdit({ initial: 'a', onCommit }),
    )
    act(() => result.current.enter())
    act(() => result.current.setDraft('b'))
    await act(async () => {
      await result.current.commit()
    })
    expect(result.current.isEditing).toBe(true)
    expect(result.current.draft).toBe('b')
    expect(result.current.error).toBe('boom')
  })

  it('handleKeyDown Enter commits', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    const { result } = renderHook(() =>
      useInlineEdit({ initial: 'a', onCommit }),
    )
    act(() => result.current.enter())
    act(() => result.current.setDraft('b'))
    await act(async () => {
      await result.current.handleKeyDown({
        key: 'Enter',
        preventDefault: vi.fn(),
      } as unknown as React.KeyboardEvent)
    })
    expect(onCommit).toHaveBeenCalledWith('b')
  })

  it('handleKeyDown Escape cancels', () => {
    const { result } = renderHook(() =>
      useInlineEdit({ initial: 'a', onCommit: vi.fn() }),
    )
    act(() => result.current.enter())
    act(() => result.current.setDraft('b'))
    act(() => {
      result.current.handleKeyDown({
        key: 'Escape',
        preventDefault: vi.fn(),
      } as unknown as React.KeyboardEvent)
    })
    expect(result.current.isEditing).toBe(false)
    expect(result.current.draft).toBe('a')
  })

  it('handleBlur commits only when changed', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    const { result } = renderHook(() =>
      useInlineEdit({ initial: 'a', onCommit }),
    )
    act(() => result.current.enter())
    await act(async () => {
      await result.current.handleBlur({} as React.FocusEvent)
    })
    expect(onCommit).not.toHaveBeenCalled()
    expect(result.current.isEditing).toBe(false)

    act(() => result.current.enter())
    act(() => result.current.setDraft('b'))
    await act(async () => {
      await result.current.handleBlur({} as React.FocusEvent)
    })
    expect(onCommit).toHaveBeenCalledWith('b')
  })
})
