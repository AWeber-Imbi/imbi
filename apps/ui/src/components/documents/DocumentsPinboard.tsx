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
            <Plus className="h-3 w-3" />
            New document
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
              <div className="px-8 py-7 text-center text-sm text-tertiary">
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
      className="flex cursor-pointer flex-col transition-colors hover:border-secondary hover:shadow-md"
      onClick={() => onOpen(document.id)}
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
        {document.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {document.tags.map((t) => (
              <DocumentTagChip key={t.slug} size="sm" tag={t} />
            ))}
          </div>
        )}
      </CardContent>
      <CardFooter className="mt-auto gap-2 border-t border-tertiary pt-3 text-[11.5px] text-tertiary">
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
      className="grid cursor-pointer items-center gap-3.5 border-b border-tertiary px-3.5 py-2.5 last:border-b-0 hover:bg-secondary"
      onClick={() => onOpen(document.id)}
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
        {document.tags.slice(0, 3).map((t) => (
          <DocumentTagChip key={t.slug} tag={t} />
        ))}
      </div>
      <UserDisplay
        className="text-xs text-secondary"
        displayNames={displayNames}
        email={author}
        size={18}
      />
      <div className="text-right font-mono text-[11.5px] text-tertiary">
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
            className={cn('h-3 w-3', pinned ? 'text-warning' : 'text-tertiary')}
          />
        </RowIconButton>
        <RowIconButton
          onClick={(e) => {
            e.stopPropagation()
            onOpen(document.id)
          }}
          title="Open document"
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
      className="inline-flex h-[22px] w-[22px] cursor-pointer items-center justify-center rounded border-0 bg-transparent text-tertiary hover:bg-tertiary"
      onClick={onClick}
      title={title}
      type="button"
    >
      {children}
    </button>
  )
}
