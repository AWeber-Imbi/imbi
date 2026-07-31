import { renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'

import { useDocumentReadTracking } from '../useDocumentReadTracking'

const HEARTBEAT_MS = 15_000

/** Drive the focus and visibility signals the hook gates accrual on. */
function setFocused(value: boolean) {
  vi.spyOn(document, 'hasFocus').mockReturnValue(value)
}

function setVisibility(value: 'hidden' | 'visible') {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => value,
  })
  document.dispatchEvent(new Event('visibilitychange'))
}

describe('useDocumentReadTracking', () => {
  let post: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    vi.useFakeTimers()
    post = vi
      .spyOn(endpoints, 'postDocumentReadEvents')
      .mockResolvedValue(undefined)
    // sendBeacon is only used for the final flush; stub it so unmount
    // does not blow up in jsdom.
    Object.defineProperty(navigator, 'sendBeacon', {
      configurable: true,
      value: vi.fn().mockReturnValue(true),
      writable: true,
    })
    setVisibility('visible')
    setFocused(true)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('accrues engaged time while visible, focused, and active', () => {
    renderHook(() => useDocumentReadTracking('acme', 'doc-1'))

    vi.advanceTimersByTime(HEARTBEAT_MS)

    expect(post).toHaveBeenCalledTimes(1)
    const [, , events] = post.mock.calls[0] as [
      string,
      string,
      { engaged_ms: number; seq: number }[],
    ]
    expect(events[0].seq).toBe(0)
    expect(events[0].engaged_ms).toBeGreaterThan(0)
  })

  it('sends nothing for an interval spent on a hidden tab', () => {
    renderHook(() => useDocumentReadTracking('acme', 'doc-1'))

    // Hiding flushes whatever was engaged so far, then stops accrual.
    // Anything after that must not produce a heartbeat.
    setVisibility('hidden')
    post.mockClear()

    vi.advanceTimersByTime(HEARTBEAT_MS * 4)

    expect(post).not.toHaveBeenCalled()
  })

  it('stops accruing once the reader goes idle', () => {
    renderHook(() => useDocumentReadTracking('acme', 'doc-1'))

    // First beat covers a genuinely engaged interval.
    vi.advanceTimersByTime(HEARTBEAT_MS)
    expect(post).toHaveBeenCalledTimes(1)

    // No further input: once past the 60s idle threshold the reader is
    // treated as gone, and idle intervals send nothing at all.
    post.mockClear()
    vi.advanceTimersByTime(HEARTBEAT_MS * 10)

    const idleBeats = post.mock.calls.length
    expect(idleBeats).toBeLessThanOrEqual(4)

    // Every beat that did land covers the window before the threshold,
    // never the long idle stretch after it.
    for (const call of post.mock.calls) {
      const events = call[2] as { engaged_ms: number }[]
      expect(events[0].engaged_ms).toBeLessThanOrEqual(HEARTBEAT_MS * 1.5)
    }
  })

  it('does not track when no document is open', () => {
    renderHook(() => useDocumentReadTracking('acme', null))
    vi.advanceTimersByTime(HEARTBEAT_MS * 3)
    expect(post).not.toHaveBeenCalled()
  })

  it('flushes through the API client on unmount, not a beacon', () => {
    // An in-SPA navigation is not a page teardown: the normal client is
    // available and carries auth, which `sendBeacon` cannot.
    const { unmount } = renderHook(() =>
      useDocumentReadTracking('acme', 'doc-1'),
    )
    vi.advanceTimersByTime(5_000)
    post.mockClear()
    unmount()

    expect(post).toHaveBeenCalledTimes(1)
    const events = post.mock.calls[0][2] as { is_final: boolean }[]
    expect(events[0].is_final).toBe(true)
    expect(navigator.sendBeacon).not.toHaveBeenCalled()
  })

  it('uses a beacon when the page itself is going away', () => {
    // A closing tab will not wait for fetch, so the tail of the session
    // has to go out via sendBeacon even though it cannot set headers.
    renderHook(() => useDocumentReadTracking('acme', 'doc-1'))
    vi.advanceTimersByTime(5_000)

    window.dispatchEvent(new Event('pagehide'))

    expect(navigator.sendBeacon).toHaveBeenCalledTimes(1)
  })
})
