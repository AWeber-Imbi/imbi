import { useCallback, useMemo, useState } from 'react'

import { ArrowUpRight, Pin, Plus } from 'lucide-react'

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
import type { Document } from '@/types'

import { DocumentsFilterRail } from './DocumentsFilterRail'
import {
  deriveExcerpt,
  documentTitle,
  formatUpdated,
  tagCounts,
  uniqueTagsFromDocuments,
} from './documentsHelpers'
import { DocumentTagChip } from './DocumentTagChip'

interface Props {
  displayNames?: Map<string, string>
  documents: Document[]
  onCreate: () => void
  onOpen: (documentId: string) => void
  onTogglePin: (document: Document) => void
}

export function DocumentsPinboard({
  displayNames,
  documents,
  onCreate,
  onOpen,
  onTogglePin,
}: Props) {
  const [active, setActive] = useState<Set<string>>(new Set())
  const [search, setSearch] = useState('')

  const tags = useMemo(() => uniqueTagsFromDocuments(documents), [documents])
  const counts = useMemo(() => tagCounts(documents), [documents])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return documents.filter((n) => {
      for (const slug of active) {
        if (!n.tags.some((t) => t.slug === slug)) return false
      }
      if (!q) return true
      const title = documentTitle(n).toLowerCase()
      const content = n.content.toLowerCase()
      return title.includes(q) || content.includes(q)
    })
  }, [documents, active, search])

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
      <DocumentsFilterRail
        active={active}
        counts={counts}
        onClear={() => setActive(new Set())}
        onSearchChange={setSearch}
        onToggle={toggle}
        search={search}
        tags={tags}
        totalFiltered={filtered.length}
      />

      <div>
        <section className="mb-6 flex items-start gap-3.5">
          {pinned.length > 0 && (
            <div className="grid min-w-0 flex-1 grid-cols-2 gap-3.5">
              {pinned.map((n) => (
                <HeroCard
                  displayNames={displayNames}
                  document={n}
                  key={n.id}
                  onOpen={onOpen}
                />
              ))}
            </div>
          )}
          <Button
            className={cn('gap-1.5', pinned.length === 0 && 'ml-auto')}
            onClick={onCreate}
            size="sm"
          >
            <Plus className="size-3" />
            New document
          </Button>
        </section>

        <section>
          <div className="border-tertiary bg-primary overflow-hidden rounded-lg border">
            <div
              className="border-tertiary bg-secondary text-overline text-tertiary grid items-center gap-3.5 border-b px-3.5 py-2 uppercase"
              style={{
                gridTemplateColumns:
                  'minmax(0, 1.6fr) minmax(0, 1fr) 100px 60px 60px',
              }}
            >
              <span>Document</span>
              <span>Tags</span>
              <span>Author</span>
              <span className="text-right">Updated</span>
              <span />
            </div>
            {rest.map((n) => (
              <IndexRow
                displayNames={displayNames}
                document={n}
                key={n.id}
                onOpen={onOpen}
                onTogglePin={onTogglePin}
              />
            ))}
            {rest.length === 0 && (
              <div className="text-tertiary px-8 py-7 text-center text-sm">
                {filtered.length === 0
                  ? 'No documents match the current filters.'
                  : 'All remaining documents are pinned.'}
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}

function HeroCard({
  displayNames,
  document,
  onOpen,
}: {
  displayNames?: Map<string, string>
  document: Document
  onOpen: (documentId: string) => void
}) {
  const title = documentTitle(document)
  const excerpt = deriveExcerpt(document.content)
  return (
    <Card
      className="hover:border-secondary flex cursor-pointer flex-col transition-colors hover:shadow-md"
      onClick={() => onOpen(document.id)}
    >
      <CardHeader className="space-y-2">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-primary text-[17px] leading-[1.3] font-medium tracking-[-0.01em]">
            {title}
          </CardTitle>
          <span className="text-warning inline-flex shrink-0 items-center gap-1 text-[11px]">
            <Pin className="size-2.5" />
            Pinned
          </span>
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-2.5">
        <p className="text-secondary m-0 line-clamp-3 text-[13px] leading-[1.55]">
          {excerpt}
        </p>
        {document.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {document.tags.map((t) => (
              <DocumentTagChip key={t.slug} size="sm" tag={t} />
            ))}
          </div>
        )}
      </CardContent>
      <CardFooter className="border-tertiary text-tertiary mt-auto gap-2 border-t pt-3 text-[11.5px]">
        <UserDisplay
          className="text-secondary"
          displayNames={displayNames}
          email={document.created_by}
          size={16}
          textClassName="font-medium"
        />
        <span className="text-tertiary">·</span>
        <span>Updated {formatUpdated(document)}</span>
      </CardFooter>
    </Card>
  )
}

function IndexRow({
  displayNames,
  document,
  onOpen,
  onTogglePin,
}: {
  displayNames?: Map<string, string>
  document: Document
  onOpen: (documentId: string) => void
  onTogglePin: (document: Document) => void
}) {
  const pinned = document.is_pinned
  const title = documentTitle(document)
  const excerpt = deriveExcerpt(document.content)
  const author = document.created_by
  return (
    <div
      className="border-tertiary hover:bg-secondary grid cursor-pointer items-center gap-3.5 border-b px-3.5 py-2.5 last:border-b-0"
      onClick={() => onOpen(document.id)}
      style={{
        gridTemplateColumns: 'minmax(0, 1.6fr) minmax(0, 1fr) 100px 60px 60px',
      }}
    >
      <div className="min-w-0">
        <div className="text-primary truncate text-[13.5px] font-medium">
          {title}
        </div>
        <div className="text-tertiary mt-0.5 truncate text-xs">{excerpt}</div>
      </div>
      <div className="flex flex-wrap gap-1">
        {document.tags.slice(0, 3).map((t) => (
          <DocumentTagChip key={t.slug} tag={t} />
        ))}
      </div>
      <UserDisplay
        className="text-secondary text-xs"
        displayNames={displayNames}
        email={author}
        size={18}
      />
      <div className="text-tertiary text-right font-mono text-[11.5px]">
        {formatUpdated(document)}
      </div>
      <div className="flex justify-end gap-0.5">
        <RowIconButton
          onClick={(e) => {
            e.stopPropagation()
            onTogglePin(document)
          }}
          title={pinned ? 'Unpin document' : 'Pin document'}
        >
          <Pin
            className={cn('size-3', pinned ? 'text-warning' : 'text-tertiary')}
          />
        </RowIconButton>
        <RowIconButton
          onClick={(e) => {
            e.stopPropagation()
            onOpen(document.id)
          }}
          title="Open document"
        >
          <ArrowUpRight className="text-tertiary size-3" />
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
      className="text-tertiary hover:bg-tertiary inline-flex size-[22px] cursor-pointer items-center justify-center rounded border-0 bg-transparent"
      onClick={onClick}
      title={title}
      type="button"
    >
      {children}
    </button>
  )
}
