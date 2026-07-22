import { useEffect, useState } from 'react'

// Returns ``value`` after it has remained unchanged for ``delayMs``
// milliseconds. Useful for keeping a snappy input state separate from
// a downstream consumer that's expensive to recompute (URL sync,
// network call, big filter+render pass).
//
// ``delayMs`` of ``0`` short-circuits and returns ``value`` directly,
// which lets a caller turn debouncing off (e.g. for tests) without
// branching the hook out.
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    if (delayMs <= 0) {
      setDebounced(value)
      return
    }
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])
  return delayMs <= 0 ? value : debounced
}
