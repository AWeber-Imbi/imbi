import { ArrowUpRight, Pin, Plus } from 'lucide-react'
import { useCallback, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { UserDisplay } from '@/components/ui/user-display'
import { cn } from '@/lib/utils'
import { NotesFilterRail } from './NotesFilterRail'
import { NoteTagChip } from './NoteTagChip'
import {
  deriveExcerpt,
  noteTitle,
  formatUpdated,
  tagCounts,
  uniqueTagsFromNotes,
} from './notesHelpers'
import type { Note } from '@/types'

interface Props {
  notes: Note[]
  displayNames?: Map<string, string>
  onOpen: (noteId: string) => void
  onCreate: () => void
  onTogglePin: (note: Note) => void
}

export function NotesPinboard({
  notes,
  displayNames,
  onOpen,
  onCreate,
  onTogglePin,
}: Props) {
  const [active, setActive] = useState<Set<string>>(new Set())
  const [search, setSearch] = useState('')

  const tags = useMemo(() => uniqueTagsFromNotes(notes), [notes])
  const counts = useMemo(() => tagCounts(notes), [notes])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return notes.filter((n) => {
      for (const slug of active) {
        if (!n.tags.some((t) => t.slug === slug)) return false
      }
      if (!q) return true
      const title = noteTitle(n).toLowerCase()
      const content = n.content.toLowerCase()
      return title.includes(q) || content.includes(q)
    })
  }, [notes, active, search])

  const pinned = useMemo(() => filtered.filter((n) => n.is_pinned), [filtered])
  const rest = useMemo(() => filtered.filter((n) => !n.is_pinned), [filtered])

  const toggle = useCallback((slug: string) => {
    setActive((prev) => {
      const next = new Set(prev)
      if (next.has(slug)) next.delete(slug)
      else next.add(slug)
      return next
    })
  }, [])

  return (
    <div className="grid grid-cols-[220px_1fr] gap-5">
      <NotesFilterRail
        tags={tags}
        counts={counts}
        active={active}
        onToggle={toggle}
        onClear={() => setActive(new Set())}
        search={search}
        onSearchChange={setSearch}
        totalFiltered={filtered.length}
      />

      <div>
        <section className="mb-6 flex items-start gap-3.5">
          {pinned.length > 0 && (
            <div className="grid min-w-0 flex-1 grid-cols-2 gap-3.5">
              {pinned.map((n) => (
                <HeroCard
                  key={n.id}
                  note={n}
                  displayNames={displayNames}
                  onOpen={onOpen}
                />
              ))}
            </div>
          )}
          <Button
            size="sm"
            onClick={onCreate}
            className={cn('gap-1.5', pinned.length === 0 && 'ml-auto')}
          >
            <Plus className="h-3 w-3" />
            New note
          </Button>
        </section>

        <section>
          <div className="overflow-hidden rounded-lg border border-tertiary bg-primary">
            <div
              className="grid items-center gap-3.5 border-b border-tertiary bg-secondary px-3.5 py-2 text-overline uppercase text-tertiary"
              style={{
                gridTemplateColumns:
                  'minmax(0, 1.6fr) minmax(0, 1fr) 100px 60px 60px',
              }}
            >
              <span>Note</span>
              <span>Tags</span>
              <span>Author</span>
              <span className="text-right">Updated</span>
              <span />
            </div>
            {rest.map((n) => (
              <IndexRow
                key={n.id}
                note={n}
                displayNames={displayNames}
                onOpen={onOpen}
                onTogglePin={onTogglePin}
              />
            ))}
            {rest.length === 0 && (
              <div className="px-8 py-7 text-center text-sm text-tertiary">
                {filtered.length === 0
                  ? 'No notes match the current filters.'
                  : 'All remaining notes are pinned.'}
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}

function HeroCard({
  note,
  displayNames,
  onOpen,
}: {
  note: Note
  displayNames?: Map<string, string>
  onOpen: (noteId: string) => void
}) {
  const title = noteTitle(note)
  const excerpt = deriveExcerpt(note.content)
  return (
    <Card
      onClick={() => onOpen(note.id)}
      className="flex cursor-pointer flex-col transition-colors hover:border-secondary hover:shadow-md"
    >
      <CardHeader className="space-y-2">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-[17px] font-medium leading-[1.3] tracking-[-0.01em] text-primary">
            {title}
          </CardTitle>
          <span className="inline-flex flex-shrink-0 items-center gap-1 text-[11px] text-warning">
            <Pin className="h-2.5 w-2.5" />
            Pinned
          </span>
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-2.5">
        <p className="m-0 line-clamp-3 text-[13px] leading-[1.55] text-secondary">
          {excerpt}
        </p>
        {note.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {note.tags.map((t) => (
              <NoteTagChip key={t.slug} tag={t} size="sm" />
            ))}
          </div>
        )}
      </CardContent>
      <CardFooter className="mt-auto gap-2 border-t border-tertiary pt-3 text-[11.5px] text-tertiary">
        <UserDisplay
          email={note.created_by}
          displayNames={displayNames}
          size={16}
          className="text-secondary"
          textClassName="font-medium"
        />
        <span className="text-tertiary">·</span>
        <span>Updated {formatUpdated(note)}</span>
      </CardFooter>
    </Card>
  )
}

function IndexRow({
  note,
  displayNames,
  onOpen,
  onTogglePin,
}: {
  note: Note
  displayNames?: Map<string, string>
  onOpen: (noteId: string) => void
  onTogglePin: (note: Note) => void
}) {
  const pinned = note.is_pinned
  const title = noteTitle(note)
  const excerpt = deriveExcerpt(note.content)
  const author = note.created_by
  return (
    <div
      onClick={() => onOpen(note.id)}
      className="grid cursor-pointer items-center gap-3.5 border-b border-tertiary px-3.5 py-2.5 last:border-b-0 hover:bg-secondary"
      style={{
        gridTemplateColumns: 'minmax(0, 1.6fr) minmax(0, 1fr) 100px 60px 60px',
      }}
    >
      <div className="min-w-0">
        <div className="truncate text-[13.5px] font-medium text-primary">
          {title}
        </div>
        <div className="mt-0.5 truncate text-xs text-tertiary">{excerpt}</div>
      </div>
      <div className="flex flex-wrap gap-1">
        {note.tags.slice(0, 3).map((t) => (
          <NoteTagChip key={t.slug} tag={t} />
        ))}
      </div>
      <UserDisplay
        email={author}
        displayNames={displayNames}
        size={18}
        className="text-xs text-secondary"
      />
      <div className="text-right font-mono text-[11.5px] text-tertiary">
        {formatUpdated(note)}
      </div>
      <div className="flex justify-end gap-0.5">
        <RowIconButton
          onClick={(e) => {
            e.stopPropagation()
            onTogglePin(note)
          }}
          title={pinned ? 'Unpin note' : 'Pin note'}
        >
          <Pin
            className={cn('h-3 w-3', pinned ? 'text-warning' : 'text-tertiary')}
          />
        </RowIconButton>
        <RowIconButton
          onClick={(e) => {
            e.stopPropagation()
            onOpen(note.id)
          }}
          title="Open note"
        >
          <ArrowUpRight className="h-3 w-3 text-tertiary" />
        </RowIconButton>
      </div>
    </div>
  )
}

function RowIconButton({
  children,
  onClick,
  title,
}: {
  children: React.ReactNode
  onClick: (e: React.MouseEvent) => void
  title: string
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className="inline-flex h-[22px] w-[22px] cursor-pointer items-center justify-center rounded border-0 bg-transparent text-tertiary hover:bg-tertiary"
    >
      {children}
    </button>
  )
}
