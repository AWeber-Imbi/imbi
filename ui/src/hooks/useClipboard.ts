import { useCallback, useEffect, useRef, useState } from 'react'

interface UseClipboardOptions {
  /** Milliseconds to keep the "copied" state set before reverting. */
  timeoutMs?: number
}

interface UseClipboardResult {
  /**
   * The most recently copied key, or `null` if nothing has been copied
   * (or the reset timeout has elapsed). When `copy(text)` is called
   * without an explicit `key`, the copied text itself is used.
   */
  copied: null | string
  /**
   * Writes `text` to the clipboard. Sets `copied` to `key` (or `text` if
   * no key is given) for `timeoutMs` ms. Returns `true` on success.
   */
  copy: (text: string, key?: string) => Promise<boolean>
}

/**
 * Shared clipboard-copy behavior: write text and flash a "just copied"
 * indicator that auto-clears after a delay. Use the optional `key`
 * argument when several copy buttons share the same hook instance and
 * each needs to highlight independently (e.g. `copied === thisField`).
 */
export function useClipboard({
  timeoutMs = 2000,
}: UseClipboardOptions = {}): UseClipboardResult {
  const [copied, setCopied] = useState<null | string>(null)
  const timerRef = useRef<null | ReturnType<typeof setTimeout>>(null)

  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    },
    [],
  )

  const copy = useCallback(
    async (text: string, key?: string) => {
      try {
        await navigator.clipboard.writeText(text)
        setCopied(key ?? text)
        if (timerRef.current) clearTimeout(timerRef.current)
        timerRef.current = setTimeout(() => setCopied(null), timeoutMs)
        return true
      } catch {
        return false
      }
    },
    [timeoutMs],
  )

  return { copied, copy }
}
