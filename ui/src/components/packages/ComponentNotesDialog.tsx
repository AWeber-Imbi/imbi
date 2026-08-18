import { useEffect, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { StickyNote } from 'lucide-react'

import { listComponentNotes } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { Sk } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { queryKeys } from '@/lib/queryKeys'

interface ComponentNotesDialogProps {
  canWrite: boolean
  componentReleaseId: string
  isPending: boolean
  onAddNote: (body: string) => Promise<unknown>
  onOpenChange: (open: boolean) => void
  open: boolean
  orgSlug: string
  purlName: string
  version: string
}

/**
 * The governance audit trail for one package version: why it was
 * marked, what to migrate to, who to ask.
 *
 * Notes are append-only and visible to every team — a component is a
 * shared identity, so the team that marked it and the teams that have
 * to act on the mark are rarely the same people.
 */
export function ComponentNotesDialog({
  canWrite,
  componentReleaseId,
  isPending,
  onAddNote,
  onOpenChange,
  open,
  orgSlug,
  purlName,
  version,
}: ComponentNotesDialogProps) {
  const [draft, setDraft] = useState('')

  // Clear the draft between openings so a note typed for one version
  // cannot be submitted against another.
  useEffect(() => {
    if (open) setDraft('')
  }, [open, componentReleaseId])

  const { data, isError, isLoading } = useQuery({
    enabled: open && !!componentReleaseId,
    queryFn: ({ signal }) =>
      listComponentNotes(orgSlug, componentReleaseId, signal),
    queryKey: queryKeys.componentNotes(orgSlug, componentReleaseId),
  })

  const trimmed = draft.trim()
  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <StickyNote className="text-tertiary size-4" />
            Notes
          </DialogTitle>
          <DialogDescription>
            <span className="font-mono text-xs">{purlName}</span> @{' '}
            <span className="font-mono text-xs">{version}</span>. Notes are
            visible to every team and are never edited or removed.
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-72 space-y-3 overflow-y-auto p-6">
          {isLoading && <Sk className="h-16 w-full" />}
          {!isLoading && isError && (
            <p className="text-danger text-sm">Could not load the notes.</p>
          )}
          {!isLoading && !isError && (data ?? []).length === 0 && (
            <p className="text-tertiary text-sm">No notes yet.</p>
          )}
          {(data ?? []).map((note) => (
            <div
              className="border-tertiary border-b pb-3 last:border-0"
              key={note.id}
            >
              <div className="text-tertiary flex items-baseline gap-2 text-xs">
                <span className="text-secondary font-medium">
                  {note.author}
                </span>
                <RelativeTime value={note.created_at} />
              </div>
              <p className="text-primary mt-1 text-sm whitespace-pre-wrap">
                {note.body}
              </p>
            </div>
          ))}
        </div>
        {canWrite && (
          <div className="px-6 pb-2">
            <Textarea
              aria-label="New note"
              className="min-h-20 text-sm"
              maxLength={2000}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Migrate to 5.x — 4.x stops receiving security fixes in Q3"
              value={draft}
            />
          </div>
        )}
        <DialogFooter>
          <Button
            onClick={() => onOpenChange(false)}
            type="button"
            variant="ghost"
          >
            Close
          </Button>
          {canWrite && (
            <Button
              disabled={!trimmed || isPending}
              onClick={() => {
                // Clear only once the note lands. A rejected write
                // already raises a toast; keeping the draft is what
                // makes that toast actionable.
                void onAddNote(trimmed).then(
                  () => setDraft(''),
                  () => undefined,
                )
              }}
              type="button"
            >
              Add note
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
