import { type RefObject, useEffect, useLayoutEffect, useRef } from 'react'

/** How close to the bottom, in pixels, still counts as at the bottom. */
const SLACK_PX = 40

/**
 * Keep a scroll container pinned to its bottom as content arrives, but
 * only while the reader is already there. Scrolling up stops following;
 * scrolling back down resumes it.
 *
 * `size` is what grows as content arrives (e.g. a count of rows). While
 * `enabled` is false nothing is tracked; when it turns true the current
 * position is the baseline, so opening a long list does not jump.
 */
export function useFollowBottom(
  ref: RefObject<HTMLElement | null>,
  size: number,
  enabled: boolean,
): void {
  const following = useRef(false)
  const active = useRef(false)

  useEffect(() => {
    const el = ref.current
    if (!el || !enabled) return
    const onScroll = () => {
      following.current = atBottom(el)
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [ref, enabled])

  useLayoutEffect(() => {
    const el = ref.current
    if (!el || !enabled) {
      active.current = false
      return
    }
    if (!active.current) {
      active.current = true
      following.current = atBottom(el)
      return
    }
    if (following.current) el.scrollTop = el.scrollHeight
  }, [ref, size, enabled])
}

function atBottom(el: HTMLElement): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= SLACK_PX
}
