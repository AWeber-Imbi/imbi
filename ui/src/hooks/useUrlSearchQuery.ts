import { useEffect, useRef, useState } from 'react'

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
  const previousUrlQuery = useRef(urlQuery)
  // The value this hook last wrote to the URL, so the resync effect
  // can tell its own write landing apart from external navigation.
  const writtenUrlQuery = useRef<null | string>(null)

  // Sync the debounced query → URL. Skip the write when the value
  // already matches what's in the URL (covers back/forward and the
  // initial mount where ``inputQuery === urlQuery`` by construction).
  // A run triggered by an external URL change is skipped too: the
  // debounced value is still the stale pre-navigation query, and
  // writing it would clobber the ``q`` that just arrived.
  useEffect(() => {
    if (previousUrlQuery.current !== urlQuery) {
      previousUrlQuery.current = urlQuery
      return
    }
    if (debouncedQuery === urlQuery) return
    writtenUrlQuery.current = debouncedQuery
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
  // resyncing the input. The hook's own debounced write is skipped so
  // typing that continued past it isn't clobbered; any other change
  // resyncs, even one that happens to equal the stale debounced value
  // (e.g. navigating away and back inside the debounce window).
  useEffect(() => {
    const isOwnWrite = writtenUrlQuery.current === urlQuery
    writtenUrlQuery.current = null
    if (!isOwnWrite && urlQuery !== inputQuery) {
      setInputQuery(urlQuery)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlQuery])

  return { debouncedQuery, inputQuery, setInputQuery }
}
