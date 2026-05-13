import type { Environment, Project } from '@/types'

import { OperationsLogReleaseCard } from './OperationsLogReleaseCard'
import { OperationsLogStreamRow } from './OperationsLogStreamRow'
import type { FeedItem } from './opsLogHelpers'

export type VItem =
  | { count: number; date: Date; key: string; kind: 'header'; label: string }
  | { id: string; isOpen: boolean; key: string; kind: 'evt' }
  | { id: string; isOpen: boolean; key: string; kind: 'rel' }

interface Props {
  environmentsBySlug: Map<string, Environment>
  groupsById: Map<string, FeedItem>
  performerDisplayNames: Map<string, string>
  projectsBySlug: Map<string, Project>
  toggleOpen: (id: string) => void
  vi: VItem
}

export function OperationsLogFeedItem({
  environmentsBySlug,
  groupsById,
  performerDisplayNames,
  projectsBySlug,
  toggleOpen,
  vi,
}: Props) {
  if (vi.kind === 'header') {
    return (
      <div className="border-tertiary bg-secondary flex items-center gap-2.5 border-b px-3 py-1.5">
        <span className="text-tertiary text-[11px] font-semibold tracking-[0.06em] uppercase">
          {vi.label}
        </span>
        <span className="text-tertiary font-mono text-[11px]">
          {vi.date.toLocaleDateString(undefined, {
            day: 'numeric',
            month: 'short',
          })}
        </span>
        <span className="flex-1" />
        <span className="text-tertiary font-mono text-[11px]">
          {vi.count.toLocaleString()} {vi.count === 1 ? 'event' : 'events'}
        </span>
      </div>
    )
  }
  const feed = groupsById.get(vi.id)
  if (!feed) return null
  if (vi.kind === 'rel' && feed.kind === 'release') {
    return (
      <OperationsLogReleaseCard
        environmentsBySlug={environmentsBySlug}
        group={feed.group}
        id={vi.id}
        isOpen={vi.isOpen}
        onToggle={toggleOpen}
        performerDisplayNames={performerDisplayNames}
        project={projectsBySlug.get(feed.group.project_slug)}
      />
    )
  }
  if (vi.kind === 'evt' && feed.kind === 'single') {
    return (
      <OperationsLogStreamRow
        entry={feed.entry}
        environment={environmentsBySlug.get(feed.entry.environment_slug)}
        id={vi.id}
        isOpen={vi.isOpen}
        onToggle={toggleOpen}
        performerDisplayNames={performerDisplayNames}
        project={projectsBySlug.get(feed.entry.project_slug)}
      />
    )
  }
  return null
}
