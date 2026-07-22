import { useCallback, useEffect, useMemo, useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { useAuth } from '@/hooks/useAuth'
import { useDocumentComments } from '@/hooks/useDocumentComments'
import { useUserDisplayNames } from '@/hooks/useUserDisplayNames'
import { extractApiErrorDetail } from '@/lib/apiError'
import type { Document, DocumentTemplate, PatchOperation } from '@/types'

export interface DocumentDraft {
  content: string
  tags: string[]
  title: string
}

/**
 * Where a set of documents lives — every API call and route the
 * documents UI needs, abstracted over the attachment target (project,
 * user, the whole org) so the exact same pinboard/reader/editor flow
 * renders in each context.
 */
export interface DocumentsScope {
  /** Route prefix the list/read/edit/new views live under. */
  basePath: string
  /** Project id for project-scoped comment routes; null = generic. */
  commentsProjectId: null | string
  create: (draft: DocumentDraft) => Promise<Document>
  /** Heading for the empty state. */
  emptyHeading?: string
  list: (signal?: AbortSignal) => Promise<Document[]>
  patch: (documentId: string, operations: PatchOperation[]) => Promise<Document>
  projectTypeSlugs?: string[]
  queryKey: readonly unknown[]
  remove: (documentId: string) => Promise<void>
  /** Hide the redundant Author column (e.g. a user's own documents). */
  showAuthor?: boolean
  templateContext: 'org' | 'project' | 'project_type' | 'user'
}

type DocumentsView =
  | { documentId: string; kind: 'editing' }
  | { documentId: string; kind: 'reading' }
  | { kind: 'creating'; template?: DocumentTemplate | null }
  | { kind: 'list' }

/**
 * Owns the document list query, the view state machine (list / read /
 * edit / create, mirrored into the URL under `scope.basePath`), and
 * the create/update/pin/delete mutations for one {@link DocumentsScope}.
 * Shared by the project tab, the user profile tab, and the org-wide
 * Documents page.
 */
// fallow-ignore-next-line complexity
export function useDocumentsController(
  orgSlug: string,
  scope: DocumentsScope,
  initialDocumentId?: string,
  initialAction?: string,
) {
  const navigate = useNavigate()
  const [view, setView] = useState<DocumentsView>(() =>
    viewFromUrl(initialDocumentId, initialAction),
  )
  const qc = useQueryClient()

  const navigateToView = useCallback(
    (next: DocumentsView) => {
      setView(next)
      const base = scope.basePath
      if (next.kind === 'reading') {
        navigate(`${base}/${encodeURIComponent(next.documentId)}`, {
          replace: true,
        })
      } else if (next.kind === 'editing') {
        navigate(`${base}/${encodeURIComponent(next.documentId)}/edit`, {
          replace: true,
        })
      } else if (next.kind === 'creating') {
        navigate(`${base}/new`, { replace: true })
      } else {
        navigate(base, { replace: true })
      }
    },
    [navigate, scope.basePath],
  )

  // Reflect URL changes (e.g. browser back/forward) into local view state.
  useEffect(() => {
    const next = viewFromUrl(initialDocumentId, initialAction)
    // fallow-ignore-next-line complexity
    setView((prev) => {
      if (
        prev.kind === next.kind &&
        ('documentId' in prev ? prev.documentId : null) ===
          ('documentId' in next ? next.documentId : null)
      ) {
        return prev
      }
      return next
    })
  }, [initialDocumentId, initialAction])

  const documentsKey = scope.queryKey

  const {
    data: documents = [],
    error,
    isLoading,
  } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => scope.list(signal),
    queryKey: documentsKey,
  })

  const { displayNames, isError: usersError } = useUserDisplayNames()
  const { user } = useAuth()
  const currentUserEmail = user?.email ?? ''

  useEffect(() => {
    if (usersError) {
      console.warn('Failed to load admin users for document display names')
    }
  }, [usersError])

  const pinMutation = useMutation<
    Document,
    unknown,
    { documentId: string; pinned: boolean },
    { previous?: Document[] }
  >({
    mutationFn: ({
      documentId,
      pinned,
    }: {
      documentId: string
      pinned: boolean
    }) =>
      scope.patch(documentId, [
        { op: 'replace', path: '/is_pinned', value: pinned },
      ]),
    onError: (err, _vars, ctx) => {
      if (ctx?.previous) qc.setQueryData(documentsKey, ctx.previous)
      toast.error(`Pin failed: ${extractApiErrorDetail(err)}`)
    },
    onMutate: async ({ documentId, pinned }) => {
      await qc.cancelQueries({ queryKey: documentsKey })
      const previous = qc.getQueryData<Document[]>(documentsKey)
      if (previous) {
        qc.setQueryData<Document[]>(
          documentsKey,
          previous.map((n) =>
            n.id === documentId ? { ...n, is_pinned: pinned } : n,
          ),
        )
      }
      return { previous }
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: documentsKey })
    },
  })

  const createMutation = useMutation({
    mutationFn: (draft: DocumentDraft) => scope.create(draft),
    onError: (err) => {
      toast.error(`Save failed: ${extractApiErrorDetail(err)}`)
    },
    onSuccess: (document) => {
      qc.setQueryData<Document[]>(documentsKey, (prev) =>
        prev ? [document, ...prev] : [document],
      )
      qc.invalidateQueries({ queryKey: documentsKey })
      toast.success('Document saved')
      navigateToView({ documentId: document.id, kind: 'reading' })
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({
      documentId,
      draft,
    }: {
      documentId: string
      draft: DocumentDraft
    }) =>
      scope.patch(documentId, [
        { op: 'replace', path: '/title', value: draft.title },
        { op: 'replace', path: '/content', value: draft.content },
        { op: 'replace', path: '/tags', value: draft.tags },
      ]),
    onError: (err) => {
      toast.error(`Update failed: ${extractApiErrorDetail(err)}`)
    },
    onSuccess: (document) => {
      qc.setQueryData<Document[]>(documentsKey, (prev) =>
        prev
          ? prev.map((n) => (n.id === document.id ? document : n))
          : [document],
      )
      qc.invalidateQueries({ queryKey: documentsKey })
      toast.success('Document updated')
      navigateToView({ documentId: document.id, kind: 'reading' })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (documentId: string) => scope.remove(documentId),
    onError: (err) => {
      toast.error(`Delete failed: ${extractApiErrorDetail(err)}`)
    },
    onSuccess: (_data, documentId) => {
      qc.setQueryData<Document[]>(documentsKey, (prev) =>
        prev ? prev.filter((n) => n.id !== documentId) : [],
      )
      qc.invalidateQueries({ queryKey: documentsKey })
      toast.success('Document deleted')
      navigateToView({ kind: 'list' })
    },
  })

  const togglePin = useCallback(
    (document: Document) => {
      pinMutation.mutate({
        documentId: document.id,
        pinned: !document.is_pinned,
      })
    },
    [pinMutation],
  )

  const selectedDocument = useMemo(
    () =>
      view.kind === 'reading'
        ? (documents.find((n) => n.id === view.documentId) ?? null)
        : null,
    [documents, view],
  )

  const comments = useDocumentComments(
    orgSlug,
    scope.commentsProjectId,
    selectedDocument?.id ?? '',
    currentUserEmail,
  )

  const editingDocument = useMemo(
    () =>
      view.kind === 'editing'
        ? (documents.find((n) => n.id === view.documentId) ?? null)
        : null,
    [documents, view],
  )

  // If a deep-linked document id doesn't exist (deleted, wrong id), surface a
  // toast and bounce back to the list view rather than silently rendering
  // the empty list. Skip while the documents query is loading or errored —
  // the error banner already covers fetch failures and an empty-on-error
  // documents array shouldn't masquerade as a missing document.
  // fallow-ignore-next-line complexity
  useEffect(() => {
    if (isLoading || error) return
    if (view.kind !== 'reading' && view.kind !== 'editing') return
    if (documents.some((n) => n.id === view.documentId)) return
    toast.error('Document not found')
    navigateToView({ kind: 'list' })
  }, [error, isLoading, navigateToView, documents, view])

  const handleCreate = useCallback(
    (template?: DocumentTemplate) => {
      navigateToView({ kind: 'creating', template: template ?? null })
    },
    [navigateToView],
  )

  const handleDiscard = useCallback(() => {
    if (view.kind === 'editing') {
      navigateToView({ documentId: view.documentId, kind: 'reading' })
    } else {
      navigateToView({ kind: 'list' })
    }
  }, [navigateToView, view])

  const handleSave = useCallback(
    (draft: DocumentDraft) => {
      if (view.kind === 'editing') {
        updateMutation.mutate({ documentId: view.documentId, draft })
      } else {
        createMutation.mutate(draft)
      }
    },
    [createMutation, updateMutation, view],
  )

  return {
    comments,
    createPending: createMutation.isPending,
    currentUserEmail,
    deleteDocument: deleteMutation.mutate,
    deletePending: deleteMutation.isPending,
    displayNames,
    documents,
    editingDocument,
    error,
    handleCreate,
    handleDiscard,
    handleSave,
    isLoading,
    navigateToView,
    selectedDocument,
    togglePin,
    updatePending: updateMutation.isPending,
    view,
  }
}

// fallow-ignore-next-line complexity
function viewFromUrl(
  initialDocumentId: string | undefined,
  initialAction: string | undefined,
): DocumentsView {
  if (initialDocumentId === 'new') return { kind: 'creating' }
  if (initialDocumentId && initialAction === 'edit') {
    return { documentId: initialDocumentId, kind: 'editing' }
  }
  if (initialDocumentId)
    return { documentId: initialDocumentId, kind: 'reading' }
  return { kind: 'list' }
}
