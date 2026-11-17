import { afterEach, describe, expect, it, vi } from 'vitest'

import { storage } from '@/lib/storage'

// test/setup.ts replaces localStorage with a writable stub of vi.fn()s.
const original = window.localStorage

describe('storage', () => {
  afterEach(() => {
    window.localStorage = original
  })

  it('passes reads and writes to localStorage', () => {
    vi.mocked(original.getItem).mockReturnValueOnce('v')
    expect(storage.getItem('k')).toBe('v')
    storage.setItem('k', 'v')
    expect(original.setItem).toHaveBeenCalledWith('k', 'v')
  })

  it('acts as empty when the browser blocks or fills storage', () => {
    const fail = () => {
      throw new DOMException('denied', 'SecurityError')
    }
    window.localStorage = {
      ...original,
      getItem: fail,
      removeItem: fail,
      setItem: fail,
    }
    expect(storage.getItem('k')).toBeNull()
    expect(() => storage.setItem('k', 'v')).not.toThrow()
    expect(() => storage.removeItem('k')).not.toThrow()
  })
})
