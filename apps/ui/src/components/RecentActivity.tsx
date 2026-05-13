import type { ReactElement } from 'react'

import md5 from 'md5'

import { usePluginOpsLogTemplates } from '@/hooks/usePluginOpsLogTemplates'
import type { ActivityFeedEntry, OperationsLogEntry } from '@/types'

import { renderActivityTemplate } from './activityFeed/renderActivityTemplate'
import { Button } from './ui/button'
import { Card } from './ui/card'

interface ActivityLineProps {
  activity: ActivityFeedEntry
  onProjectSelect?: (projectName: string) => void
  onUserSelect?: (userName: string) => void
  // When the activity is an ops-log entry whose plugin ships a template
  // for the embedded ``action``, return the rendered label string;
  // otherwise return ``null`` so the line falls back to the legacy
  // hand-built sentence.
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
  if (isLoading) {
    return (
      <Card className="p-6">
        {!hideHeading && (
          <h2 className="text-primary mb-6 text-xl">Recent Activity</h2>
        )}
        <div className="text-muted-foreground py-8 text-center">Loading...</div>
      </Card>
    )
  }

  if (!activities || activities.length === 0) {
    return (
      <Card className="p-6">
        {!hideHeading && (
          <h2 className="text-primary mb-6 text-xl">Recent Activity</h2>
        )}
        <div className="text-muted-foreground py-8 text-center">
          No recent activity
        </div>
      </Card>
    )
  }

  const activityList = (
    <div className="max-h-[calc(100vh-380px)] space-y-4 overflow-y-auto pr-2">
      {activities.map((activity, index) => (
        <div
          className="border-tertiary border-b pb-4 last:border-0 last:pb-0"
          key={index}
        >
          <div className="flex gap-3">
            <img
              alt={activity.display_name}
              className="size-10 shrink-0 rounded-full"
              src={getGravatarUrl(activity.email_address)}
            />

            <div className="min-w-0 flex-1">
              <ActivityLine
                activity={activity}
                onProjectSelect={onProjectSelect}
                onUserSelect={onUserSelect}
                renderTemplate={(opsEntry) =>
                  renderActivityTemplate(opsEntry, templates)
                }
              />

              <p className="text-tertiary mt-1 text-xs">
                {getRelativeTime(
                  activity.occurred_at ||
                    (activity.type === 'ProjectFeedEntry'
                      ? activity.when
                      : undefined) ||
                    '',
                )}
              </p>
            </div>
          </div>
        </div>
      ))}

      {/* Load More Button */}
      {onLoadMore && (
        <div className="pt-4 text-center">
          <Button
            className="text-info hover:text-info/80 h-auto p-0 text-sm transition-colors disabled:opacity-50"
            disabled={isLoadingMore}
            onClick={onLoadMore}
            variant="link"
          >
            {isLoadingMore ? 'Loading more...' : 'Load more activity'}
          </Button>
        </div>
      )}
    </div>
  )

  return (
    <Card className="p-6">
      {!hideHeading && (
        <h2 className="text-primary mb-6 text-xl">Recent Activity</h2>
      )}
      {activityList}
    </Card>
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

function getGravatarUrl(email: string, size: number = 40): string {
  const hash = md5(email.trim().toLowerCase())
  return `https://www.gravatar.com/avatar/${hash}?s=${size}&d=identicon`
}

function getRelativeTime(timestamp: string): string {
  try {
    const now = new Date()
    const past = new Date(timestamp)

    // Check if date is valid
    if (isNaN(past.getTime())) {
      console.warn('Invalid timestamp:', timestamp)
      return `Invalid date: ${timestamp}`
    }

    const diffMs = now.getTime() - past.getTime()

    // Handle future dates or invalid differences
    if (diffMs < 0) {
      return 'just now'
    }

    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) {
      return 'just now'
    } else if (diffMins < 60) {
      return `${diffMins} ${diffMins === 1 ? 'minute' : 'minutes'} ago`
    } else if (diffHours < 24) {
      return `${diffHours} ${diffHours === 1 ? 'hour' : 'hours'} ago`
    } else {
      return `${diffDays} ${diffDays === 1 ? 'day' : 'days'} ago`
    }
  } catch (error) {
    console.error('Error parsing timestamp:', timestamp, error)
    return 'unknown time'
  }
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
