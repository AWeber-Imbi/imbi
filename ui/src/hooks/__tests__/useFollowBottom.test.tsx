import { fireEvent, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { useFollowBottom } from '../useFollowBottom'

/** A scroll box with a settable height; jsdom does no layout. */
function box(scrollHeight: number, scrollTop: number) {
  const el = document.createElement('div')
  let height = scrollHeight
  Object.defineProperty(el, 'clientHeight', { value: 100 })
  Object.defineProperty(el, 'scrollHeight', { get: () => height })
  el.scrollTop = scrollTop
  return {
    el,
    grow(to: number) {
      height = to
    },
  }
}

function render(el: HTMLElement, enabled = true) {
  const ref = { current: el }
  return renderHook(
    ({ enabled, size }) => useFollowBottom(ref, size, enabled),
    { initialProps: { enabled, size: 1 } },
  )
}

describe('useFollowBottom', () => {
  it('follows new content while at the bottom', () => {
    const { el, grow } = box(300, 200)
    const hook = render(el)
    grow(500)
    hook.rerender({ enabled: true, size: 2 })
    expect(el.scrollTop).toBe(500)
  })

  it('stays put once the reader scrolls up', () => {
    const { el, grow } = box(300, 200)
    const hook = render(el)
    el.scrollTop = 50
    fireEvent.scroll(el)
    grow(500)
    hook.rerender({ enabled: true, size: 2 })
    expect(el.scrollTop).toBe(50)
  })

  it('resumes when the reader scrolls back down', () => {
    const { el, grow } = box(300, 50)
    const hook = render(el)
    el.scrollTop = 200
    fireEvent.scroll(el)
    grow(500)
    hook.rerender({ enabled: true, size: 2 })
    expect(el.scrollTop).toBe(500)
  })

  it('does not jump when it opens away from the bottom', () => {
    const { el, grow } = box(300, 0)
    const hook = render(el)
    grow(500)
    hook.rerender({ enabled: true, size: 2 })
    expect(el.scrollTop).toBe(0)
  })

  it('does nothing while disabled', () => {
    const { el, grow } = box(300, 200)
    const hook = render(el, false)
    grow(500)
    hook.rerender({ enabled: false, size: 2 })
    expect(el.scrollTop).toBe(200)
  })
})
