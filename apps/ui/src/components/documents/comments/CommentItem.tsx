import type { ReactNode } from 'react'
import { useState } from 'react'

import { formatDistanceToNow } from 'date-fns'
import { Pencil, Reply, ThumbsUp, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { UserDisplay } from '@/components/ui/user-display'
import { cn } from '@/lib/utils'
import type { Comment } from '@/types/comments'

import { CommentComposer } from './CommentComposer'

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
  onEdit: (body: string) => void
  onReply?: () => void
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
      </div>

      {editing ? (
        <CommentComposer
          autoFocus
          busy={busy}
          initial={comment.body}
          onCancel={() => setEditing(false)}
          onSubmit={(body) => {
            onEdit(body)
            setEditing(false)
          }}
          submitLabel="Save"
        />
      ) : (
        <>
          <div className="text-primary text-[13.5px] leading-normal whitespace-pre-wrap">
            {comment.body}
          </div>
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
