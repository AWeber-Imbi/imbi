import { useCallback, useState } from 'react'

/** A view setting kept in localStorage, so every task opens the same way. */
export function useStoredState<T>(
  key: string,
  fallback: T,
  parse: (raw: unknown) => T | undefined,
): [T, (next: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = window.localStorage.getItem(key)
      return raw === null ? fallback : (parse(JSON.parse(raw)) ?? fallback)
    } catch {
      return fallback
    }
  })
  const update = useCallback(
    (next: T) => {
      setValue(next)
      try {
        window.localStorage.setItem(key, JSON.stringify(next))
      } catch {
        // Storage can be full or blocked; the setting still applies to this page.
      }
    },
    [key],
  )
  return [value, update]
}
