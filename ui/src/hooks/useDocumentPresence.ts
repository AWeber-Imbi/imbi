import { useEffect } from 'react'

import { useQuery } from '@tanstack/react-query'

import { clearDocumentEditing, heartbeatDocumentEditing } from '@/api/endpoints'

// The server expires markers after 30s; heartbeat well inside that.
const HEARTBEAT_MS = 10_000

/**
 * Advisory "currently editing" presence for one document.
 *
 * Active only while `isEditing`: sends a PUT heartbeat on an interval
 * (the response carries the active editor list, so no separate poll
 * is needed) and clears the caller's marker on unmount / leaving edit
 * mode. Idle readers generate no presence traffic. Presence is
 * best-effort: markers expire server-side, so a missed DELETE only
 * lingers for the TTL.
 */
export function useDocumentPresence(
  orgSlug: string,
  documentId: null | string,
  isEditing: boolean,
  currentUserEmail: string,
) {
  const enabled = !!orgSlug && !!documentId && isEditing

  const { data } = useQuery({
    enabled,
    gcTime: 0,
    queryFn: () => heartbeatDocumentEditing(orgSlug, documentId ?? ''),
    queryKey: ['documentEditors', orgSlug, documentId],
    refetchInterval: HEARTBEAT_MS,
    retry: false,
    staleTime: 0,
  })

  // Best-effort release when the editor closes; the TTL covers the rest.
  useEffect(() => {
    if (!enabled || !documentId) return
    return () => {
      clearDocumentEditing(orgSlug, documentId).catch(() => {})
    }
  }, [enabled, orgSlug, documentId])

  const editors = enabled ? (data?.editors ?? []) : []
  return {
    otherEditors: editors.filter((email) => email !== currentUserEmail),
  }
}
