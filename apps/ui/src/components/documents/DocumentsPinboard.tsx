import { useMemo } from 'react'

import { Pin } from 'lucide-react'

import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { UserDisplay } from '@/components/ui/user-display'
import { cn } from '@/lib/utils'
import type { Document, DocumentTemplate } from '@/types'

import { DocumentRowTail, DocumentTagsCell } from './DocumentRowCells'
import { DocumentsFilterRail } from './DocumentsFilterRail'
import { deriveExcerpt, documentTitle, formatUpdated } from './documentsHelpers'
import { DocumentTagChip } from './DocumentTagChip'
import { NewDocumentMenu } from './NewDocumentMenu'
import { useTagFilter } from './useTagFilter'

interface Props {
  context?: 'project' | 'project_type' | 'user'
  displayNames?: Map<string, string>
  documents: Document[]
  onCreate: (template?: DocumentTemplate) => void
  onOpen: (documentId: string) => void
  onTogglePin: (document: Document) => void
  orgSlug: string
  projectTypeSlugs?: string[]
  /**
   * Hide the Author column where it is redundant — e.g. the user profile
   * Documents tab, where every document belongs to the profiled user.
   */
  showAuthor?: boolean
}

export function DocumentsPinboard({
  context = 'project',
  displayNames,
  documents,
  onCreate,
  onOpen,
  onTogglePin,
  orgSlug,
  projectTypeSlugs,
  showAuthor = true,
}: Props) {
  const filter = useTagFilter(documents, pinboardHaystack)
  const { filtered } = filter

  const pinned = useMemo(() => filtered.filter((n) => n.is_pinned), [filtered])
  const rest = useMemo(() => filtered.filter((n) => !n.is_pinned), [filtered])

  return (
    <div className="grid grid-cols-[220px_1fr] gap-5">
      <DocumentsFilterRail
        active={filter.active}
        counts={filter.counts}
        onClear={filter.clear}
        onSearchChange={filter.setSearch}
        onToggle={filter.toggle}
        search={filter.search}
        tags={filter.tags}
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
          <NewDocumentMenu
            className={cn(pinned.length === 0 && 'ml-auto')}
            context={context}
            onCreate={onCreate}
            orgSlug={orgSlug}
            projectTypeSlugs={projectTypeSlugs}
          />
        </section>

        <section>
          <div className="border-tertiary bg-primary overflow-hidden rounded-lg border">
            <div
              className="border-tertiary bg-secondary text-overline text-tertiary grid items-center gap-3.5 border-b px-3.5 py-2 uppercase"
              style={{ gridTemplateColumns: gridColumns(showAuthor) }}
            >
              <span>Document</span>
              <span>Tags</span>
              {showAuthor && <span>Author</span>}
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
                showAuthor={showAuthor}
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

function gridColumns(showAuthor: boolean): string {
  return showAuthor
    ? 'minmax(0, 1.6fr) minmax(0, 1fr) 100px 60px 60px'
    : 'minmax(0, 1.6fr) minmax(0, 1fr) 60px 60px'
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
  showAuthor,
}: {
  displayNames?: Map<string, string>
  document: Document
  onOpen: (documentId: string) => void
  onTogglePin: (document: Document) => void
  showAuthor: boolean
}) {
  const title = documentTitle(document)
  const excerpt = deriveExcerpt(document.content)
  return (
    <div
      className="border-tertiary hover:bg-secondary grid cursor-pointer items-center gap-3.5 border-b px-3.5 py-2.5 last:border-b-0"
      onClick={() => onOpen(document.id)}
      style={{ gridTemplateColumns: gridColumns(showAuthor) }}
    >
      <div className="min-w-0">
        <div className="text-primary truncate text-[13.5px] font-medium">
          {title}
        </div>
        <div className="text-tertiary mt-0.5 truncate text-xs">{excerpt}</div>
      </div>
      <DocumentTagsCell document={document} />
      <DocumentRowTail
        displayNames={displayNames}
        document={document}
        onOpen={onOpen}
        onTogglePin={onTogglePin}
        showAuthor={showAuthor}
      />
    </div>
  )
}

function pinboardHaystack(document: Document): string {
  return `${documentTitle(document)} ${document.content}`
}
