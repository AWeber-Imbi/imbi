import { FileText, FolderKanban, MessageSquare, Pin } from 'lucide-react'

import { Card } from '@/components/ui/card'
import { UserIdentity } from '@/components/ui/user-identity'
import type { Document } from '@/types'

import {
  attachmentDisplay,
  deriveExcerpt,
  documentTitle,
} from './documentsHelpers'
import { DocumentTagChip } from './DocumentTagChip'

interface Props {
  displayNames?: Map<string, string>
  documents: Document[]
  onOpen: (documentId: string) => void
}

/**
 * The "Activity feed" view of the org-wide Documents page — one
 * Confluence-style card per document, newest first.
 */
export function DocumentsFeed({ displayNames, documents, onOpen }: Props) {
  if (documents.length === 0) {
    return (
      <Card className="text-tertiary px-10 py-10 text-center text-sm">
        No recent activity.
      </Card>
    )
  }
  return (
    <div className="flex flex-col gap-4">
      {documents.map((d) => (
        <FeedCard
          displayNames={displayNames}
          document={d}
          key={d.id}
          onOpen={onOpen}
        />
      ))}
    </div>
  )
}

// fallow-ignore-next-line complexity
function FeedCard({
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
  const attached = attachmentDisplay(document)
  const team = document.attached_to?.team
  return (
    <Card className="hover:border-secondary px-5 py-4 transition-colors hover:shadow-sm">
      {/* Byline */}
      <div className="flex items-center gap-2.5">
        <UserIdentity
          displayName={document.created_by_name ?? undefined}
          displayNames={displayNames}
          email={document.created_by}
          size="floating"
        />
        <span className="text-secondary text-[13.5px]">
          {document.updated_at ? 'updated' : 'created'}
        </span>
        <span className="text-tertiary">·</span>
        <span className="text-secondary text-[13.5px] tabular-nums">
          {feedDate(document)}
        </span>
      </div>

      <div className="bg-tertiary my-3 h-px" />

      {/* Title */}
      <button
        className="group flex cursor-pointer items-center gap-2 border-0 bg-transparent p-0 text-left"
        onClick={() => onOpen(document.id)}
        type="button"
      >
        <span className="bg-info text-info inline-flex size-6 shrink-0 items-center justify-center rounded-md">
          <FileText className="size-3.5" />
        </span>
        <span className="text-primary text-base font-semibold tracking-[-0.01em] group-hover:underline">
          {title}
        </span>
        {document.is_pinned && (
          <Pin className="text-warning size-3 shrink-0 rotate-45" />
        )}
      </button>

      {/* Ownership */}
      <div className="text-tertiary mt-2 mb-2 flex flex-wrap items-center gap-1.5 text-[13px]">
        Owned by
        <UserIdentity
          displayName={document.created_by_name ?? undefined}
          displayNames={displayNames}
          email={document.created_by}
          size="small"
        />
        {team && (
          <>
            <span className="text-tertiary">·</span>
            <span className="text-secondary">{team}</span>
          </>
        )}
        <span className="text-tertiary">·</span>
        <span className="text-secondary inline-flex items-center gap-1.5 whitespace-nowrap">
          <FolderKanban className="text-tertiary size-3.5" />
          {attached.name}
        </span>
      </div>

      {/* Preview */}
      <p className="text-secondary m-0 line-clamp-2 text-sm leading-[1.55]">
        {excerpt}
      </p>

      {/* Footer */}
      <div className="mt-3.5 flex items-center gap-2">
        <span className="border-secondary bg-primary text-tertiary inline-flex h-7 items-center gap-1.5 rounded-md border px-2 text-xs">
          <MessageSquare className="size-3.5" />
          <span className="tabular-nums">{document.comment_count ?? 0}</span>
        </span>
        <div className="ml-auto inline-flex items-center gap-1.5">
          {document.tags.map((t) => (
            <DocumentTagChip key={t.slug} tag={t} />
          ))}
        </div>
      </div>
    </Card>
  )
}

function feedDate(document: Document): string {
  const iso = document.updated_at ?? document.created_at
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return iso
  }
}
