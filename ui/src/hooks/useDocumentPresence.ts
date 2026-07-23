import { useEffect } from 'react'

import { useQuery } from '@tanstack/react-query'

import {
  clearDocumentEditing,
  getDocumentEditors,
  heartbeatDocumentEditing,
} from '@/api/endpoints'

// The server expires markers after 30s; heartbeat well inside that.
const HEARTBEAT_MS = 10_000
const READER_POLL_MS = 5000

/**
 * Advisory "currently editing" presence for one document.
 *
 * While `isEditing`, sends a PUT heartbeat on an interval (the response
 * carries the active editor list, so no separate poll is needed) and
 * clears the caller's marker on unmount / leaving edit mode. While just
 * reading, polls the editor list. Presence is best-effort: markers
 * expire server-side, so a missed DELETE only lingers for the TTL.
 */
export function useDocumentPresence(
  orgSlug: string,
  documentId: null | string,
  isEditing: boolean,
  currentUserEmail: string,
) {
  const enabled = !!orgSlug && !!documentId

  const { data } = useQuery({
    enabled,
    gcTime: 0,
    queryFn: ({ signal }) =>
      isEditing
        ? heartbeatDocumentEditing(orgSlug, documentId ?? '')
        : getDocumentEditors(orgSlug, documentId ?? '', signal),
    queryKey: ['documentEditors', orgSlug, documentId, isEditing],
    refetchInterval: isEditing ? HEARTBEAT_MS : READER_POLL_MS,
    retry: false,
    staleTime: 0,
  })

  // Best-effort release when the editor closes; the TTL covers the rest.
  useEffect(() => {
    if (!enabled || !isEditing || !documentId) return
    return () => {
      clearDocumentEditing(orgSlug, documentId).catch(() => {})
    }
  }, [enabled, isEditing, orgSlug, documentId])

  const editors = data?.editors ?? []
  return {
    otherEditors: editors.filter((email) => email !== currentUserEmail),
  }
}
