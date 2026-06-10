import { useCallback, useMemo } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  acknowledgeComment,
  addCommentReply,
  createCommentThread,
  deleteComment,
  editComment,
  listDocumentComments,
  resolveCommentThread,
} from '@/api/endpoints'
import { extractApiErrorDetail } from '@/lib/apiError'
import type {
  Comment,
  CommentAnchor,
  CommentThread,
  CommentThreadHandlers,
} from '@/types/comments'

interface CommentVars {
  commentId: string
  threadId: string
}

interface CreateThreadVars {
  anchor?: CommentAnchor
  body: string
  mentions: string[]
}

interface EditVars extends CommentVars {
  body: string
  mentions: string[]
}

interface ReplyVars {
  body: string
  mentions: string[]
  threadId: string
}

interface Result extends CommentThreadHandlers {
  comments: CommentThread[]
  commentsBusy: boolean
}

interface ThreadVars {
  resolved: boolean
  threadId: string
}

/**
 * Owns the page-level comment thread query and its optimistic mutations for a
 * single document. The query stays disabled until a documentId is supplied
 * (i.e. while a document is being read), mirroring the document data flow in
 * ProjectDocumentsTab. Optimistic updates are modeled on its `pinMutation`.
 */
export function useDocumentComments(
  orgSlug: string,
  projectId: null | string,
  documentId: string,
  currentUserEmail: string,
): Result {
  const qc = useQueryClient()
  const commentsKey = useMemo(
    () => ['documentComments', orgSlug, projectId, documentId] as const,
    [orgSlug, projectId, documentId],
  )

  const { data: comments = [], isFetching: commentsBusy } = useQuery({
    enabled: !!orgSlug && !!documentId,
    queryFn: ({ signal }) =>
      listDocumentComments(orgSlug, projectId, documentId, signal),
    queryKey: commentsKey,
  })

  // Apply a transform to the cached threads array and snapshot it for rollback.
  const optimistic = useCallback(
    async (update: (prev: CommentThread[]) => CommentThread[]) => {
      await qc.cancelQueries({ queryKey: commentsKey })
      const previous = qc.getQueryData<CommentThread[]>(commentsKey)
      if (previous)
        qc.setQueryData<CommentThread[]>(commentsKey, update(previous))
      return { previous }
    },
    [qc, commentsKey],
  )

  const rollback = useCallback(
    (ctx: undefined | { previous?: CommentThread[] }) => {
      if (ctx?.previous) qc.setQueryData(commentsKey, ctx.previous)
    },
    [qc, commentsKey],
  )

  const settle = useCallback(() => {
    qc.invalidateQueries({ queryKey: commentsKey })
  }, [qc, commentsKey])

  const fail = useCallback(
    (label: string) => (err: unknown) => {
      toast.error(`${label}: ${extractApiErrorDetail(err)}`)
    },
    [],
  )

  const createThreadMutation = useMutation<
    CommentThread,
    unknown,
    CreateThreadVars
  >({
    mutationFn: ({ anchor, body, mentions }) =>
      createCommentThread(orgSlug, projectId, documentId, {
        body,
        mentions,
        ...(anchor ? { anchor, kind: 'inline' } : { kind: 'page' }),
      }),
    onError: fail('Comment failed'),
    onSettled: settle,
    onSuccess: (thread) => {
      qc.setQueryData<CommentThread[]>(commentsKey, (prev) =>
        prev ? [...prev, thread] : [thread],
      )
    },
  })

  const replyMutation = useMutation<Comment, unknown, ReplyVars>({
    mutationFn: ({ body, mentions, threadId }) =>
      addCommentReply(orgSlug, projectId, documentId, threadId, {
        body,
        mentions,
      }),
    onError: fail('Reply failed'),
    onSettled: settle,
    onSuccess: (comment, { threadId }) => {
      qc.setQueryData<CommentThread[]>(commentsKey, (prev) =>
        prev?.map((t) =>
          t.id === threadId ? { ...t, comments: [...t.comments, comment] } : t,
        ),
      )
    },
  })

  const resolveMutation = useMutation<
    CommentThread,
    unknown,
    ThreadVars,
    { previous?: CommentThread[] }
  >({
    mutationFn: ({ resolved, threadId }) =>
      resolveCommentThread(orgSlug, projectId, documentId, threadId, resolved),
    onError: (err, _vars, ctx) => {
      rollback(ctx)
      fail('Update failed')(err)
    },
    onMutate: ({ resolved, threadId }) =>
      optimistic((prev) =>
        prev.map((t) =>
          t.id === threadId
            ? {
                ...t,
                resolved,
                resolved_at: resolved ? new Date().toISOString() : null,
                resolved_by: resolved ? currentUserEmail : null,
              }
            : t,
        ),
      ),
    onSettled: settle,
  })

  const acknowledgeMutation = useMutation<
    Comment,
    unknown,
    CommentVars,
    { previous?: CommentThread[] }
  >({
    mutationFn: ({ commentId, threadId }) =>
      acknowledgeComment(orgSlug, projectId, documentId, threadId, commentId),
    onError: (err, _vars, ctx) => {
      rollback(ctx)
      fail('Acknowledge failed')(err)
    },
    onMutate: ({ commentId, threadId }) =>
      optimistic((prev) =>
        mapComment(prev, threadId, commentId, (c) => ({
          ...c,
          acknowledged_by: c.acknowledged_by.includes(currentUserEmail)
            ? c.acknowledged_by.filter((e) => e !== currentUserEmail)
            : [...c.acknowledged_by, currentUserEmail],
        })),
      ),
    onSettled: settle,
  })

  const editMutation = useMutation<
    Comment,
    unknown,
    EditVars,
    { previous?: CommentThread[] }
  >({
    mutationFn: ({ body, commentId, mentions, threadId }) =>
      editComment(
        orgSlug,
        projectId,
        documentId,
        threadId,
        commentId,
        body,
        mentions,
      ),
    onError: (err, _vars, ctx) => {
      rollback(ctx)
      fail('Edit failed')(err)
    },
    onMutate: ({ body, commentId, mentions, threadId }) =>
      optimistic((prev) =>
        mapComment(prev, threadId, commentId, (c) => ({
          ...c,
          body,
          edited: true,
          mentions,
        })),
      ),
    onSettled: settle,
  })

  const deleteCommentMutation = useMutation<
    void,
    unknown,
    CommentVars,
    { previous?: CommentThread[] }
  >({
    mutationFn: ({ commentId, threadId }) =>
      deleteComment(orgSlug, projectId, documentId, threadId, commentId),
    onError: (err, _vars, ctx) => {
      rollback(ctx)
      fail('Delete failed')(err)
    },
    onMutate: ({ commentId, threadId }) =>
      optimistic((prev) => removeComment(prev, threadId, commentId)),
    onSettled: settle,
  })

  return {
    comments,
    commentsBusy,
    onAcknowledge: (threadId, commentId) =>
      acknowledgeMutation.mutate({ commentId, threadId }),
    onCreateThread: (body, mentions, inline) =>
      createThreadMutation.mutate({ anchor: inline?.anchor, body, mentions }),
    onDelete: (threadId, commentId) =>
      deleteCommentMutation.mutate({ commentId, threadId }),
    onEdit: (threadId, commentId, body, mentions) =>
      editMutation.mutate({ body, commentId, mentions, threadId }),
    onReply: (threadId, body, mentions) =>
      replyMutation.mutate({ body, mentions, threadId }),
    onResolve: (threadId, resolved) =>
      resolveMutation.mutate({ resolved, threadId }),
  }
}

/** True when `commentId` is the root of a thread that has no replies. */
function isLoneRoot(thread: CommentThread, commentId: string): boolean {
  return thread.comments.length === 1 && thread.comments[0]?.id === commentId
}

/** Replace one comment within one thread, leaving everything else untouched. */
function mapComment(
  threads: CommentThread[],
  threadId: string,
  commentId: string,
  update: (comment: Comment) => Comment,
): CommentThread[] {
  return threads.map((t) =>
    t.id === threadId
      ? {
          ...t,
          comments: t.comments.map((c) => (c.id === commentId ? update(c) : c)),
        }
      : t,
  )
}

/**
 * Remove one comment from a thread. Deleting the root of a reply-less thread
 * removes the whole thread.
 */
function removeComment(
  threads: CommentThread[],
  threadId: string,
  commentId: string,
): CommentThread[] {
  return threads.flatMap((t) => {
    if (t.id !== threadId) return [t]
    if (isLoneRoot(t, commentId)) return []
    return [{ ...t, comments: t.comments.filter((c) => c.id !== commentId) }]
  })
}
