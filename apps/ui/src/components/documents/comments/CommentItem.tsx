import type { ReactNode } from 'react'
import { useMemo, useState } from 'react'

import { formatDistanceToNow } from 'date-fns'
import { Pencil, Reply, ThumbsUp, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { UserDisplay } from '@/components/ui/user-display'
import { cn } from '@/lib/utils'
import type { Comment } from '@/types/comments'

import { CommentComposer } from './CommentComposer'
import { parseBody } from './mentions'

interface ActionsProps {
  ackCount: number
  acknowledged: boolean
  mine: boolean
  onAcknowledge: () => void
  onDelete: () => void
  onEdit: () => void
  onReply?: () => void
}

interface Props {
  busy?: boolean
  comment: Comment
  currentUserEmail: string
  displayNames?: Map<string, string>
  onAcknowledge: () => void
  onDelete: () => void
  onEdit: (body: string, mentions: string[]) => void
  onReply?: () => void
  /** Show an unread dot — comment is newer than the viewer's last visit. */
  unread?: boolean
}

export function CommentItem({
  busy = false,
  comment,
  currentUserEmail,
  displayNames,
  onAcknowledge,
  onDelete,
  onEdit,
  onReply,
  unread = false,
}: Props) {
  const [editing, setEditing] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const mine = comment.author === currentUserEmail
  const acknowledged = comment.acknowledged_by.includes(currentUserEmail)
  const ackCount = comment.acknowledged_by.length

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-2">
        <UserDisplay
          className="text-secondary"
          displayNames={displayNames}
          email={comment.author}
          size={22}
          textClassName="text-[12.5px] font-medium text-primary"
        />
        <span className="text-tertiary text-[11.5px]">
          {formatDistanceToNow(new Date(comment.created_at), {
            addSuffix: true,
          })}
          {comment.edited && ' · edited'}
        </span>
        {unread && (
          <span
            aria-label="New since your last visit"
            className="comment-unread-dot"
            title="New since your last visit"
          />
        )}
      </div>

      {editing ? (
        <CommentComposer
          autoFocus
          busy={busy}
          displayNames={displayNames}
          initial={comment.body}
          onCancel={() => setEditing(false)}
          onSubmit={(body, mentions) => {
            onEdit(body, mentions)
            setEditing(false)
          }}
          submitLabel="Save"
        />
      ) : (
        <>
          <CommentBody
            body={comment.body}
            displayNames={displayNames}
            mentions={comment.mentions}
          />
          <CommentActions
            ackCount={ackCount}
            acknowledged={acknowledged}
            mine={mine}
            onAcknowledge={onAcknowledge}
            onDelete={() => setConfirmDelete(true)}
            onEdit={() => setEditing(true)}
            onReply={onReply}
          />
        </>
      )}

      <ConfirmDialog
        confirmLabel="Delete"
        description="This comment will be permanently removed."
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => {
          setConfirmDelete(false)
          onDelete()
        }}
        open={confirmDelete}
        title="Delete comment?"
      />
    </div>
  )
}

function ActionButton({
  ariaLabel,
  className,
  icon,
  label,
  onClick,
}: {
  ariaLabel?: string
  className?: string
  icon: ReactNode
  label: number | string
  onClick: () => void
}) {
  return (
    <Button
      aria-label={ariaLabel}
      className={cn('h-7 gap-1 px-2 text-[12px]', className)}
      onClick={onClick}
      size="sm"
      variant="ghost"
    >
      {icon}
      {label}
    </Button>
  )
}

// fallow-ignore-next-line complexity
function CommentActions({
  ackCount,
  acknowledged,
  mine,
  onAcknowledge,
  onDelete,
  onEdit,
  onReply,
}: ActionsProps) {
  return (
    <div className="text-tertiary flex flex-wrap items-center gap-1">
      <ActionButton
        ariaLabel={acknowledged ? 'Remove acknowledgement' : 'Acknowledge'}
        className={cn(acknowledged && 'text-action')}
        icon={<ThumbsUp className="size-3" />}
        label={ackCount > 0 ? ackCount : ''}
        onClick={onAcknowledge}
      />
      {onReply && (
        <ActionButton
          icon={<Reply className="size-3" />}
          label="Reply"
          onClick={onReply}
        />
      )}
      {mine && <OwnerActions onDelete={onDelete} onEdit={onEdit} />}
    </div>
  )
}

/**
 * Render a comment body, styling `@Display Name` tokens that resolve to one of
 * the comment's mentioned users. Matching is restricted to the comment's
 * `mentions` (resolved emails) so unrelated `@text` is left as plain text.
 */
function CommentBody({
  body,
  displayNames,
  mentions,
}: {
  body: string
  displayNames?: Map<string, string>
  mentions: string[]
}) {
  const names = useMemo(() => {
    const m = new Map<string, string>()
    if (!displayNames) return m
    for (const email of mentions) {
      const name = displayNames.get(email)
      if (name) m.set(email, name)
    }
    return m
  }, [displayNames, mentions])

  const segments = useMemo(() => parseBody(body, names), [body, names])

  return (
    <div className="text-primary text-[13.5px] leading-normal whitespace-pre-wrap">
      {segments.map((seg, i) =>
        seg.type === 'mention' ? (
          <span className="comment-mention" key={i}>
            {seg.text}
          </span>
        ) : (
          <span key={i}>{seg.text}</span>
        ),
      )}
    </div>
  )
}

function OwnerActions({
  onDelete,
  onEdit,
}: {
  onDelete: () => void
  onEdit: () => void
}) {
  return (
    <>
      <ActionButton
        icon={<Pencil className="size-3" />}
        label="Edit"
        onClick={onEdit}
      />
      <ActionButton
        className="text-destructive"
        icon={<Trash2 className="size-3" />}
        label="Delete"
        onClick={onDelete}
      />
    </>
  )
}
