import type { KeyboardEvent, RefObject } from 'react'
import { useMemo, useState } from 'react'

import type { MentionCandidate, MentionQuery } from './mentions'
import { filterCandidates, insertMention, mentionQueryAt } from './mentions'

interface MentionAutocomplete {
  /** The currently highlighted candidate index. */
  active: number
  /** Dismiss the open query (e.g. after submit). */
  close: () => void
  /** The visible (filtered) candidates for the open query. */
  matches: MentionCandidate[]
  /**
   * Handle a keydown while the popover is open. Returns true when the key was
   * consumed (navigation/selection/dismiss) so the composer skips its own
   * handling.
   */
  onKeyDown: (e: KeyboardEvent<HTMLTextAreaElement>) => boolean
  /** True while a mention query is open at the caret. */
  open: boolean
  /** Insert a candidate's display name, replacing the open query. */
  pick: (candidate: MentionCandidate) => void
  /** Recompute the open query from the textarea's value + caret. */
  refresh: (el: HTMLTextAreaElement) => void
}

/**
 * @mention autocomplete state machine for a textarea. Owns the open query,
 * candidate filtering, keyboard navigation, and caret-aware insertion; the
 * composer wires it to `value`/`onChange` and calls `refresh` on input. Kept
 * separate from CommentComposer so the composer stays a thin render.
 */
export function useMentionAutocomplete(
  ref: RefObject<HTMLTextAreaElement | null>,
  candidates: MentionCandidate[],
  value: string,
  setValue: (next: string, caret?: number) => void,
): MentionAutocomplete {
  const [query, setQuery] = useState<MentionQuery | null>(null)
  const [active, setActive] = useState(0)

  const matches = useMemo(
    () => (query ? filterCandidates(candidates, query.text) : []),
    [candidates, query],
  )

  const refresh = (el: HTMLTextAreaElement) => {
    setQuery(mentionQueryAt(el.value, el.selectionStart))
    setActive(0)
  }

  const pick = (candidate: MentionCandidate) => {
    const el = ref.current
    if (!el || !query) return
    const next = insertMention(
      value,
      query,
      el.selectionStart,
      candidate.display_name,
    )
    setQuery(null)
    setValue(next.value, next.caret)
  }

  // fallow-ignore-next-line complexity
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>): boolean => {
    if (!query || matches.length === 0) return false
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((a) => (a + 1) % matches.length)
      return true
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => (a - 1 + matches.length) % matches.length)
      return true
    }
    if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault()
      const choice = matches[active]
      if (choice) pick(choice)
      return true
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      setQuery(null)
      return true
    }
    return false
  }

  return {
    active,
    close: () => setQuery(null),
    matches,
    onKeyDown,
    open: query !== null && matches.length > 0,
    pick,
    refresh,
  }
}
