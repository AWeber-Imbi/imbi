import { useMemo, useState } from 'react'

import { ChevronRight } from 'lucide-react'

import { RelativeTime } from '@/components/ui/RelativeTime'
import { Sk, Swap } from '@/components/ui/skeleton'
import { UserIdentity } from '@/components/ui/user-identity'
import { swatchForName } from '@/lib/chip-colors'
import type { ActivityFeedEntry } from '@/types'

import { Card } from '../ui/card'
import { ActivityFilter, ALL_ACTORS, filterEntries } from './ActivityFilter'
import type { ActivityFilterValue } from './ActivityFilter'
import { ClusterEvents } from './ClusterEvents'
import { clusterView } from './clusterView'
import {
  ACTIVITY_GROUP_WINDOW_MS,
  entryClusterKey,
  entryNamespace,
  entryProjectName,
  entryProjectType,
  entrySummaryText,
  entryTimeIso,
  entryTimeMs,
} from './entryAdapters'
import type { ClusterMeta } from './entryAdapters'
import { expandableRowProps } from './expandableRow'
import { clusterConsecutive } from './grouping'
import type { ActivityCluster } from './grouping'
import { StatusChip, StatusDot } from './StatusChip'
import type { Tone } from './tone'

interface ProjectActivityFeedProps {
  activities: ActivityFeedEntry[]
  /** Query failed — render a placeholder instead of an empty feed. */
  isError?: boolean
  isLoading?: boolean
  isLoadingMore?: boolean
  onLoadMore?: () => void
  onProjectSelect?: (projectName: string) => void
  /** Header subtitle, e.g. "Across all projects · AWeber". */
  subtitle?: string
}

interface ProjectClusterRowProps {
  cluster: ActivityCluster<ActivityFeedEntry>
  expanded: boolean
  onProjectSelect?: (projectName: string) => void
  onToggle: () => void
}

interface ProjectFeedBodyProps {
  clusters: ActivityCluster<ActivityFeedEntry>[]
  expanded: Record<string, boolean>
  hasActivities: boolean
  isError?: boolean
  isLoading?: boolean
  isLoadingMore?: boolean
  onLoadMore?: () => void
  onProjectSelect?: (projectName: string) => void
  onToggle: (key: string) => void
}

/**
 * Compact, project-centric activity feed (dashboard widget). Unlike the
 * full RecentActivity feed this is a flat clustered list (no date sections)
 * that leads with the project each burst touched.
 */
export function ProjectActivityFeed({
  activities,
  isError,
  isLoading,
  isLoadingMore,
  onLoadMore,
  onProjectSelect,
  subtitle,
}: ProjectActivityFeedProps) {
  const [filter, setFilter] = useState<ActivityFilterValue>(ALL_ACTORS)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  const clusters = useMemo(
    () =>
      clusterConsecutive(filterEntries(activities ?? [], filter), {
        keyOf: entryClusterKey,
        timeOf: entryTimeMs,
        windowMs: ACTIVITY_GROUP_WINDOW_MS,
      }),
    [activities, filter],
  )

  const toggle = (key: string) =>
    setExpanded((prev) => ({ ...prev, [key]: !prev[key] }))

  return (
    <Card className="flex h-full flex-col overflow-hidden p-0">
      <div className="border-tertiary flex items-start justify-between border-b px-5 py-4">
        <div>
          <div className="text-primary text-[15px] font-semibold">
            Recent activity
          </div>
          {subtitle && (
            <div className="text-tertiary mt-0.5 text-xs">{subtitle}</div>
          )}
        </div>
        <ActivityFilter onChange={setFilter} value={filter} />
      </div>

      <div className="relative flex-1 overflow-y-auto px-4 py-1">
        <ProjectFeedBody
          clusters={clusters}
          expanded={expanded}
          hasActivities={activities.length > 0}
          isError={isError}
          isLoading={isLoading}
          isLoadingMore={isLoadingMore}
          onLoadMore={onLoadMore}
          onProjectSelect={onProjectSelect}
          onToggle={toggle}
        />
      </div>
    </Card>
  )
}

function ProjectActorLine({
  count,
  isGroup,
  lead,
  meta,
  tone,
}: {
  count: number
  isGroup: boolean
  lead: ActivityFeedEntry
  meta: ClusterMeta
  tone: Tone
}) {
  return (
    <div className="mt-1 flex flex-wrap items-center gap-2">
      <UserIdentity
        displayName={lead.display_name}
        email={lead.email_address}
        hideName
        linkToProfile={false}
        size="small"
      />
      <span className="text-secondary text-[12.5px]">{lead.display_name}</span>
      {isGroup && (
        <>
          <StatusChip label={meta.statusLabel} tone={tone} />
          <span className="bg-secondary text-secondary rounded-full px-2 font-mono text-[10.5px]">
            {count}
          </span>
        </>
      )}
    </div>
  )
}

