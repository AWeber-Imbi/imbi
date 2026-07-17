import { FileText, Pin } from 'lucide-react'

import type { Document } from '@/types'

import { DocumentRowTail, DocumentTagsCell } from './DocumentRowCells'
import { DocumentsFilterRail } from './DocumentsFilterRail'
import {
  attachmentDisplay,
  deriveExcerpt,
  documentTitle,
} from './documentsHelpers'
import { useTagFilter } from './useTagFilter'

const GRID_COLUMNS =
  'minmax(0, 0.9fr) minmax(0, 1.4fr) minmax(0, 0.8fr) 110px 64px 56px'

interface Props {
  displayNames?: Map<string, string>
  documents: Document[]
  onOpen: (documentId: string) => void
  onTogglePin: (document: Document) => void
}

/**
 * The "Index" view of the org-wide Documents page — a flat table with
 * the attachment (project, project type, or user) as the first column
 * and a tag-filter rail alongside.
 */
export function DocumentsIndexTable({
  displayNames,
  documents,
  onOpen,
  onTogglePin,
}: Props) {
  const filter = useTagFilter(documents, indexHaystack)
  const { filtered } = filter

  return (
    <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[220px_1fr]">
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
        <div className="overflow-x-auto">
          <div className="border-tertiary bg-primary min-w-180 overflow-hidden rounded-lg border">
            <div
              className="border-tertiary bg-secondary text-overline text-tertiary grid items-center gap-3.5 border-b px-3.5 py-2 uppercase"
              style={{ gridTemplateColumns: GRID_COLUMNS }}
            >
              <span>Attached to</span>
              <span>Document</span>
              <span>Tags</span>
              <span>Author</span>
              <span className="text-right">Updated</span>
              <span />
            </div>
            {filtered.map((n) => (
              <IndexRow
                displayNames={displayNames}
                document={n}
                key={n.id}
                onOpen={onOpen}
                onTogglePin={onTogglePin}
              />
            ))}
            {filtered.length === 0 && (
              <div className="text-tertiary px-8 py-10 text-center text-sm">
                No documents match.
              </div>
            )}
          </div>
        </div>
        <div className="text-tertiary mt-3 text-xs">
          {filtered.length} {filtered.length === 1 ? 'document' : 'documents'}
        </div>
      </div>
    </div>
  )
}

function indexHaystack(document: Document): string {
  const attached = attachmentDisplay(document)
  return [
    documentTitle(document),
    document.content,
    attached.name,
    attached.sub,
    document.attached_to?.team ?? '',
    document.created_by,
    document.created_by_name ?? '',
  ].join(' ')
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
  const attached = attachmentDisplay(document)
  return (
    <div
      className="border-tertiary hover:bg-secondary grid cursor-pointer items-center gap-3.5 border-b px-3.5 py-3 last:border-b-0"
      onClick={() => onOpen(document.id)}
      style={{ gridTemplateColumns: GRID_COLUMNS }}
    >
      <div className="min-w-0">
        <div className="text-primary truncate text-sm font-semibold">
          {attached.name}
        </div>
        {attached.sub && (
          <div className="text-tertiary mt-0.5 truncate text-xs">
            {attached.sub}
          </div>
        )}
      </div>
      <div className="flex min-w-0 items-start gap-2.5">
        <span className="bg-info text-info mt-0.5 inline-flex size-5.5 shrink-0 items-center justify-center rounded-md">
          <FileText className="size-3" />
        </span>
        <div className="min-w-0">
          <div className="text-primary flex items-center gap-1.5 text-[13.5px] font-medium">
            <span className="truncate">{title}</span>
            {pinned && (
              <Pin className="text-warning size-3 shrink-0 rotate-45" />
            )}
          </div>
          <div className="text-tertiary mt-0.5 truncate text-xs">{excerpt}</div>
        </div>
      </div>
      <DocumentTagsCell document={document} />
      <DocumentRowTail
        displayNames={displayNames}
        document={document}
        onOpen={onOpen}
        onTogglePin={onTogglePin}
      />
    </div>
  )
}
