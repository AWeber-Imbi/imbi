import { useEffect, useMemo, useState } from 'react'

import { ArrowLeft, Clock, Pencil, Pin, PinOff, Trash2 } from 'lucide-react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { UserDisplay } from '@/components/ui/user-display'
import { cn } from '@/lib/utils'
import type { Document } from '@/types'

import { DocumentsFilterRail } from './DocumentsFilterRail'
import {
  documentTitle,
  EMPTY_ACTIVE,
  formatFull,
  formatUpdated,
  tagCounts,
  uniqueTagsFromDocuments,
} from './documentsHelpers'
import { DocumentTagChip } from './DocumentTagChip'

interface Heading {
  level: 2 | 3
  slug: string
  text: string
}

interface Props {
  allDocuments: Document[]
  deleting?: boolean
  displayNames?: Map<string, string>
  document: Document
  onBack: () => void
  onDelete?: () => void
  onEdit?: () => void
  onOpen: (documentId: string) => void
  onTogglePin: () => void
}

export function DocumentsPinboardReader({
  allDocuments,
  deleting = false,
  displayNames,
  document,
  onBack,
  onDelete,
  onEdit,
  onOpen,
  onTogglePin,
}: Props) {
  const [search, setSearch] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const pinned = document.is_pinned
  const title = documentTitle(document)

  const tags = useMemo(
    () => uniqueTagsFromDocuments(allDocuments),
    [allDocuments],
  )
  const counts = useMemo(() => tagCounts(allDocuments), [allDocuments])
  const highlightedSlugs = useMemo(
    () => new Set(document.tags.map((t) => t.slug)),
    [document.tags],
  )

  const related = useMemo(() => {
    const documentTags = new Set(document.tags.map((t) => t.slug))
    return allDocuments
      .filter(
        (n) =>
          n.id !== document.id && n.tags.some((t) => documentTags.has(t.slug)),
      )
      .slice(0, 4)
  }, [allDocuments, document])

  const headings = useMemo(
    () => extractHeadings(document.content),
    [document.content],
  )
  const headingSlugs = useMemo(() => headings.map((h) => h.slug), [headings])
  const activeSlug = useActiveHeading(headingSlugs)

  // Reader is navigable from the same tab; filter rail keeps rail semantics.
  return (
    <div className="grid grid-cols-[220px_1fr] gap-5">
      <DocumentsFilterRail
        active={EMPTY_ACTIVE}
        counts={counts}
        highlightedSlugs={highlightedSlugs}
        onClear={() => onBack()}
        onSearchChange={setSearch}
        onToggle={() => onBack()}
        search={search}
        tags={tags}
        totalFiltered={allDocuments.length}
      />

      <div>
        <div className="mb-3.5 grid grid-cols-[minmax(0,1fr)_260px] items-start gap-5">
          <div className="flex flex-wrap items-center gap-2.5">
            <button
              className="text-secondary hover:bg-secondary hover:text-primary inline-flex cursor-pointer items-center gap-1.5 rounded border-0 bg-transparent px-1.5 py-1 text-xs"
              onClick={onBack}
              type="button"
            >
              <ArrowLeft className="size-3" />
              All documents
            </button>
            <div className="ml-auto flex items-center gap-1">
              <Button
                className="gap-1.5"
                onClick={onTogglePin}
                size="sm"
                variant="ghost"
              >
                {pinned ? (
                  <>
                    <PinOff className="size-3" />
                    Unpin
                  </>
                ) : (
                  <>
                    <Pin className="size-3" />
                    Pin
                  </>
                )}
              </Button>
              <Button
                className="gap-1.5"
                disabled={!onEdit}
                onClick={onEdit}
                size="sm"
                variant="ghost"
              >
                <Pencil className="size-3" />
                Edit
              </Button>
              <Button
                disabled={!onDelete || deleting}
                onClick={() => setConfirmDelete(true)}
                size="sm"
                title="Delete document"
                variant="ghost"
              >
                <Trash2 className="size-3" />
              </Button>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-[minmax(0,1fr)_260px] items-start gap-5">
          <article className="border-tertiary bg-primary rounded-lg border px-8 py-7">
            <h1 className="text-primary m-0 text-[26px] leading-[1.2] font-medium tracking-[-0.015em]">
              {title}
            </h1>

            <div className="mt-3.5 flex flex-wrap items-center gap-2.5">
              <div className="text-tertiary inline-flex items-center gap-2 text-[12.5px]">
                <UserDisplay
                  className="text-secondary"
                  displayNames={displayNames}
                  email={document.created_by}
                  size={22}
                  textClassName="text-[12.5px] text-secondary"
                />
                <span className="text-tertiary">·</span>
                <span>Updated {formatUpdated(document)}</span>
              </div>
              <div className="bg-tertiary h-3.5 w-px" />
              <div className="flex flex-wrap gap-1">
                {document.tags.map((t) => (
                  <DocumentTagChip key={t.slug} tag={t} />
                ))}
              </div>
            </div>

            <div className="document-markdown mt-6">
              <Markdown
                components={{
                  h2: ({ children, ...props }) => (
                    <h2
                      className="scroll-mt-20"
                      id={slugify(headingTextFromChildren(children))}
                      {...props}
                    >
                      {children}
                    </h2>
                  ),
                  h3: ({ children, ...props }) => (
                    <h3
                      className="scroll-mt-20"
                      id={slugify(headingTextFromChildren(children))}
                      {...props}
                    >
                      {children}
                    </h3>
                  ),
                }}
                remarkPlugins={[remarkGfm]}
              >
                {document.content}
              </Markdown>
            </div>

            <div className="border-tertiary text-tertiary mt-7 flex flex-wrap items-center gap-2.5 border-t pt-4 text-[11.5px]">
              <Clock className="size-3" />
              <span>Created {formatFull(document.created_at)}</span>
              {document.updated_at && (
                <>
                  <span className="text-tertiary">·</span>
                  <span>Last updated {formatFull(document.updated_at)}</span>
                </>
              )}
            </div>
          </article>

          <div className="sticky top-5 flex flex-col gap-4">
            {headings.length > 0 && (
              <div>
                <div className="text-overline text-tertiary mb-2 uppercase">
                  On this page
                </div>
                <div className="border-tertiary flex flex-col gap-0.5 border-l">
                  {headings.map((h, i) => {
                    const isActive = h.slug === activeSlug
                    return (
                      <a
                        className={cn(
                          '-ml-px border-l-2 text-[12.5px] no-underline transition-colors',
                          h.level === 3
                            ? 'py-0.5 pr-2 pl-5'
                            : 'py-0.5 pr-2 pl-3',
                          isActive
                            ? 'border-action font-medium text-primary'
                            : cn(
                                'border-transparent',
                                h.level === 3
                                  ? 'text-secondary'
                                  : 'text-primary',
                              ),
                        )}
                        href={`#${h.slug}`}
                        key={`${h.slug}-${i}`}
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
                <div className="text-overline text-tertiary mb-2 uppercase">
                  Related documents
                </div>
                <div className="flex flex-col gap-2">
                  {related.map((r) => (
                    <button
                      className="border-tertiary bg-primary hover:border-secondary block cursor-pointer rounded-lg border p-2 text-left"
                      key={r.id}
                      onClick={() => onOpen(r.id)}
                      type="button"
                    >
                      <div className="text-primary line-clamp-2 text-[12.5px] leading-[1.35] font-medium">
                        {documentTitle(r)}
                      </div>
                      <div className="text-tertiary mt-1 flex items-center gap-1.5 text-[11px]">
                        <UserDisplay
                          displayNames={displayNames}
                          email={r.created_by}
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
        confirmLabel={deleting ? 'Deleting…' : 'Delete'}
        description={`"${title}" will be permanently removed.`}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => {
          setConfirmDelete(false)
          onDelete?.()
        }}
        open={confirmDelete}
        title="Delete document?"
      />
    </div>
  )
}

function extractHeadings(content: string): Heading[] {
  const out: Heading[] = []
  for (const raw of content.split('\n')) {
    const m = raw.match(/^(#{2,3})\s+(.+?)\s*#*$/)
    if (!m) continue
    const level = (m[1].length === 2 ? 2 : 3) as 2 | 3
    const text = m[2].trim()
    out.push({ level, slug: slugify(text), text })
  }
  return out
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

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .trim()
    .replace(/\s+/g, '-')
}

/**
 * Track which heading is currently nearest the top of the viewport. Picks the
 * last heading whose top has scrolled above the offset; falls back to the
 * first when nothing has scrolled past yet.
 */
function useActiveHeading(slugs: string[]): null | string {
  const [active, setActive] = useState<null | string>(slugs[0] ?? null)
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
