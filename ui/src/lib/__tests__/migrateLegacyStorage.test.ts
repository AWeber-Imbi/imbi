import { beforeEach, describe, expect, it, vi } from 'vitest'

import { migrateLegacyStorage } from '../utils'

const OLD_MODE = 'imbi:agent-task:conversation-mode'
const MODE = 'imbi:ticket:conversation-mode'
const OLD_SPLIT = 'react-resizable-panels:imbi:agent-tasks:split:list:detail'
const SPLIT = 'react-resizable-panels:imbi:tickets:split:list:detail'

describe('migrateLegacyStorage', () => {
  const store = new Map<string, string>()

  beforeEach(() => {
    store.clear()
    vi.mocked(window.localStorage.getItem).mockImplementation(
      (key: string) => store.get(key) ?? null,
    )
    vi.mocked(window.localStorage.setItem).mockImplementation(
      (key: string, value: string) => {
        store.set(key, value)
      },
    )
    vi.mocked(window.localStorage.removeItem).mockImplementation(
      (key: string) => {
        store.delete(key)
      },
    )
  })

  it('moves both old keys to the new keys once', () => {
    store.set(OLD_MODE, 'compact')
    store.set(OLD_SPLIT, '{"list":30,"detail":70}')
    migrateLegacyStorage()
    expect(store.get(MODE)).toBe('compact')
    expect(store.get(SPLIT)).toBe('{"list":30,"detail":70}')
    expect(store.has(OLD_MODE)).toBe(false)
    expect(store.has(OLD_SPLIT)).toBe(false)
  })

  it('keeps a value already at the new key', () => {
    store.set(MODE, 'verbose')
    store.set(OLD_MODE, 'compact')
    migrateLegacyStorage()
    expect(store.get(MODE)).toBe('verbose')
    expect(store.has(OLD_MODE)).toBe(false)
  })
})
