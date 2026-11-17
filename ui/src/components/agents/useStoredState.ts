import { useCallback, useState } from 'react'

import { storage } from '@/lib/storage'

/** A view setting kept in localStorage, so every task opens the same way. */
export function useStoredState<T>(
  key: string,
  fallback: T,
  parse: (raw: unknown) => T | undefined,
): [T, (next: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = storage.getItem(key)
      return raw === null ? fallback : (parse(JSON.parse(raw)) ?? fallback)
    } catch {
      return fallback
    }
  })
  const update = useCallback(
    (next: T) => {
      setValue(next)
      storage.setItem(key, JSON.stringify(next))
    },
    [key],
  )
  return [value, update]
}
