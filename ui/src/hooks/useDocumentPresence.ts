import { useEffect } from 'react'

import { useQuery } from '@tanstack/react-query'

import { clearDocumentEditing, heartbeatDocumentEditing } from '@/api/endpoints'
import { queryKeys } from '@/lib/queryKeys'

// Bootstrap interval until the first heartbeat reports the server TTL;
// thereafter the interval is derived as TTL/3 so the marker can miss
// two beats before expiring.
const DEFAULT_HEARTBEAT_MS = 10_000

/**
 * Advisory "currently editing" presence for one document.
 *
 * Active while `documentId` is set (null means "not editing"): sends a
 * PUT heartbeat on an interval — including while the tab is
 * backgrounded, so the marker survives the editor losing focus — and
 * clears the caller's marker on unmount. The heartbeat response
 * carries the active editor list, so no separate poll is needed, and
 * idle readers generate no presence traffic. Presence is best-effort:
 * markers expire server-side, so a missed DELETE only lingers for the
 * TTL.
 */
export function useDocumentPresence(
  orgSlug: string,
  documentId: null | string,
  currentUserEmail: string,
) {
  const { data } = useQuery({
    enabled: !!orgSlug && !!documentId,
    gcTime: 0,
    queryFn: () => heartbeatDocumentEditing(orgSlug, documentId ?? ''),
    queryKey: queryKeys.documentEditors(orgSlug, documentId ?? ''),
    refetchInterval: (query) => {
      const ttl = query.state.data?.ttl_seconds
      return ttl ? (ttl / 3) * 1000 : DEFAULT_HEARTBEAT_MS
    },
    refetchIntervalInBackground: true,
    retry: false,
    staleTime: 0,
  })

  // Best-effort release when the editor closes; the TTL covers the rest.
  useEffect(() => {
    if (!orgSlug || !documentId) return
    return () => {
      clearDocumentEditing(orgSlug, documentId).catch(() => {})
    }
  }, [orgSlug, documentId])

  return {
    otherEditors:
      data?.editors.filter((email) => email !== currentUserEmail) ?? [],
  }
}
