import { useState } from 'react'

import { useMutation, useQueryClient } from '@tanstack/react-query'

import { likeDocument, unlikeDocument } from '@/api/endpoints'
import { queryKeys } from '@/lib/queryKeys'
import type { DocumentLikeState } from '@/types'

export interface DocumentLike extends DocumentLikeState {
  toggle: () => void
}

/**
 * Shared like state for one document.
 *
 * The reader shows the same like control in three places (toolbar,
 * byline, discussion header); they have to agree, so the state lives
 * here once and each button renders it. The toggle is optimistic and
 * reconciles against the server's returned count rather than a refetch
 * — PUT and DELETE are both idempotent, so a double-tap cannot desync.
 */
export function useDocumentLike(
  orgSlug: string,
  documentId: string,
  initialCount: number,
  initialLiked: boolean,
): DocumentLike {
  const queryClient = useQueryClient()
  const [state, setState] = useState<DocumentLikeState>({
    like_count: initialCount,
    liked_by_me: initialLiked,
  })

  const mutation = useMutation({
    mutationFn: (like: boolean) =>
      like
        ? likeDocument(orgSlug, documentId)
        : unlikeDocument(orgSlug, documentId),
    onError: (_error, _like, context) => {
      // Put the pre-click state back; the click did not land.
      if (context) setState(context)
    },
    onMutate: (like: boolean): DocumentLikeState => {
      const previous = state
      setState({
        like_count: Math.max(0, state.like_count + (like ? 1 : -1)),
        liked_by_me: like,
      })
      return previous
    },
    onSuccess: (result) => {
      setState(result)
      void queryClient.invalidateQueries({
        queryKey: queryKeys.documentLikers(orgSlug, documentId),
      })
    },
    // One scope per document runs rapid toggles in series. Without it a
    // slow PUT can settle after the DELETE that followed it and put the
    // stale count back.
    scope: { id: `document-like:${orgSlug}:${documentId}` },
  })

  return {
    ...state,
    toggle: () => mutation.mutate(!state.liked_by_me),
  }
}
