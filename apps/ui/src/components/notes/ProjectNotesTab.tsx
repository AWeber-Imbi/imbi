import { useCallback, useEffect, useMemo, useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  createProjectNote,
  deleteProjectNote,
  listAdminUsers,
  listProjectNotes,
  patchProjectNote,
} from '@/api/endpoints'
import { ErrorBanner } from '@/components/ui/error-banner'
import { LoadingState } from '@/components/ui/loading-state'
import { extractApiErrorDetail } from '@/lib/apiError'
import type { Note, NoteTemplate } from '@/types'

import { NotesPinboard } from './NotesPinboard'
import { NotesPinboardEmpty } from './NotesPinboardEmpty'
import { NotesPinboardNew } from './NotesPinboardNew'
import { NotesPinboardReader } from './NotesPinboardReader'

interface Props {
  initialAction?: string
  initialNoteId?: string
  orgSlug: string
  projectId: string
  projectTypeSlugs?: string[]
}

type View =
  | { kind: 'creating'; template?: NoteTemplate | null }
  | { kind: 'editing'; noteId: string }
  | { kind: 'list' }
  | { kind: 'reading'; noteId: string }

export function ProjectNotesTab({
  initialAction,
  initialNoteId,
  orgSlug,
  projectId,
  projectTypeSlugs,
}: Props) {
  const navigate = useNavigate()
  const [view, setView] = useState<View>(() =>
    viewFromUrl(initialNoteId, initialAction),
  )
  const qc = useQueryClient()

  const navigateToView = useCallback(
    (next: View) => {
      setView(next)
      const base = `/projects/${projectId}/notes`
      if (next.kind === 'reading') {
        navigate(`${base}/${encodeURIComponent(next.noteId)}`, {
          replace: true,
        })
      } else if (next.kind === 'editing') {
        navigate(`${base}/${encodeURIComponent(next.noteId)}/edit`, {
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
    const next = viewFromUrl(initialNoteId, initialAction)
    setView((prev) => {
      if (
        prev.kind === next.kind &&
        ('noteId' in prev ? prev.noteId : null) ===
          ('noteId' in next ? next.noteId : null)
      ) {
        return prev
      }
      return next
    })
  }, [initialNoteId, initialAction])

  const notesKey = ['projectNotes', orgSlug, projectId] as const

  const {
    data: notes = [],
    error,
    isLoading,
  } = useQuery({
    enabled: !!orgSlug && !!projectId,
    queryFn: ({ signal }) =>
      listProjectNotes(orgSlug, projectId, undefined, signal),
    queryKey: notesKey,
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
        'Failed to load admin users for note display names',
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
    Note,
    unknown,
    { noteId: string; pinned: boolean },
    { previous?: Note[] }
  >({
    mutationFn: ({ noteId, pinned }: { noteId: string; pinned: boolean }) =>
      patchProjectNote(orgSlug, projectId, noteId, [
        { op: 'replace', path: '/is_pinned', value: pinned },
      ]),
    onError: (err, _vars, ctx) => {
      if (ctx?.previous) qc.setQueryData(notesKey, ctx.previous)
      toast.error(`Pin failed: ${extractApiErrorDetail(err)}`)
    },
    onMutate: async ({ noteId, pinned }) => {
      await qc.cancelQueries({ queryKey: notesKey })
      const previous = qc.getQueryData<Note[]>(notesKey)
      if (previous) {
        qc.setQueryData<Note[]>(
          notesKey,
          previous.map((n) =>
            n.id === noteId ? { ...n, is_pinned: pinned } : n,
          ),
        )
      }
      return { previous }
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: notesKey })
    },
  })

  const createMutation = useMutation({
    mutationFn: (draft: { content: string; tags: string[]; title: string }) =>
      createProjectNote(orgSlug, projectId, draft),
    onError: (err) => {
      toast.error(`Save failed: ${extractApiErrorDetail(err)}`)
    },
    onSuccess: (note) => {
      qc.setQueryData<Note[]>(notesKey, (prev) =>
        prev ? [note, ...prev] : [note],
      )
      qc.invalidateQueries({ queryKey: notesKey })
      toast.success('Note saved')
      navigateToView({ kind: 'reading', noteId: note.id })
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({
      draft,
      noteId,
    }: {
      draft: { content: string; tags: string[]; title: string }
      noteId: string
    }) =>
      patchProjectNote(orgSlug, projectId, noteId, [
        { op: 'replace', path: '/title', value: draft.title },
        { op: 'replace', path: '/content', value: draft.content },
        { op: 'replace', path: '/tags', value: draft.tags },
      ]),
    onError: (err) => {
      toast.error(`Update failed: ${extractApiErrorDetail(err)}`)
    },
    onSuccess: (note) => {
      qc.setQueryData<Note[]>(notesKey, (prev) =>
        prev ? prev.map((n) => (n.id === note.id ? note : n)) : [note],
      )
      qc.invalidateQueries({ queryKey: notesKey })
      toast.success('Note updated')
      navigateToView({ kind: 'reading', noteId: note.id })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (noteId: string) =>
      deleteProjectNote(orgSlug, projectId, noteId),
    onError: (err) => {
      toast.error(`Delete failed: ${extractApiErrorDetail(err)}`)
    },
    onSuccess: (_data, noteId) => {
      qc.setQueryData<Note[]>(notesKey, (prev) =>
        prev ? prev.filter((n) => n.id !== noteId) : [],
      )
      qc.invalidateQueries({ queryKey: notesKey })
      toast.success('Note deleted')
      navigateToView({ kind: 'list' })
    },
  })

  const togglePin = useCallback(
    (note: Note) => {
      pinMutation.mutate({ noteId: note.id, pinned: !note.is_pinned })
    },
    [pinMutation],
  )

  const selectedNote = useMemo(
    () =>
      view.kind === 'reading'
        ? (notes.find((n) => n.id === view.noteId) ?? null)
        : null,
    [notes, view],
  )

  const editingNote = useMemo(
    () =>
      view.kind === 'editing'
        ? (notes.find((n) => n.id === view.noteId) ?? null)
        : null,
    [notes, view],
  )

  // If a deep-linked note id doesn't exist (deleted, wrong id), surface a
  // toast and bounce back to the list view rather than silently rendering
  // the empty list. Skip while the notes query is loading or errored —
  // the error banner (rendered below) already covers fetch failures and
  // an empty-on-error notes array shouldn't masquerade as a missing note.
  useEffect(() => {
    if (isLoading || error) return
    if (view.kind !== 'reading' && view.kind !== 'editing') return
    if (notes.some((n) => n.id === view.noteId)) return
    toast.error('Note not found')
    navigateToView({ kind: 'list' })
  }, [error, isLoading, navigateToView, notes, view])

  const handleCreate = useCallback(
    (template?: NoteTemplate) => {
      navigateToView({ kind: 'creating', template: template ?? null })
    },
    [navigateToView],
  )

  const handleDiscard = useCallback(() => {
    if (view.kind === 'editing') {
      navigateToView({ kind: 'reading', noteId: view.noteId })
    } else {
      navigateToView({ kind: 'list' })
    }
  }, [navigateToView, view])

  const handleSave = useCallback(
    (draft: { content: string; tags: string[]; title: string }) => {
      if (view.kind === 'editing') {
        updateMutation.mutate({ draft, noteId: view.noteId })
      } else {
        createMutation.mutate(draft)
      }
    },
    [createMutation, updateMutation, view],
  )

  if (isLoading) return <LoadingState label="Loading notes…" />
  if (error) return <ErrorBanner error={error} title="Failed to load notes" />

  if (view.kind === 'creating') {
    return (
      <NotesPinboardNew
        allNotes={notes}
        onDiscard={handleDiscard}
        onSave={handleSave}
        orgSlug={orgSlug}
        saving={createMutation.isPending}
        template={view.template}
      />
    )
  }

  if (editingNote) {
    return (
      <NotesPinboardNew
        allNotes={notes}
        initialNote={editingNote}
        key={editingNote.id}
        onDiscard={handleDiscard}
        onSave={handleSave}
        orgSlug={orgSlug}
        saving={updateMutation.isPending}
      />
    )
  }

  if (selectedNote) {
    return (
      <NotesPinboardReader
        allNotes={notes}
        deleting={deleteMutation.isPending}
        displayNames={displayNames}
        note={selectedNote}
        onBack={() => navigateToView({ kind: 'list' })}
        onDelete={() => deleteMutation.mutate(selectedNote.id)}
        onEdit={() =>
          navigateToView({ kind: 'editing', noteId: selectedNote.id })
        }
        onOpen={(id) => navigateToView({ kind: 'reading', noteId: id })}
        onTogglePin={() => togglePin(selectedNote)}
      />
    )
  }

  if (notes.length === 0) {
    return (
      <NotesPinboardEmpty
        onCreate={handleCreate}
        orgSlug={orgSlug}
        projectTypeSlugs={projectTypeSlugs}
      />
    )
  }

  return (
    <NotesPinboard
      displayNames={displayNames}
      notes={notes}
      onCreate={handleCreate}
      onOpen={(id) => navigateToView({ kind: 'reading', noteId: id })}
      onTogglePin={togglePin}
    />
  )
}

function viewFromUrl(
  initialNoteId: string | undefined,
  initialAction: string | undefined,
): View {
  if (initialNoteId === 'new') return { kind: 'creating' }
  if (initialNoteId && initialAction === 'edit') {
    return { kind: 'editing', noteId: initialNoteId }
  }
  if (initialNoteId) return { kind: 'reading', noteId: initialNoteId }
  return { kind: 'list' }
}
