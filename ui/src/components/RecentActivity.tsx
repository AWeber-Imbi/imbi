import type { ReactElement } from 'react'
import { useMemo, useState } from 'react'

import { ChevronRight } from 'lucide-react'

import { RelativeTime } from '@/components/ui/RelativeTime'
import { Sk } from '@/components/ui/skeleton'
import { UserIdentity } from '@/components/ui/user-identity'
import { usePluginOpsLogTemplates } from '@/hooks/usePluginOpsLogTemplates'
import type { ActivityFeedEntry, OperationsLogEntry } from '@/types'

import {
  ActivityFilter,
  ALL_ACTORS,
  filterEntries,
} from './activityFeed/ActivityFilter'
import type { ActivityFilterValue } from './activityFeed/ActivityFilter'
import { ClusterEvents } from './activityFeed/ClusterEvents'
import { clusterView } from './activityFeed/clusterView'
import {
  ACTIVITY_GROUP_WINDOW_MS,
  entryClusterKey,
  entryTimeIso,
  entryTimeMs,
} from './activityFeed/entryAdapters'
import { expandableRowProps } from './activityFeed/expandableRow'
import { sectionByDay } from './activityFeed/grouping'
import type { ActivityCluster } from './activityFeed/grouping'
import { renderActivityTemplate } from './activityFeed/renderActivityTemplate'
import { StatusChip, StatusDot } from './activityFeed/StatusChip'
import { Button } from './ui/button'
import { Card } from './ui/card'

// NOTE: The feed API has no correlation/run id, so groups are approximated by
// clustering consecutive same-actor+project entries (see grouping.ts). A
// backend `group_id` would let clusterMeta report true per-run breakdowns
// (e.g. "1 failed · 6 skipped") instead of a per-change_type count.

interface ActivityLineProps {
  activity: ActivityFeedEntry
  onProjectSelect?: (projectName: string) => void
  onUserSelect?: (userName: string) => void
  renderTemplate: (entry: OperationsLogEntry) => null | string
}

interface ClusterRowProps {
  cluster: ActivityCluster<ActivityFeedEntry>
  expanded: boolean
  onProjectSelect?: (projectName: string) => void
  onToggle: () => void
  onUserSelect?: (userName: string) => void
  renderTemplate: (entry: OperationsLogEntry) => null | string
}

interface OpsLogActivityLineProps {
  entry: OperationsLogEntry
  projectButton: null | ReactElement
  renderTemplate: (entry: OperationsLogEntry) => null | string
  userButton: ReactElement
}

interface ProjectFeedActivityLineProps {
  activity: Extract<ActivityFeedEntry, { type: 'ProjectFeedEntry' }>
  projectButton: null | ReactElement
  userButton: ReactElement
}

interface RecentActivityProps {
  activities: ActivityFeedEntry[]
  hideHeading?: boolean
  isLoading?: boolean
  isLoadingMore?: boolean
  onLoadMore?: () => void
  onProjectSelect?: (projectName: string) => void
  onUserSelect?: (userName: string) => void
}

export function RecentActivity({
  activities,
  hideHeading,
  isLoading,
  isLoadingMore,
  onLoadMore,
  onProjectSelect,
  onUserSelect,
}: RecentActivityProps) {
  const { templates } = usePluginOpsLogTemplates()
  const [filter, setFilter] = useState<ActivityFilterValue>(ALL_ACTORS)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  const sections = useMemo(
    () =>
      sectionByDay(filterEntries(activities ?? [], filter), {
        keyOf: entryClusterKey,
        timeOf: entryTimeMs,
        windowMs: ACTIVITY_GROUP_WINDOW_MS,
      }),
    [activities, filter],
  )

  if (isLoading) {
    return (
      <Card className="p-6">
        <Heading hidden={hideHeading} />
        <ActivityFeedSkeleton rows={5} />
      </Card>
    )
  }

  if (!activities || activities.length === 0) {
    return (
      <Card className="p-6">
        <Heading hidden={hideHeading} />
        <div className="text-muted-foreground py-8 text-center">
          No recent activity
        </div>
      </Card>
    )
  }

  const toggle = (key: string) =>
    setExpanded((prev) => ({ ...prev, [key]: !prev[key] }))

  const renderTemplate = (opsEntry: OperationsLogEntry) =>
    renderActivityTemplate(opsEntry, templates)

  return (
    <Card className="p-6">
      <div className="mb-1 flex items-center justify-between">
        <Heading hidden={hideHeading} />
        <ActivityFilter onChange={setFilter} value={filter} />
      </div>

      <div className="max-h-[calc(100vh-380px)] overflow-y-auto pr-2">
        {sections.length === 0 ? (
          <div className="text-tertiary py-8 text-center text-sm">
            No activity matches the filter
          </div>
        ) : (
          sections.map((section) => (
            <div key={section.key}>
              <div className="text-tertiary pt-3.5 pb-1 text-[11.5px] font-semibold tracking-wider uppercase">
                {section.label}
              </div>
              <div className="relative">
                <div
                  className="bg-tertiary absolute w-0.5 rounded"
                  style={{ bottom: 22, left: 5, top: 22 }}
                />
                {section.clusters.map((cluster) => (
                  <ClusterRow
                    cluster={cluster}
                    expanded={isExpanded(cluster, expanded)}
                    key={cluster.key}
                    onProjectSelect={onProjectSelect}
                    onToggle={() => toggle(cluster.key)}
                    onUserSelect={onUserSelect}
                    renderTemplate={renderTemplate}
                  />
                ))}
              </div>
            </div>
          ))
        )}

        {isLoadingMore && <ActivityFeedSkeleton rows={3} />}
        {onLoadMore && !isLoadingMore && (
          <div className="pt-4 text-center">
            <Button
              className="text-info hover:text-info/80 h-auto p-0 text-sm transition-colors"
              onClick={onLoadMore}
              variant="link"
            >
              Load more activity
            </Button>
          </div>
        )}
      </div>
    </Card>
  )
}

