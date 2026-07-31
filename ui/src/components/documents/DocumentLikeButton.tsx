import { useEffect, useRef, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ThumbsUp } from 'lucide-react'

import {
  likeDocument,
  listDocumentLikers,
  unlikeDocument,
} from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { queryKeys } from '@/lib/queryKeys'
import { cn } from '@/lib/utils'
import type { DocumentLikeState } from '@/types'

interface Props {
  documentId: string
  initialCount: number
  initialLiked: boolean
  orgSlug: string
}

/**
 * Thumbs-up toggle for a document.
 *
 * Mirrors the comment-acknowledgement affordance (same icon, same
 * amber-when-active treatment) so the gesture reads identically in both
 * places. The toggle is optimistic and reconciles against the server's
 * returned count rather than a refetch; PUT and DELETE are both
 * idempotent, so a double-tap cannot desync the count.
 *
 * The liker list is fetched only when the popover is opened — most
 * readers never ask who liked a document, and the count alone comes
 * free on the document itself.
 */
export function DocumentLikeButton({
  documentId,
  initialCount,
  initialLiked,
  orgSlug,
}: Props) {
  const queryClient = useQueryClient()
  const [state, setState] = useState<DocumentLikeState>({
    like_count: initialCount,
    liked_by_me: initialLiked,
  })
  const [showLikers, setShowLikers] = useState(false)
  // Arm the liker fetch only after a deliberate hover, so merely
  // sweeping the cursor across the toolbar costs no request.
  const hoverTimer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(hoverTimer.current), [])

  const armLikers = () => {
    hoverTimer.current = window.setTimeout(() => setShowLikers(true), 300)
  }
  const disarmLikers = () => {
    window.clearTimeout(hoverTimer.current)
    setShowLikers(false)
  }

  const { data: likers } = useQuery({
    enabled: showLikers && state.like_count > 0,
    queryFn: ({ signal }) => listDocumentLikers(orgSlug, documentId, signal),
    queryKey: queryKeys.documentLikers(orgSlug, documentId),
    staleTime: 30_000,
  })

  const toggle = useMutation({
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
  })

  return (
    <div className="relative">
      <Button
        aria-label={state.liked_by_me ? 'Remove like' : 'Like this document'}
        aria-pressed={state.liked_by_me}
        className={cn('gap-1.5', state.liked_by_me && 'text-action')}
        onClick={() => toggle.mutate(!state.liked_by_me)}
        onMouseEnter={armLikers}
        onMouseLeave={disarmLikers}
        size="sm"
        variant="ghost"
      >
        <ThumbsUp className="size-3" />
        {state.like_count > 0 && (
          <span className="tabular-nums">{state.like_count}</span>
        )}
      </Button>
      {showLikers && likers && likers.length > 0 && (
        <div className="border-primary bg-primary absolute top-full right-0 z-20 mt-1 w-56 border p-2 text-xs shadow-sm">
          <div className="text-tertiary mb-1">Liked by</div>
          <ul className="space-y-0.5">
            {likers.slice(0, 8).map((liker) => (
              <li className="text-secondary truncate" key={liker.principal}>
                {liker.display_name || liker.principal}
              </li>
            ))}
          </ul>
          {likers.length > 8 && (
            <div className="text-tertiary mt-1">
              and {likers.length - 8} more
            </div>
          )}
        </div>
      )}
    </div>
  )
}
