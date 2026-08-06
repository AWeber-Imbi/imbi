import { useEffect, useRef, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { ThumbsUp } from 'lucide-react'

import { listDocumentLikers } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { queryKeys } from '@/lib/queryKeys'
import { cn } from '@/lib/utils'
import type { DocumentLiker } from '@/types'

import type { DocumentLike } from './useDocumentLike'

interface Props {
  documentId: string
  like: DocumentLike
  orgSlug: string
  /**
   * `toolbar` is the bare ghost button that sits among History/Pin/Edit;
   * `pill` is the labelled, rounded affordance used beside the byline and
   * at the head of the discussion, where the gesture needs a name.
   */
  variant?: 'pill' | 'toolbar'
}

interface TriggerProps {
  count: number
  liked: boolean
  onMouseEnter: () => void
  onMouseLeave: () => void
  onToggle: () => void
}

/** How many likers the popover names before collapsing the rest. */
const NAMED_LIKERS = 8
/** Deliberate-hover delay before the liker list is worth a request. */
const HOVER_DELAY_MS = 300

/**
 * Thumbs-up toggle for a document.
 *
 * Mirrors the comment-acknowledgement affordance (same icon, same
 * amber-when-active treatment) so the gesture reads identically in both
 * places. All instances share one {@link DocumentLike} so they never
 * disagree about the count.
 *
 * The liker list is fetched only when the popover is opened — most
 * readers never ask who liked a document, and the count alone comes
 * free on the document itself.
 */
export function DocumentLikeButton({
  documentId,
  like,
  orgSlug,
  variant = 'toolbar',
}: Props) {
  const [showLikers, setShowLikers] = useState(false)
  // Arm the liker fetch only after a deliberate hover, so merely
  // sweeping the cursor across the toolbar costs no request.
  const hoverTimer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(hoverTimer.current), [])

  const { data: likers } = useQuery({
    enabled: showLikers && like.like_count > 0,
    queryFn: ({ signal }) => listDocumentLikers(orgSlug, documentId, signal),
    queryKey: queryKeys.documentLikers(orgSlug, documentId),
    staleTime: 30_000,
  })

  const trigger: TriggerProps = {
    count: like.like_count,
    liked: like.liked_by_me,
    onMouseEnter: () => {
      hoverTimer.current = window.setTimeout(
        () => setShowLikers(true),
        HOVER_DELAY_MS,
      )
    },
    onMouseLeave: () => {
      window.clearTimeout(hoverTimer.current)
      setShowLikers(false)
    },
    onToggle: like.toggle,
  }

  return (
    <div className="relative">
      {variant === 'pill' ? (
        <LikePill {...trigger} />
      ) : (
        <LikeGhost {...trigger} />
      )}
      {showLikers && <LikerList likers={likers} />}
    </div>
  )
}

function LikeGhost({ count, liked, onToggle, ...hover }: TriggerProps) {
  return (
    <Button
      aria-label={likeLabel(liked)}
      aria-pressed={liked}
      className={cn('gap-1.5', liked && 'text-action')}
      onClick={onToggle}
      size="sm"
      variant="ghost"
      {...hover}
    >
      <ThumbsUp className="size-3" fill={liked ? 'currentColor' : 'none'} />
      {count > 0 && <span className="tabular-nums">{count}</span>}
    </Button>
  )
}

function likeLabel(liked: boolean): string {
  return liked ? 'Remove like' : 'Like this document'
}

function LikePill({ count, liked, onToggle, ...hover }: TriggerProps) {
  return (
    <button
      aria-label={likeLabel(liked)}
      aria-pressed={liked}
      className={cn(
        'inline-flex cursor-pointer items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12.5px] transition-colors',
        liked
          ? 'border-warning bg-warning text-warning font-medium'
          : 'border-tertiary bg-primary text-secondary hover:border-secondary hover:text-primary',
      )}
      onClick={onToggle}
      type="button"
      {...hover}
    >
      <ThumbsUp className="size-3.5" fill={liked ? 'currentColor' : 'none'} />
      {liked ? 'Liked' : 'Like'}
      <span className="tabular-nums">{count}</span>
    </button>
  )
}

function LikerList({ likers }: { likers?: DocumentLiker[] }) {
  if (!likers || likers.length === 0) return null
  const overflow = likers.length - NAMED_LIKERS
  return (
    <div className="border-tertiary bg-primary absolute top-full right-0 z-20 mt-1 w-56 rounded-lg border p-2 text-xs shadow-sm">
      <div className="text-overline text-tertiary mb-1 uppercase">Liked by</div>
      <ul className="space-y-0.5">
        {likers.slice(0, NAMED_LIKERS).map((liker) => (
          <li className="text-secondary truncate" key={liker.principal}>
            {liker.display_name || liker.principal}
          </li>
        ))}
      </ul>
      {overflow > 0 && (
        <div className="text-tertiary mt-1">and {overflow} more</div>
      )}
    </div>
  )
}