function ActivityFeedSkeleton({ rows }: { rows: number }) {
  return (
    <div aria-hidden className="space-y-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div
          className="border-tertiary flex gap-3 border-b pb-4 last:border-0 last:pb-0"
          key={i}
        >
          <Sk circle h={40} w={40} />
          <div className="flex-1 space-y-2">
            <Sk h={14} w="85%" />
            <Sk h={11} w={90} />
          </div>
        </div>
      ))}
    </div>
  )
}

function ActivityLine({
  activity,
  onProjectSelect,
  onUserSelect,
  renderTemplate,
}: ActivityLineProps) {
  const userButton = (
    <Button
      className="text-primary hover:text-info h-auto p-0 font-medium transition-colors"
      onClick={() => onUserSelect?.(activity.display_name)}
      variant="link"
    >
      {activity.display_name}
    </Button>
  )
  const projectButton = activity.project_name ? (
    <Button
      className="text-info hover:text-info/80 h-auto p-0 font-medium transition-colors"
      onClick={() => onProjectSelect?.(activity.project_name!)}
      variant="link"
    >
      {activity.project_name}
    </Button>
  ) : null

  if (activity.type === 'OperationsLogEntry') {
    return (
      <OpsLogActivityLine
        entry={activity}
        projectButton={projectButton}
        renderTemplate={renderTemplate}
        userButton={userButton}
      />
    )
  }

  return (
    <ProjectFeedActivityLine
      activity={activity}
      projectButton={projectButton}
      userButton={userButton}
    />
  )
}

function ClusterRow({
  cluster,
  expanded,
  onProjectSelect,
  onToggle,
  onUserSelect,
  renderTemplate,
}: ClusterRowProps) {
  const { isGroup, lead, meta, tone } = clusterView(cluster)

  return (
    <div className="border-tertiary relative z-1 border-b py-3 last:border-0">
      <div className="grid grid-cols-[26px_1fr] gap-x-3">
        <StatusDot tone={tone} />
        <div
          className={`flex items-start gap-2.5 ${isGroup ? 'cursor-pointer' : ''}`}
          {...expandableRowProps(isGroup, expanded, onToggle)}
        >
          <UserIdentity
            displayName={lead.display_name}
            email={lead.email_address}
            hideName
            linkToProfile={false}
            size="floating"
          />
          <div className="min-w-0 flex-1">
            {isGroup ? (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[13.5px] font-semibold">
                    {lead.display_name}
                  </span>
                  <StatusChip label={meta.statusLabel} tone={tone} />
                  <span className="bg-secondary text-secondary rounded-full px-2 font-mono text-[11px]">
                    {cluster.items.length}
                  </span>
                </div>
                <div className="text-tertiary mt-0.5 text-[12.5px]">
                  {meta.summary}
                </div>
              </>
            ) : (
              <ActivityLine
                activity={lead}
                onProjectSelect={onProjectSelect}
                onUserSelect={onUserSelect}
                renderTemplate={renderTemplate}
              />
            )}
          </div>
          <div className="mt-0.5 flex shrink-0 items-center gap-2.5">
            <RelativeTime
              className="text-tertiary font-mono text-[11.5px] whitespace-nowrap"
              value={entryTimeIso(lead)}
              variant="short"
            />
            {isGroup && (
              <ChevronRight
                className="text-tertiary size-3.75 transition-transform"
                style={{ transform: expanded ? 'rotate(90deg)' : 'none' }}
              />
            )}
          </div>
        </div>
      </div>
      {isGroup && expanded && <ClusterEvents items={cluster.items} />}
    </div>
  )
}

function Heading({ hidden }: { hidden?: boolean }) {
  if (hidden) return null
  return <h2 className="text-primary text-xl">Recent Activity</h2>
}

/** Danger clusters auto-expand (mockup's autoExpandFailed) until toggled. */
function isExpanded(
  cluster: ActivityCluster<ActivityFeedEntry>,
  state: Record<string, boolean>,
): boolean {
  if (cluster.key in state) return state[cluster.key]
  return cluster.items.length > 1 && clusterView(cluster).tone === 'danger'
}

function OpsLogActivityLine({
  entry,
  projectButton,
  renderTemplate,
  userButton,
}: OpsLogActivityLineProps) {
  const rendered = renderTemplate(entry)
  if (rendered) {
    return (
      <p className="text-secondary text-sm leading-relaxed">
        {userButton} {rendered}
        {projectButton ? <> on {projectButton}</> : null}
      </p>
    )
  }
  return (
    <p className="text-secondary text-sm leading-relaxed">
      {userButton} {entry.change_type.toLowerCase()} {projectButton}
      {entry.environment && (
        <span>
          {entry.change_type === 'Deployed' ? ' to the ' : ' in the '}
          {entry.environment} environment.
        </span>
      )}
      {entry.version && (
        <span className="text-tertiary"> ({entry.version})</span>
      )}
    </p>
  )
}

function ProjectFeedActivityLine({
  activity,
  projectButton,
  userButton,
}: ProjectFeedActivityLineProps) {
  const trailing = activity.what === 'updated facts' ? ' project.' : '.'
  const verbPhrase =
    activity.what === 'updated facts' ? 'updated facts for the' : activity.what
  return (
    <p className="text-secondary text-sm leading-relaxed">
      {userButton} {verbPhrase} {projectButton}
      {trailing}
    </p>
  )
}