// fallow-ignore-next-line complexity
function ProjectClusterRow({
  cluster,
  expanded,
  onProjectSelect,
  onToggle,
}: ProjectClusterRowProps) {
  const { isGroup, lead, meta, tone } = clusterView(cluster)

  return (
    <div className="border-tertiary relative z-1 border-b py-3 last:border-0">
      <div className="grid grid-cols-[18px_1fr_auto] gap-x-3">
        <StatusDot size={11} tone={tone} />
        <div
          className={`min-w-0 ${isGroup ? 'cursor-pointer' : ''}`}
          {...expandableRowProps(isGroup, expanded, onToggle)}
        >
          <ProjectRowHeader entry={lead} onProjectSelect={onProjectSelect} />
          <ProjectActorLine
            count={cluster.items.length}
            isGroup={isGroup}
            lead={lead}
            meta={meta}
            tone={tone}
          />
          <div className="text-tertiary mt-1 text-[12.5px]">
            {isGroup ? meta.summary : entrySummaryText(lead)}
          </div>
        </div>

        <div className="mt-px flex shrink-0 items-center gap-2">
          <RelativeTime
            className="text-tertiary font-mono text-[11px] whitespace-nowrap"
            value={entryTimeIso(lead)}
            variant="narrow"
          />
          {isGroup && (
            <ChevronRight
              className="text-tertiary size-3.5 transition-transform"
              style={{ transform: expanded ? 'rotate(90deg)' : 'none' }}
            />
          )}
        </div>
      </div>
      {isGroup && expanded && (
        <ClusterEvents indent={29} items={cluster.items} />
      )}
    </div>
  )
}

function ProjectFeedBody({ isLoading, ...rest }: ProjectFeedBodyProps) {
  return (
    <Swap
      delay={50}
      ready={!isLoading}
      skeleton={<ProjectFeedSkeleton rows={5} />}
    >
      <ProjectFeedContent {...rest} />
    </Swap>
  )
}

// fallow-ignore-next-line complexity
function ProjectFeedContent({
  clusters,
  expanded,
  hasActivities,
  isError,
  isLoadingMore,
  onLoadMore,
  onProjectSelect,
  onToggle,
}: Omit<ProjectFeedBodyProps, 'isLoading'>) {
  if (isError) {
    return (
      <div className="text-tertiary py-10 text-center text-sm">
        Activity unavailable
      </div>
    )
  }
  if (clusters.length === 0) {
    return (
      <div className="text-tertiary py-10 text-center text-sm">
        {hasActivities
          ? 'No activity matches the filter'
          : 'No recent activity'}
      </div>
    )
  }
  return (
    <>
      <div
        className="bg-tertiary absolute w-0.5 rounded"
        style={{ bottom: 20, left: 25, top: 20 }}
      />
      {clusters.map((cluster) => (
        <ProjectClusterRow
          cluster={cluster}
          expanded={!!expanded[cluster.key]}
          key={cluster.key}
          onProjectSelect={onProjectSelect}
          onToggle={() => onToggle(cluster.key)}
        />
      ))}
      {isLoadingMore && <ProjectFeedSkeleton rows={2} />}
      {onLoadMore && !isLoadingMore && (
        <button
          className="text-secondary hover:bg-secondary hover:text-primary w-full rounded-md py-2.5 text-center text-[12.5px] font-medium transition-colors"
          onClick={onLoadMore}
          type="button"
        >
          Load more
        </button>
      )}
    </>
  )
}

/** Footprint mirrors ProjectClusterRow: dot · header/actor/summary · time. */
function ProjectFeedSkeleton({ rows }: { rows: number }) {
  return (
    <div aria-hidden className="space-y-3 py-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div className="grid grid-cols-[18px_1fr_auto] gap-x-3" key={i}>
          <Sk circle h={11} w={11} />
          <div className="min-w-0 space-y-1.5">
            <Sk h={13} w="45%" />
            <div className="flex items-center gap-2">
              <Sk circle h={16} w={16} />
              <Sk h={11} w="30%" />
            </div>
            <Sk h={11} w="60%" />
          </div>
          <Sk h={11} w={28} />
        </div>
      ))}
    </div>
  )
}

function ProjectRowHeader({
  entry,
  onProjectSelect,
}: {
  entry: ActivityFeedEntry
  onProjectSelect?: (projectName: string) => void
}) {
  const project = entryProjectName(entry)
  const projectType = entryProjectType(entry)
  const namespace = entryNamespace(entry)
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
      {project ? (
        <button
          className="text-primary hover:text-info truncate text-[13.5px] font-semibold transition-colors"
          onClick={(e) => {
            e.stopPropagation()
            onProjectSelect?.(project)
          }}
          type="button"
        >
          {project}
        </button>
      ) : (
        <span className="text-primary text-[13.5px] font-semibold">
          Activity
        </span>
      )}
      {projectType && (
        <span className="text-tertiary text-[11px]">{projectType}</span>
      )}
      {namespace && (
        <span className="text-tertiary inline-flex items-center gap-1 text-[11px]">
          <span
            className="size-1.5 rounded-full"
            style={{ background: swatchForName(namespace) }}
          />
          {namespace}
        </span>
      )}
    </div>
  )
}
