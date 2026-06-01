import { Check, RotateCcw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { UserDisplay } from '@/components/ui/user-display'
import type { CommentThread } from '@/types/comments'

import { CommentComposer } from './CommentComposer'
import { CommentItem } from './CommentItem'

interface Props {
  busy?: boolean
  currentUserEmail: string
  displayNames?: Map<string, string>
  /** Epoch ms of the viewer's last visit; comments after it show unread dots. */
  lastVisit?: number
  onAcknowledge: (commentId: string) => void
  onDelete: (commentId: string) => void
  onEdit: (commentId: string, body: string, mentions: string[]) => void
  onReply: (body: string, mentions: string[]) => void
  onResolve: (resolved: boolean) => void
  thread: CommentThread
}

interface ResolveBarProps {
  busy: boolean
  displayNames?: Map<string, string>
  onResolve: (resolved: boolean) => void
  resolved: boolean
  resolvedBy: null | string
}

export function CommentThreadView({
  busy = false,
  currentUserEmail,
  displayNames,
  lastVisit,
  onAcknowledge,
  onDelete,
  onEdit,
  onReply,
  onResolve,
  thread,
}: Props) {
  const root = thread.comments[0]
  const replies = thread.comments.slice(1)
  if (!root) return null

  const isUnread = (comment: (typeof thread.comments)[number]) =>
    lastVisit !== undefined &&
    comment.author !== currentUserEmail &&
    new Date(comment.created_at).getTime() > lastVisit

  return (
    <div className="border-tertiary bg-primary flex flex-col gap-3 rounded-lg border p-4">
      <ResolveBar
        busy={busy}
        displayNames={displayNames}
        onResolve={onResolve}
        resolved={thread.resolved}
        resolvedBy={thread.resolved_by}
      />

      <CommentItem
        busy={busy}
        comment={root}
        currentUserEmail={currentUserEmail}
        displayNames={displayNames}
        onAcknowledge={() => onAcknowledge(root.id)}
        onDelete={() => onDelete(root.id)}
        onEdit={(body, mentions) => onEdit(root.id, body, mentions)}
        unread={isUnread(root)}
      />

      {replies.length > 0 && (
        <div className="border-tertiary flex flex-col gap-3 border-l pl-4">
          {replies.map((reply) => (
            <CommentItem
              busy={busy}
              comment={reply}
              currentUserEmail={currentUserEmail}
              displayNames={displayNames}
              key={reply.id}
              onAcknowledge={() => onAcknowledge(reply.id)}
              onDelete={() => onDelete(reply.id)}
              onEdit={(body, mentions) => onEdit(reply.id, body, mentions)}
              unread={isUnread(reply)}
            />
          ))}
        </div>
      )}

      {!thread.resolved && (
        <CommentComposer
          busy={busy}
          displayNames={displayNames}
          onSubmit={onReply}
          placeholder="Reply…"
          submitLabel="Reply"
        />
      )}
    </div>
  )
}

function ResolveBar({
  busy,
  displayNames,
  onResolve,
  resolved,
  resolvedBy,
}: ResolveBarProps) {
  if (!resolved) {
    return (
      <div className="flex justify-end">
        <Button
          className="h-7 gap-1 px-2 text-[12px]"
          disabled={busy}
          onClick={() => onResolve(true)}
          size="sm"
          variant="ghost"
        >
          <Check className="size-3" />
          Resolve
        </Button>
      </div>
    )
  }
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-tertiary inline-flex items-center gap-1.5 text-[12px]">
        <Check className="text-action size-3.5" />
        Resolved
        {resolvedBy && (
          <>
            {' by '}
            <UserDisplay
              className="text-secondary"
              displayNames={displayNames}
              email={resolvedBy}
              hideName
              size={16}
            />
            <span className="text-secondary">
              {displayNames?.get(resolvedBy) ?? resolvedBy.split('@')[0]}
            </span>
          </>
        )}
      </span>
      <Button
        className="h-7 gap-1 px-2 text-[12px]"
        disabled={busy}
        onClick={() => onResolve(false)}
        size="sm"
        variant="ghost"
      >
        <RotateCcw className="size-3" />
        Reopen
      </Button>
    </div>
  )
}
