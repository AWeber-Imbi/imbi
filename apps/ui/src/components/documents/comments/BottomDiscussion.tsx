import { useState } from 'react'

import { MessageSquarePlus, MessagesSquare } from 'lucide-react'

import { Button } from '@/components/ui/button'
import type { CommentThread, CommentThreadHandlers } from '@/types/comments'

import { CommentThreadView } from './CommentThreadView'
import { LazyRichComposer } from './LazyRichComposer'

export type CommentFilter = 'all' | 'open' | 'resolved'

interface Props extends CommentThreadHandlers {
  busy?: boolean
  currentUserEmail: string
  displayNames?: Map<string, string>
  lastVisit?: number
  threads: CommentThread[]
}

/**
 * The page-level discussion feed. Unlike inline comments, discussion threads
 * are a flat, always-visible conversation — they are not resolvable and are
 * not filtered. The composer follows the Confluence pattern: a collapsed
 * "Add a comment" trigger at the bottom that expands into the form on click.
 */
export function BottomDiscussion({
  busy = false,
  currentUserEmail,
  displayNames,
  lastVisit,
  onAcknowledge,
  onCreateThread,
  onDelete,
  onEdit,
  onReply,
  onResolve,
  threads,
}: Props) {
  const [composing, setComposing] = useState(false)

  return (
    <section className="mt-8 flex flex-col gap-4">
      <h2 className="text-primary m-0 flex items-center gap-2 text-[16px] font-medium">
        <MessagesSquare className="text-secondary size-[18px]" />
        Discussion
        <span className="bg-secondary text-tertiary rounded px-1.5 text-[12px] tabular-nums">
          {threads.length}
        </span>
      </h2>

      {composing ? (
        <LazyRichComposer
          autoFocus
          busy={busy}
          displayNames={displayNames}
          onCancel={() => setComposing(false)}
          onSubmit={(body, mentions) => {
            onCreateThread(body, mentions)
            setComposing(false)
          }}
          placeholder="Add a comment to the discussion…"
          submitLabel="Comment"
        />
      ) : (
        <div>
          <Button
            className="gap-1.5"
            onClick={() => setComposing(true)}
            size="sm"
            variant="ghost"
          >
            <MessageSquarePlus className="size-3.5" />
            Add a comment
          </Button>
        </div>
      )}

      {threads.length === 0 ? (
        <div className="text-tertiary text-[13.5px]">No comments yet.</div>
      ) : (
        <div className="flex flex-col gap-3">
          {threads.map((thread) => (
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
              resolvable={false}
              thread={thread}
            />
          ))}
        </div>
      )}
    </section>
  )
}
