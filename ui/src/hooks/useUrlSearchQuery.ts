import { useEffect, useState } from 'react'

import { useSearchParams } from 'react-router-dom'

import { useDebouncedValue } from '@/hooks/useDebouncedValue'

export const SEARCH_DEBOUNCE_MS = 200

// Two-way binds a free-text filter input to a URL search param.
//
// ``inputQuery`` drives the controlled <input> so typing stays
// responsive; ``debouncedQuery`` is what gets written to the URL (with
// ``replace``, so keystrokes never pile up history entries) and what
// callers should filter on. External URL changes (back/forward, deep
// links) flow back into the input.
export function useUrlSearchQuery(
  param = 'q',
  delayMs: number = SEARCH_DEBOUNCE_MS,
) {
  const [searchParams, setSearchParams] = useSearchParams()
  const urlQuery = searchParams.get(param) ?? ''
  const [inputQuery, setInputQuery] = useState(urlQuery)
  const debouncedQuery = useDebouncedValue(inputQuery, delayMs)

  // Sync the debounced query → URL. Skip the write when the value
  // already matches what's in the URL (covers back/forward and the
  // initial mount where ``inputQuery === urlQuery`` by construction).
  useEffect(() => {
    if (debouncedQuery === urlQuery) return
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (debouncedQuery) next.set(param, debouncedQuery)
        else next.delete(param)
        return next
      },
      { replace: true },
    )
  }, [debouncedQuery, param, urlQuery, setSearchParams])

  // Honor external URL changes (back/forward, deep links) by
  // resyncing the input. Compares against the *current* input so
  // typing isn't clobbered by the debounced URL write that just
  // landed.
  useEffect(() => {
    if (urlQuery !== inputQuery && urlQuery !== debouncedQuery) {
      setInputQuery(urlQuery)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlQuery])

  return { debouncedQuery, inputQuery, setInputQuery }
}
