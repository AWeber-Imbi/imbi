import type { Environment, Project } from '@/types'
import { OperationsLogReleaseCard } from './OperationsLogReleaseCard'
import { OperationsLogStreamRow } from './OperationsLogStreamRow'
import type { FeedItem } from './opsLogHelpers'

export type VItem =
  | { kind: 'header'; key: string; label: string; date: Date; count: number }
  | { kind: 'rel'; key: string; id: string; isOpen: boolean }
  | { kind: 'evt'; key: string; id: string; isOpen: boolean }

interface Props {
  vi: VItem
  groupsById: Map<string, FeedItem>
  projectsBySlug: Map<string, Project>
  environmentsBySlug: Map<string, Environment>
  performerDisplayNames: Map<string, string>
  toggleOpen: (id: string) => void
}

export function OperationsLogFeedItem({
  vi,
  groupsById,
  projectsBySlug,
  environmentsBySlug,
  performerDisplayNames,
  toggleOpen,
}: Props) {
  if (vi.kind === 'header') {
    return (
      <div className="flex items-center gap-2.5 border-b border-tertiary bg-secondary px-3 py-1.5">
        <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-tertiary">
          {vi.label}
        </span>
        <span className="font-mono text-[11px] text-tertiary">
          {vi.date.toLocaleDateString(undefined, {
            month: 'short',
            day: 'numeric',
          })}
        </span>
        <span className="flex-1" />
        <span className="font-mono text-[11px] text-tertiary">
          {vi.count} {vi.count === 1 ? 'event' : 'events'}
        </span>
      </div>
    )
  }
  const feed = groupsById.get(vi.id)
  if (!feed) return null
  if (vi.kind === 'rel' && feed.kind === 'release') {
    return (
      <OperationsLogReleaseCard
        id={vi.id}
        group={feed.group}
        project={projectsBySlug.get(feed.group.project_slug)}
        environmentsBySlug={environmentsBySlug}
        isOpen={vi.isOpen}
        onToggle={toggleOpen}
        performerDisplayNames={performerDisplayNames}
      />
    )
  }
  if (vi.kind === 'evt' && feed.kind === 'single') {
    return (
      <OperationsLogStreamRow
        id={vi.id}
        entry={feed.entry}
        project={projectsBySlug.get(feed.entry.project_slug)}
        environment={environmentsBySlug.get(feed.entry.environment_slug)}
        isOpen={vi.isOpen}
        onToggle={toggleOpen}
        performerDisplayNames={performerDisplayNames}
      />
    )
  }
  return null
}
