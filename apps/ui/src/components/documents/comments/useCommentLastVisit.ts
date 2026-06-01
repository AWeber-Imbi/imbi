import { useEffect, useState } from 'react'

const STORAGE_PREFIX = 'imbi:comment-last-visit:'

/**
 * Per-document "last visited the comments" timestamp, persisted in
 * localStorage and keyed by org/project/document. Comments created after the
 * returned `lastVisit` (and not by the current user) are considered unread.
 *
 * The returned value is the *previous* visit's timestamp, captured once when
 * the document is opened so dots stay stable for the whole viewing session;
 * the current visit time is written back immediately so the next visit
 * compares against this one. There is no server-side read model — that is an
 * explicit future follow-up.
 */
export function useCommentLastVisit(
  orgSlug: string,
  projectId: string,
  documentId: string,
): number | undefined {
  const [lastVisit, setLastVisit] = useState<number | undefined>(undefined)

  useEffect(() => {
    if (!orgSlug || !projectId || !documentId) {
      setLastVisit(undefined)
      return
    }
    const key = `${STORAGE_PREFIX}${orgSlug}:${projectId}:${documentId}`
    let previous: number | undefined
    try {
      const raw = window.localStorage.getItem(key)
      previous = raw ? Number(raw) : undefined
      if (previous !== undefined && Number.isNaN(previous)) previous = undefined
    } catch {
      previous = undefined
    }
    setLastVisit(previous)
    try {
      window.localStorage.setItem(key, String(Date.now()))
    } catch {
      // Ignore storage failures (private mode, quota) — unread dots are
      // a best-effort enhancement, not load-bearing.
    }
  }, [orgSlug, projectId, documentId])

  return lastVisit
}
