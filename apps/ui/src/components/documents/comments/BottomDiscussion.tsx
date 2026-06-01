import { useMemo } from 'react'

import { MessagesSquare } from 'lucide-react'

import type { CommentThread, CommentThreadHandlers } from '@/types/comments'

import { CommentComposer } from './CommentComposer'
import { CommentThreadView } from './CommentThreadView'

export type CommentFilter = 'all' | 'open' | 'resolved'

interface Props extends CommentThreadHandlers {
  busy?: boolean
  currentUserEmail: string
  displayNames?: Map<string, string>
  filter: CommentFilter
  lastVisit?: number
  threads: CommentThread[]
}

export function BottomDiscussion({
  busy = false,
  currentUserEmail,
  displayNames,
  filter,
  lastVisit,
  onAcknowledge,
  onCreateThread,
  onDelete,
  onEdit,
  onReply,
  onResolve,
  threads,
}: Props) {
  const visible = useMemo(
    () =>
      threads.filter((t) =>
        filter === 'all' ? true : filter === 'open' ? !t.resolved : t.resolved,
      ),
    [threads, filter],
  )

  return (
    <section className="mt-8 flex flex-col gap-4">
      <h2 className="text-primary m-0 flex items-center gap-2 text-[16px] font-medium">
        <MessagesSquare className="text-secondary size-[18px]" />
        Discussion
        <span className="bg-secondary text-tertiary rounded px-1.5 text-[12px] tabular-nums">
          {threads.length}
        </span>
      </h2>

      <CommentComposer
        busy={busy}
        displayNames={displayNames}
        onSubmit={onCreateThread}
        placeholder="Add a comment to the discussion…"
        submitLabel="Comment"
      />

      {visible.length === 0 ? (
        <div className="text-tertiary py-7 text-center text-[13.5px]">
          No comments in this view.
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {visible.map((thread) => (
            <CommentThreadView
              busy={busy}
              currentUserEmail={currentUserEmail}
              displayNames={displayNames}
              key={thread.id}
              lastVisit={lastVisit}
              onAcknowledge={(commentId) => onAcknowledge(thread.id, commentId)}
              onDelete={(commentId) => onDelete(thread.id, commentId)}
              onEdit={(commentId, body, mentions) =>
                onEdit(thread.id, commentId, body, mentions)
              }
              onReply={(body, mentions) => onReply(thread.id, body, mentions)}
              onResolve={(resolved) => onResolve(thread.id, resolved)}
              thread={thread}
            />
          ))}
        </div>
      )}
    </section>
  )
}
