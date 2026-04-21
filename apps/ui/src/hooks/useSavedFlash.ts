import { useCallback, useEffect, useRef, useState } from 'react'

export interface UseSavedFlashResult {
  saved: Record<string, boolean>
  flash: (key: string) => void
}

export function useSavedFlash(durationMs = 2000): UseSavedFlashResult {
  const [saved, setSaved] = useState<Record<string, boolean>>({})
  const timers = useRef<Record<string, number>>({})

  useEffect(() => {
    const handles = timers.current
    return () => {
      for (const id of Object.values(handles)) {
        window.clearTimeout(id)
      }
    }
  }, [])

  const flash = useCallback(
    (key: string) => {
      setSaved((prev) => ({ ...prev, [key]: true }))
      if (timers.current[key] !== undefined) {
        window.clearTimeout(timers.current[key])
      }
      timers.current[key] = window.setTimeout(() => {
        setSaved((prev) => ({ ...prev, [key]: false }))
        delete timers.current[key]
      }, durationMs)
    },
    [durationMs],
  )

  return { saved, flash }
}
