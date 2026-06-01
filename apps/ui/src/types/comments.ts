// Document comment types.
//
// Hand-written because the comments API is not yet in the committed openapi
// snapshot (the same reason Document/Tag are inlined in `index.ts`). Once the
// comments endpoints are deployed, re-run `npm run codegen:fetch` and migrate
// these to the generated `Schemas[...]` equivalents.

export interface AddReplyBody {
  body: string
  mentions?: string[]
}

export interface Comment {
  acknowledged_by: string[]
  /** Author email address. */
  author: string
  body: string
  created_at: string
  edited: boolean
  id: string
  mentions: string[]
  thread_id: string
  updated_at: null | string
}

export interface CommentAnchor {
  prefix: string
  quote: string
  start: number
  suffix: string
}

export interface CommentThread {
  anchor: CommentAnchor | null
  comments: Comment[] // oldest-first; [0] is the root comment
  created_at: string
  created_by: string
  document_id: string
  id: string
  kind: 'inline' | 'page'
  resolved: boolean
  resolved_at: null | string
  resolved_by: null | string
  updated_at: null | string
}

/**
 * Callbacks for mutating a document's comment threads, produced by
 * `useDocumentComments` and consumed by the discussion UI.
 */
export interface CommentThreadHandlers {
  onAcknowledge: (threadId: string, commentId: string) => void
  onCreateThread: (body: string, inline?: { anchor: CommentAnchor }) => void
  onDelete: (threadId: string, commentId: string) => void
  onEdit: (threadId: string, commentId: string, body: string) => void
  onReply: (threadId: string, body: string) => void
  onResolve: (threadId: string, resolved: boolean) => void
}

export interface CreateThreadBody {
  anchor?: CommentAnchor
  body: string
  kind: 'inline' | 'page'
  mentions?: string[]
}
