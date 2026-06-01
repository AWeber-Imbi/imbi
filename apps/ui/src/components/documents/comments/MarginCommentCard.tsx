import { forwardRef } from 'react'

import { formatDistanceToNow } from 'date-fns'
import { CheckCircle2, MessageSquare, ThumbsUp } from 'lucide-react'

import { UserDisplay } from '@/components/ui/user-display'
import { cn } from '@/lib/utils'
import type { CommentThread } from '@/types/comments'

import { CommentThreadView } from './CommentThreadView'
import { LazyRichComposer } from './LazyRichComposer'

interface Props {
  busy?: boolean
  currentUserEmail: string
  displayNames?: Map<string, string>
  draft?: boolean
  focused: boolean
  lastVisit?: number
  onAcknowledge: (commentId: string) => void
  onCancelDraft?: () => void
  onDelete: (commentId: string) => void
  onEdit: (commentId: string, body: string, mentions: string[]) => void
  onFocus: () => void
  onHover: (hovered: boolean) => void
  onReply: (body: string, mentions: string[]) => void
  onResolve: (resolved: boolean) => void
  onSubmitDraft?: (body: string, mentions: string[]) => void
  orphaned?: boolean
  thread: CommentThread
}

/**
 * One anchored margin card. Positioned imperatively by RightCommentBar via a
 * `transform: translateY(...)` on this element — intentionally with NO CSS
 * transition on transform (it would fight live re-measurement; cards must snap).
 * Collapsed by default; expands to the full thread (or a composer for a draft)
 * when focused.
 */
export const MarginCommentCard = forwardRef<HTMLDivElement, Props>(
  // fallow-ignore-next-line complexity
  function MarginCommentCard(
    {
      busy,
      currentUserEmail,
      displayNames,
      draft,
      focused,
      lastVisit,
      onAcknowledge,
      onCancelDraft,
      onDelete,
      onEdit,
      onFocus,
      onHover,
      onReply,
      onResolve,
      onSubmitDraft,
      orphaned,
      thread,
    },
    ref,
  ) {
    return (
      <div
        className={cn(
          'absolute inset-x-0 top-0 rounded-lg border border-tertiary bg-primary p-3 shadow-sm',
          'transition-[box-shadow,border-color] duration-150',
          focused && 'border-action shadow-md',
          thread.resolved && 'opacity-70',
        )}
        onClick={() => {
          if (!focused) onFocus()
        }}
        onMouseEnter={() => onHover(true)}
        onMouseLeave={() => onHover(false)}
        ref={ref}
      >
        {thread.anchor?.quote && (
          <div className="border-action text-secondary mb-2 line-clamp-2 border-l-2 pl-2 text-[11.5px] italic">
            {thread.anchor.quote}
          </div>
        )}
        {orphaned && (
          <div className="text-tertiary mb-2 text-[11px]">
            Anchor text not found — orphaned
          </div>
        )}

        {draft ? (
          <LazyRichComposer
            autoFocus
            busy={busy}
            displayNames={displayNames}
            minHeight={96}
            onCancel={onCancelDraft}
            onSubmit={(body, mentions) => onSubmitDraft?.(body, mentions)}
            placeholder="Add your comment…"
            submitLabel="Comment"
          />
        ) : focused ? (
          <CommentThreadView
            busy={busy}
            currentUserEmail={currentUserEmail}
            displayNames={displayNames}
            lastVisit={lastVisit}
            onAcknowledge={onAcknowledge}
            onDelete={onDelete}
            onEdit={onEdit}
            onReply={onReply}
            onResolve={onResolve}
            thread={thread}
          />
        ) : (
          <CollapsedCard displayNames={displayNames} thread={thread} />
        )}
      </div>
    )
  },
)

/** Collapsed preview shown when a non-draft card is not focused. */
// fallow-ignore-next-line complexity
function CollapsedCard({
  displayNames,
  thread,
}: {
  displayNames?: Map<string, string>
  thread: CommentThread
}) {
  const root = thread.comments[0]
  if (!root) return null
  const replyCount = Math.max(0, thread.comments.length - 1)
  return (
    <div>
      <div className="flex items-center gap-2">
        <UserDisplay
          className="text-secondary"
          displayNames={displayNames}
          email={root.author}
          size={22}
          textClassName="text-[12.5px] font-medium text-primary"
        />
        <span className="text-tertiary text-[11.5px]">
          {formatDistanceToNow(new Date(root.created_at), { addSuffix: true })}
        </span>
        {thread.resolved && (
          <CheckCircle2 className="text-action ml-auto size-3.5" />
        )}
      </div>
      <div className="text-primary mt-1.5 line-clamp-3 text-[13px] leading-normal whitespace-pre-wrap">
        {root.body}
      </div>
      <div className="text-tertiary mt-2 flex items-center gap-3 text-[12px]">
        {replyCount > 0 && (
          <span className="inline-flex items-center gap-1">
            <MessageSquare className="size-3" />
            {replyCount} {replyCount === 1 ? 'reply' : 'replies'}
          </span>
        )}
        {root.acknowledged_by.length > 0 && (
          <span className="text-action inline-flex items-center gap-1">
            <ThumbsUp className="size-3" />
            {root.acknowledged_by.length}
          </span>
        )}
      </div>
    </div>
  )
}
