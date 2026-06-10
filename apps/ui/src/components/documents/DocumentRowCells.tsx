import { ArrowUpRight, Pin } from 'lucide-react'

import { IconTooltip } from '@/components/ui/tooltip'
import { UserDisplay } from '@/components/ui/user-display'
import { cn } from '@/lib/utils'
import type { Document } from '@/types'

import { formatUpdated } from './documentsHelpers'
import { DocumentTagChip } from './DocumentTagChip'

/**
 * The trailing cells shared by every document index row: optional
 * author, relative updated time, and the pin/open action buttons.
 * Rendered as a fragment so the cells participate in the caller's
 * grid directly.
 */
// fallow-ignore-next-line complexity
export function DocumentRowTail({
  displayNames,
  document,
  onOpen,
  onTogglePin,
  showAuthor = true,
}: {
  displayNames?: Map<string, string>
  document: Document
  onOpen: (documentId: string) => void
  onTogglePin: (document: Document) => void
  showAuthor?: boolean
}) {
  const pinned = document.is_pinned
  return (
    <>
      {showAuthor && (
        <UserDisplay
          className="text-secondary text-xs"
          displayName={document.created_by_name ?? undefined}
          displayNames={displayNames}
          email={document.created_by}
          size={18}
        />
      )}
      <div className="text-tertiary text-right font-mono text-[11.5px] whitespace-nowrap">
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
    </>
  )
}

/** The first three tag chips of an index row. */
export function DocumentTagsCell({ document }: { document: Document }) {
  return (
    <div className="flex flex-wrap gap-1">
      {document.tags.slice(0, 3).map((t) => (
        <DocumentTagChip key={t.slug} tag={t} />
      ))}
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
    <IconTooltip label={title}>
      <button
        aria-label={title}
        className="text-tertiary hover:bg-tertiary inline-flex size-[22px] cursor-pointer items-center justify-center rounded border-0 bg-transparent"
        onClick={onClick}
        type="button"
      >
        {children}
      </button>
    </IconTooltip>
  )
}
