import { ArrowLeft, Clock, Pencil, Pin, PinOff, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { UserDisplay } from '@/components/ui/user-display'
import { cn } from '@/lib/utils'
import { NotesFilterRail } from './NotesFilterRail'
import { NoteTagChip } from './NoteTagChip'
import {
  EMPTY_ACTIVE,
  noteTitle,
  formatFull,
  formatUpdated,
  tagCounts,
  uniqueTagsFromNotes,
} from './notesHelpers'
import type { Note } from '@/types'

interface Props {
  note: Note
  allNotes: Note[]
  displayNames?: Map<string, string>
  onBack: () => void
  onOpen: (noteId: string) => void
  onTogglePin: () => void
  onEdit?: () => void
  onDelete?: () => void
  deleting?: boolean
}

interface Heading {
  level: 2 | 3
  text: string
  slug: string
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .trim()
    .replace(/\s+/g, '-')
}

function headingTextFromChildren(children: React.ReactNode): string {
  let out = ''
  const visit = (node: React.ReactNode) => {
    if (typeof node === 'string' || typeof node === 'number') {
      out += String(node)
    } else if (Array.isArray(node)) {
      node.forEach(visit)
    } else if (
      typeof node === 'object' &&
      node !== null &&
      'props' in node &&
      (node as { props?: { children?: React.ReactNode } }).props
    ) {
      visit((node as { props: { children?: React.ReactNode } }).props.children)
    }
  }
  visit(children)
  return out
}

function extractHeadings(content: string): Heading[] {
  const out: Heading[] = []
  for (const raw of content.split('\n')) {
    const m = raw.match(/^(#{2,3})\s+(.+?)\s*#*$/)
    if (!m) continue
    const level = (m[1].length === 2 ? 2 : 3) as 2 | 3
    const text = m[2].trim()
    out.push({ level, text, slug: slugify(text) })
  }
  return out
}

/**
 * Track which heading is currently nearest the top of the viewport. Picks the
 * last heading whose top has scrolled above the offset; falls back to the
 * first when nothing has scrolled past yet.
 */
function useActiveHeading(slugs: string[]): string | null {
  const [active, setActive] = useState<string | null>(slugs[0] ?? null)
  useEffect(() => {
    if (!slugs.length) {
      setActive(null)
      return
    }
    const offset = 120
    const update = () => {
      let current = slugs[0]
      for (const slug of slugs) {
        const el = document.getElementById(slug)
        if (!el) continue
        if (el.getBoundingClientRect().top - offset <= 0) current = slug
        else break
      }
      setActive((prev) => (prev === current ? prev : current))
    }
    update()
    window.addEventListener('scroll', update, { passive: true })
    window.addEventListener('resize', update)
    return () => {
      window.removeEventListener('scroll', update)
      window.removeEventListener('resize', update)
    }
  }, [slugs])
  return active
}

export function NotesPinboardReader({
  note,
  allNotes,
  onBack,
  onOpen,
  onTogglePin,
  onEdit,
  onDelete,
  deleting = false,
  displayNames,
}: Props) {
  const [search, setSearch] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const pinned = note.is_pinned
  const title = noteTitle(note)

  const tags = useMemo(() => uniqueTagsFromNotes(allNotes), [allNotes])
  const counts = useMemo(() => tagCounts(allNotes), [allNotes])
  const highlightedSlugs = useMemo(
    () => new Set(note.tags.map((t) => t.slug)),
    [note.tags],
  )

  const related = useMemo(() => {
    const noteTags = new Set(note.tags.map((t) => t.slug))
    return allNotes
      .filter(
        (n) => n.id !== note.id && n.tags.some((t) => noteTags.has(t.slug)),
      )
      .slice(0, 4)
  }, [allNotes, note])

  const headings = useMemo(() => extractHeadings(note.content), [note.content])
  const headingSlugs = useMemo(() => headings.map((h) => h.slug), [headings])
  const activeSlug = useActiveHeading(headingSlugs)

  // Reader is navigable from the same tab; filter rail keeps rail semantics.
  return (
    <div className="grid grid-cols-[220px_1fr] gap-5">
      <NotesFilterRail
        tags={tags}
        counts={counts}
        active={EMPTY_ACTIVE}
        onToggle={() => onBack()}
        onClear={() => onBack()}
        search={search}
        onSearchChange={setSearch}
        totalFiltered={allNotes.length}
        highlightedSlugs={highlightedSlugs}
      />

      <div>
        <div className="mb-3.5 grid items-start gap-5 [grid-template-columns:minmax(0,1fr)_260px]">
          <div className="flex flex-wrap items-center gap-2.5">
            <button
              type="button"
              onClick={onBack}
              className="inline-flex cursor-pointer items-center gap-1.5 rounded border-0 bg-transparent px-1.5 py-1 text-xs text-secondary hover:bg-secondary hover:text-primary"
            >
              <ArrowLeft className="h-3 w-3" />
              All notes
            </button>
            <div className="ml-auto flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                className="gap-1.5"
                onClick={onTogglePin}
              >
                {pinned ? (
                  <>
                    <PinOff className="h-3 w-3" />
                    Unpin
                  </>
                ) : (
                  <>
                    <Pin className="h-3 w-3" />
                    Pin
                  </>
                )}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="gap-1.5"
                onClick={onEdit}
                disabled={!onEdit}
              >
                <Pencil className="h-3 w-3" />
                Edit
              </Button>
              <Button
                variant="ghost"
                size="sm"
                title="Delete note"
                onClick={() => setConfirmDelete(true)}
                disabled={!onDelete || deleting}
              >
                <Trash2 className="h-3 w-3" />
              </Button>
            </div>
          </div>
        </div>

        <div className="grid items-start gap-5 [grid-template-columns:minmax(0,1fr)_260px]">
          <article className="rounded-lg border border-tertiary bg-primary px-8 py-7">
            <h1 className="m-0 text-[26px] font-medium leading-[1.2] tracking-[-0.015em] text-primary">
              {title}
            </h1>

            <div className="mt-3.5 flex flex-wrap items-center gap-2.5">
              <div className="inline-flex items-center gap-2 text-[12.5px] text-tertiary">
                <UserDisplay
                  email={note.created_by}
                  displayNames={displayNames}
                  size={22}
                  className="text-secondary"
                  textClassName="text-[12.5px] text-secondary"
                />
                <span className="text-tertiary">·</span>
                <span>Updated {formatUpdated(note)}</span>
              </div>
              <div className="h-3.5 w-px bg-tertiary" />
              <div className="flex flex-wrap gap-1">
                {note.tags.map((t) => (
                  <NoteTagChip key={t.slug} tag={t} />
                ))}
              </div>
            </div>

            <div className="note-markdown mt-6">
              <Markdown
                remarkPlugins={[remarkGfm]}
                components={{
                  h2: ({ children, ...props }) => (
                    <h2
                      id={slugify(headingTextFromChildren(children))}
                      className="scroll-mt-20"
                      {...props}
                    >
                      {children}
                    </h2>
                  ),
                  h3: ({ children, ...props }) => (
                    <h3
                      id={slugify(headingTextFromChildren(children))}
                      className="scroll-mt-20"
                      {...props}
                    >
                      {children}
                    </h3>
                  ),
                }}
              >
                {note.content}
              </Markdown>
            </div>

            <div className="mt-7 flex flex-wrap items-center gap-2.5 border-t border-tertiary pt-4 text-[11.5px] text-tertiary">
              <Clock className="h-3 w-3" />
              <span>Created {formatFull(note.created_at)}</span>
              {note.updated_at && (
                <>
                  <span className="text-tertiary">·</span>
                  <span>Last updated {formatFull(note.updated_at)}</span>
                </>
              )}
            </div>
          </article>

          <div className="sticky top-5 flex flex-col gap-4">
            {headings.length > 0 && (
              <div>
                <div className="mb-2 text-overline uppercase text-tertiary">
                  On this page
                </div>
                <div className="flex flex-col gap-0.5 border-l border-tertiary">
                  {headings.map((h, i) => {
                    const isActive = h.slug === activeSlug
                    return (
                      <a
                        key={`${h.slug}-${i}`}
                        href={`#${h.slug}`}
                        className={cn(
                          '-ml-px border-l-2 text-[12.5px] no-underline transition-colors',
                          h.level === 3
                            ? 'py-0.5 pl-5 pr-2'
                            : 'py-0.5 pl-3 pr-2',
                          isActive
                            ? 'border-action font-medium text-primary'
                            : cn(
                                'border-transparent',
                                h.level === 3
                                  ? 'text-secondary'
                                  : 'text-primary',
                              ),
                        )}
                      >
                        {h.text}
                      </a>
                    )
                  })}
                </div>
              </div>
            )}

            {related.length > 0 && (
              <div>
                <div className="mb-2 text-overline uppercase text-tertiary">
                  Related notes
                </div>
                <div className="flex flex-col gap-2">
                  {related.map((r) => (
                    <button
                      key={r.id}
                      type="button"
                      onClick={() => onOpen(r.id)}
                      className="block cursor-pointer rounded-lg border border-tertiary bg-primary p-2 text-left hover:border-secondary"
                    >
                      <div className="line-clamp-2 text-[12.5px] font-medium leading-[1.35] text-primary">
                        {noteTitle(r)}
                      </div>
                      <div className="mt-1 flex items-center gap-1.5 text-[11px] text-tertiary">
                        <UserDisplay
                          email={r.created_by}
                          displayNames={displayNames}
                          size={14}
                        />
                        <span>· {formatUpdated(r)}</span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
      <ConfirmDialog
        open={confirmDelete}
        title="Delete note?"
        description={`"${title}" will be permanently removed.`}
        confirmLabel={deleting ? 'Deleting…' : 'Delete'}
        onConfirm={() => {
          setConfirmDelete(false)
          onDelete?.()
        }}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  )
}
