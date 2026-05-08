import { useCallback, useEffect, useMemo, useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  createProjectDocument,
  deleteProjectDocument,
  listAdminUsers,
  listProjectDocuments,
  patchProjectDocument,
} from '@/api/endpoints'
import { ErrorBanner } from '@/components/ui/error-banner'
import { LoadingState } from '@/components/ui/loading-state'
import { extractApiErrorDetail } from '@/lib/apiError'
import type { Document, DocumentTemplate } from '@/types'

import { DocumentsPinboard } from './DocumentsPinboard'
import { DocumentsPinboardEmpty } from './DocumentsPinboardEmpty'
import { DocumentsPinboardNew } from './DocumentsPinboardNew'
import { DocumentsPinboardReader } from './DocumentsPinboardReader'

interface Props {
  initialAction?: string
  initialDocumentId?: string
  orgSlug: string
  projectId: string
  projectTypeSlugs?: string[]
}

type View =
  | { documentId: string; kind: 'editing' }
  | { documentId: string; kind: 'reading' }
  | { kind: 'creating'; template?: DocumentTemplate | null }
  | { kind: 'list' }

export function ProjectDocumentsTab({
  initialAction,
  initialDocumentId,
  orgSlug,
  projectId,
  projectTypeSlugs,
}: Props) {
  const navigate = useNavigate()
  const [view, setView] = useState<View>(() =>
    viewFromUrl(initialDocumentId, initialAction),
  )
  const qc = useQueryClient()

  const navigateToView = useCallback(
    (next: View) => {
      setView(next)
      const base = `/projects/${projectId}/documents`
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
    [navigate, projectId],
  )

  // Reflect URL changes (e.g. browser back/forward) into local view state.
  useEffect(() => {
    const next = viewFromUrl(initialDocumentId, initialAction)
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

  const documentsKey = ['projectDocuments', orgSlug, projectId] as const

  const {
    data: documents = [],
    error,
    isLoading,
  } = useQuery({
    enabled: !!orgSlug && !!projectId,
    queryFn: ({ signal }) =>
      listProjectDocuments(orgSlug, projectId, undefined, signal),
    queryKey: documentsKey,
  })

  const { data: users = [], error: usersError } = useQuery({
    queryFn: ({ signal }) => listAdminUsers({ is_active: true }, signal),
    queryKey: ['admin-users', 'active'],
  })

  // Display-name enrichment is non-essential — when the admin-users fetch
  // fails, fall back to raw author IDs (existing UserDisplay behavior) but
  // log so the failure is diagnosable rather than truly silent.
  useEffect(() => {
    if (usersError) {
      console.warn(
        'Failed to load admin users for document display names',
        usersError,
      )
    }
  }, [usersError])

  const displayNames = useMemo(() => {
    const m = new Map<string, string>()
    for (const u of users) {
      if (u.email && u.display_name) m.set(u.email, u.display_name)
    }
    return m
  }, [users])

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
      patchProjectDocument(orgSlug, projectId, documentId, [
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
    mutationFn: (draft: { content: string; tags: string[]; title: string }) =>
      createProjectDocument(orgSlug, projectId, draft),
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
      draft: { content: string; tags: string[]; title: string }
    }) =>
      patchProjectDocument(orgSlug, projectId, documentId, [
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
    mutationFn: (documentId: string) =>
      deleteProjectDocument(orgSlug, projectId, documentId),
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
  // the error banner (rendered below) already covers fetch failures and
  // an empty-on-error documents array shouldn't masquerade as a missing document.
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
    (draft: { content: string; tags: string[]; title: string }) => {
      if (view.kind === 'editing') {
        updateMutation.mutate({ documentId: view.documentId, draft })
      } else {
        createMutation.mutate(draft)
      }
    },
    [createMutation, updateMutation, view],
  )

  if (isLoading) return <LoadingState label="Loading documents…" />
  if (error)
    return <ErrorBanner error={error} title="Failed to load documents" />

  if (view.kind === 'creating') {
    return (
      <DocumentsPinboardNew
        allDocuments={documents}
        onDiscard={handleDiscard}
        onSave={handleSave}
        orgSlug={orgSlug}
        saving={createMutation.isPending}
        template={view.template}
      />
    )
  }

  if (editingDocument) {
    return (
      <DocumentsPinboardNew
        allDocuments={documents}
        initialDocument={editingDocument}
        key={editingDocument.id}
        onDiscard={handleDiscard}
        onSave={handleSave}
        orgSlug={orgSlug}
        saving={updateMutation.isPending}
      />
    )
  }

  if (selectedDocument) {
    return (
      <DocumentsPinboardReader
        allDocuments={documents}
        deleting={deleteMutation.isPending}
        displayNames={displayNames}
        document={selectedDocument}
        onBack={() => navigateToView({ kind: 'list' })}
        onDelete={() => deleteMutation.mutate(selectedDocument.id)}
        onEdit={() =>
          navigateToView({ documentId: selectedDocument.id, kind: 'editing' })
        }
        onOpen={(id) => navigateToView({ documentId: id, kind: 'reading' })}
        onTogglePin={() => togglePin(selectedDocument)}
      />
    )
  }

  if (documents.length === 0) {
    return (
      <DocumentsPinboardEmpty
        onCreate={handleCreate}
        orgSlug={orgSlug}
        projectTypeSlugs={projectTypeSlugs}
      />
    )
  }

  return (
    <DocumentsPinboard
      displayNames={displayNames}
      documents={documents}
      onCreate={handleCreate}
      onOpen={(id) => navigateToView({ documentId: id, kind: 'reading' })}
      onTogglePin={togglePin}
    />
  )
}

function viewFromUrl(
  initialDocumentId: string | undefined,
  initialAction: string | undefined,
): View {
  if (initialDocumentId === 'new') return { kind: 'creating' }
  if (initialDocumentId && initialAction === 'edit') {
    return { documentId: initialDocumentId, kind: 'editing' }
  }
  if (initialDocumentId)
    return { documentId: initialDocumentId, kind: 'reading' }
  return { kind: 'list' }
}
