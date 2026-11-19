import { useCallback, useState } from 'react'

import { storage } from '@/lib/storage'

/** A view setting kept in localStorage, so every task opens the same way. */
export function useStoredState<T>(
  key: string,
  fallback: T,
  parse: (raw: unknown) => T | undefined,
): [T, (next: ((current: T) => T) | T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = storage.getItem(key)
      return raw === null ? fallback : (parse(JSON.parse(raw)) ?? fallback)
    } catch {
      return fallback
    }
  })
  const update = useCallback(
    (next: ((current: T) => T) | T) => {
      setValue((current) => {
        const value =
          typeof next === 'function'
            ? (next as (current: T) => T)(current)
            : next
        storage.setItem(key, JSON.stringify(value))
        return value
      })
    },
    [key],
  )
  return [value, update]
}
