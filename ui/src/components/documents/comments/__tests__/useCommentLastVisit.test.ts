import { renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { useCommentLastVisit } from '../useCommentLastVisit'

const KEY = 'imbi:comment-last-visit:acme:proj-1:doc-1'

// The shared test setup stubs localStorage with a no-op mock; install a real
// in-memory store for this suite so reads reflect writes.
function installMemoryStorage() {
  const store = new Map<string, string>()
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: {
      clear: () => store.clear(),
      getItem: (k: string) => store.get(k) ?? null,
      key: (i: number) => [...store.keys()][i] ?? null,
      get length() {
        return store.size
      },
      removeItem: (k: string) => store.delete(k),
      setItem: (k: string, v: string) => store.set(k, v),
    },
    writable: true,
  })
}

describe('useCommentLastVisit', () => {
  beforeEach(() => {
    installMemoryStorage()
  })

  it('returns undefined on the first visit and records now', () => {
    const before = Date.now()
    const { result } = renderHook(() =>
      useCommentLastVisit('acme', 'proj-1', 'doc-1'),
    )
    expect(result.current).toBeUndefined()
    expect(Number(window.localStorage.getItem(KEY))).toBeGreaterThanOrEqual(
      before,
    )
  })

  it('returns the prior visit timestamp on a later visit', () => {
    const prior = new Date('2026-05-28T09:00:00Z').getTime()
    window.localStorage.setItem(KEY, String(prior))
    const { result } = renderHook(() =>
      useCommentLastVisit('acme', 'proj-1', 'doc-1'),
    )
    expect(result.current).toBe(prior)
    // The current visit replaces the stored timestamp.
    expect(Number(window.localStorage.getItem(KEY))).toBeGreaterThan(prior)
  })

  it('returns undefined when required ids are missing', () => {
    const { result } = renderHook(() =>
      useCommentLastVisit('acme', 'proj-1', ''),
    )
    expect(result.current).toBeUndefined()
  })

  it('ignores a corrupt stored value', () => {
    window.localStorage.setItem(KEY, 'not-a-number')
    const { result } = renderHook(() =>
      useCommentLastVisit('acme', 'proj-1', 'doc-1'),
    )
    expect(result.current).toBeUndefined()
  })
})
