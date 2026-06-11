import { useState } from 'react'

import { ChevronDown, ChevronRight, ExternalLink } from 'lucide-react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { Badge } from '@/components/ui/badge'
import { UserIdentity } from '@/components/ui/user-identity'
import { formatRelativeDate } from '@/lib/formatDate'
import { cn } from '@/lib/utils'
import type { ReleaseHistoryEntry } from '@/types'

import type { ArtifactInfo } from './artifact'
import { CiStatusDot } from './CiStatusDot'

interface ReleaseHistoryProps {
  artifact: ArtifactInfo
  currentTag: null | string
  releases: ReleaseHistoryEntry[]
}

interface ReleaseRowProps {
  artifact: ArtifactInfo
  isCurrent: boolean
  isOpen: boolean
  onToggle: () => void
  rel: ReleaseHistoryEntry
}

export function ReleaseHistory({
  artifact,
  currentTag,
  releases,
}: ReleaseHistoryProps) {
  const [open, setOpen] = useState<null | string>(null)
  if (releases.length === 0) return null
  return (
    <div className="border-tertiary mt-3 border-t pt-3">
      <p className="text-tertiary mb-2 text-xs tracking-wider uppercase">
        Release history
      </p>
      <div>
        {releases.map((rel) => (
          <ReleaseRow
            artifact={artifact}
            isCurrent={rel.tag === currentTag}
            isOpen={open === rel.tag}
            key={rel.tag}
            onToggle={() => setOpen((o) => (o === rel.tag ? null : rel.tag))}
            rel={rel}
          />
        ))}
      </div>
    </div>
  )
}

// fallow-ignore-next-line complexity
function ReleaseRow({
  artifact,
  isCurrent,
  isOpen,
  onToggle,
  rel,
}: ReleaseRowProps) {
  return (
    <div
      className={cn(
        '-mx-2 rounded-md transition-colors',
        isOpen && 'bg-secondary',
      )}
    >
      <button
        className="hover:bg-secondary grid w-full grid-cols-[auto_auto_auto_1fr_auto] items-center gap-3 rounded-md px-2 py-1.5 text-left"
        onClick={onToggle}
        type="button"
      >
        {isOpen ? (
          <ChevronDown className="text-tertiary size-3.5" />
        ) : (
          <ChevronRight className="text-tertiary size-3.5" />
        )}
        <span className="flex items-center gap-2">
          <span className="font-mono text-sm font-semibold">{rel.tag}</span>
          <CiStatusDot size={13} status={rel.ci_status} />
        </span>
        <span className="text-tertiary font-mono text-xs">{rel.short_sha}</span>
        <span className="text-tertiary text-xs">
          {formatRelativeDate(rel.published_at)}
        </span>
        {isCurrent ? <Badge variant="accent">Latest</Badge> : <span />}
      </button>
      {isOpen ? (
        <div className="px-2 pb-3 pl-[2.1rem]">
          {rel.notes_markdown ? (
            <div className="document-markdown max-w-none text-sm [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
              <Markdown
                components={{
                  a: (props) => (
                    <a {...props} rel="noopener noreferrer" target="_blank" />
                  ),
                }}
                remarkPlugins={[remarkGfm]}
              >
                {rel.notes_markdown}
              </Markdown>
            </div>
          ) : (
            <p className="text-tertiary text-xs">No release notes.</p>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-4">
            {rel.author ? (
              <span className="text-tertiary inline-flex items-center gap-1.5 text-xs">
                released by
                <UserIdentity
                  actor={rel.author}
                  email={rel.author_email}
                  size="small"
                />
              </span>
            ) : null}
            {(rel.release_url ?? rel.tag_url) ? (
              <a
                className="text-tertiary hover:text-primary inline-flex items-center gap-1 text-xs"
                href={(rel.release_url ?? rel.tag_url) as string}
                rel="noopener noreferrer"
                target="_blank"
              >
                <ExternalLink size={12} />
                {rel.release_url ? 'Release notes' : 'View tag'}
              </a>
            ) : null}
            {artifact.indexUrl ? (
              <a
                className="text-tertiary hover:text-primary inline-flex items-center gap-1 text-xs"
                href={artifact.indexUrl}
                rel="noopener noreferrer"
                target="_blank"
              >
                <artifact.icon size={12} />
                {artifact.indexLabel ?? 'Package index'}
              </a>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  )
}
