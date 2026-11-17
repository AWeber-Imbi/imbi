import { useEffect, useState } from 'react'

import { storage } from '@/lib/storage'

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
  projectId: null | string,
  documentId: string,
): number | undefined {
  const [lastVisit, setLastVisit] = useState<number | undefined>(undefined)

  useEffect(() => {
    if (!orgSlug || !documentId) {
      setLastVisit(undefined)
      return
    }
    const key = `${STORAGE_PREFIX}${orgSlug}:${projectId ?? 'org'}:${documentId}`
    const raw = storage.getItem(key)
    const previous = raw ? Number(raw) : Number.NaN
    setLastVisit(Number.isNaN(previous) ? undefined : previous)
    storage.setItem(key, String(Date.now()))
  }, [orgSlug, projectId, documentId])

  return lastVisit
}
