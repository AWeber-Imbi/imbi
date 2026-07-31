import { useEffect } from 'react'

import { apiUrl } from '@/api/client'
import { postDocumentReadEvents } from '@/api/endpoints'
import type { DocumentReadEvent } from '@/types'

// How often a heartbeat is sent while the reader is engaged. Must match
// the server's `HEARTBEAT_INTERVAL_SECONDS`, which clamps each beat's
// claimed engaged time to 1.5x this — raising one without the other
// silently truncates every session.
const HEARTBEAT_MS = 15_000

// No input for this long means the reader has stopped reading, even
// with the tab visible and focused. Accrual resumes on the next input.
const IDLE_THRESHOLD_MS = 60_000

// Activity only has to be observed once per this window: it feeds a
// 60s threshold, so re-deriving it per `pointermove` would run the
// whole accrual path hundreds of times a second to no effect.
const ACTIVITY_RESOLUTION_MS = 1_000

// Input events that count as "still here". Deliberately passive and
// coarse: this only needs to distinguish a person from an empty chair.
const ACTIVITY_EVENTS = [
  'keydown',
  'pointerdown',
  'pointermove',
  'touchstart',
  'wheel',
] as const

/**
 * Measures how long a reader is actually engaged with a document.
 *
 * Time accrues only while the document is visible, the window is
 * focused, and an input event has occurred within `IDLE_THRESHOLD_MS`.
 * A tab left open overnight therefore reports the seconds actually
 * read, not the hours the tab existed — the entire point of measuring
 * engagement client-side is that only the client can see these three
 * signals.
 *
 * Heartbeats carry the *delta* since the previous beat rather than a
 * running total, so a dropped beat costs one interval instead of
 * corrupting the session. An interval with no engaged time sends
 * nothing at all, so an idle reader generates no traffic.
 *
 * Only the page-teardown flush uses `sendBeacon`, because a closing tab
 * will not wait for `fetch`; every other path goes through the normal
 * API client so it carries auth. Both are idempotent server-side —
 * heartbeats dedup on `(session_id, seq)` — so a beacon racing the
 * interval timer cannot double-count.
 */
export function useDocumentReadTracking(
  orgSlug: string,
  documentId: null | string,
): void {
  useEffect(() => {
    if (!orgSlug || !documentId) return

    // Effect-local: every closure below captures these, and the effect
    // re-runs (starting a new session) only when the document changes.
    const sessionId = crypto.randomUUID()
    const sessionStartedAt = new Date().toISOString()
    let engagedMs = 0
    let lastActivityAt = Date.now()
    let lastTickAt = Date.now()
    let maxScrollPct = 0
    let seq = 0
    // Cached so a scroll burst does not force a layout per event.
    let scrollable = document.documentElement.scrollHeight - window.innerHeight

    const engaged = (): boolean =>
      document.visibilityState === 'visible' &&
      document.hasFocus() &&
      Date.now() - lastActivityAt < IDLE_THRESHOLD_MS

    // Fold the time since the last accrual into the running delta, then
    // reset the clock. Called before every read of `engagedMs` so the
    // in-flight interval is never lost or double-counted.
    const accrue = (): void => {
      const now = Date.now()
      if (engaged()) engagedMs += now - lastTickAt
      lastTickAt = now
    }

    const onActivity = (): void => {
      // Cheap early-out for high-frequency events; the marker only has
      // to be accurate to within `ACTIVITY_RESOLUTION_MS`.
      if (Date.now() - lastActivityAt < ACTIVITY_RESOLUTION_MS) return
      // Accrue *before* moving the activity marker: the span just ended
      // is only engaged time if the reader was already non-idle, and
      // stamping first would retroactively credit an idle gap.
      accrue()
      lastActivityAt = Date.now()
    }

    const onScroll = (): void => {
      onActivity()
      if (scrollable > 0) {
        const pct = Math.round((window.scrollY / scrollable) * 100)
        maxScrollPct = Math.min(100, Math.max(maxScrollPct, pct))
      } else {
        // Nothing to scroll: the whole document is on screen, which is
        // full depth. Without this a short document could never reach
        // the read threshold by scrolling.
        maxScrollPct = 100
      }
    }

    const onResize = (): void => {
      scrollable = document.documentElement.scrollHeight - window.innerHeight
    }

    const flush = (isFinal: boolean, teardown = false): void => {
      accrue()
      // A non-final beat with nothing to report is not worth a request;
      // a final one still is, because it closes the session out.
      if (engagedMs <= 0 && !isFinal) return
      const event: DocumentReadEvent = {
        engaged_ms: engagedMs,
        is_final: isFinal,
        max_scroll_pct: maxScrollPct,
        seq,
        session_id: sessionId,
        session_started_at: sessionStartedAt,
        surface: 'web',
      }
      seq += 1
      engagedMs = 0
      if (teardown) {
        sendBeacon(event)
      } else {
        void postDocumentReadEvents(orgSlug, documentId, [event]).catch(
          () => {},
        )
      }
    }

    // Only for a page that is going away: `sendBeacon` cannot set an
    // Authorization header, so this relies on the session cookie.
    const sendBeacon = (event: DocumentReadEvent): void => {
      const body = JSON.stringify({ events: [event] })
      const url = apiUrl(
        `/organizations/${encodeURIComponent(orgSlug)}/documents/${encodeURIComponent(documentId)}/read-events`,
      )
      if (typeof navigator.sendBeacon === 'function') {
        navigator.sendBeacon(
          url,
          new Blob([body], { type: 'application/json' }),
        )
      }
    }

    const onVisibility = (): void => {
      accrue()
      if (document.visibilityState === 'hidden') flush(true, true)
    }
    const onPageHide = (): void => flush(true, true)

    const timer = window.setInterval(() => flush(false), HEARTBEAT_MS)
    for (const name of ACTIVITY_EVENTS) {
      window.addEventListener(name, onActivity, { passive: true })
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onResize, { passive: true })
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('pagehide', onPageHide)
    // Focus changes gate accrual, so fold the elapsed span in at the
    // boundary rather than letting the next accrue() attribute it to
    // whichever side happened to be current.
    window.addEventListener('blur', accrue)
    window.addEventListener('focus', accrue)

    return () => {
      window.clearInterval(timer)
      for (const name of ACTIVITY_EVENTS) {
        window.removeEventListener(name, onActivity)
      }
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onResize)
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('pagehide', onPageHide)
      window.removeEventListener('blur', accrue)
      window.removeEventListener('focus', accrue)
      // An in-SPA navigation, not a page teardown — the normal client
      // is available here and carries auth.
      flush(true)
    }
  }, [orgSlug, documentId])
}
