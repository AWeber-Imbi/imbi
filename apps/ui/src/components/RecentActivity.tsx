import md5 from 'md5'
import { Card } from './ui/card'
import type { ActivityFeedEntry } from '@/types'

interface RecentActivityProps {
  activities: ActivityFeedEntry[]
  onUserSelect?: (userName: string) => void
  onProjectSelect?: (projectName: string) => void
  hideHeading?: boolean
  isLoading?: boolean
  onLoadMore?: () => void
  isLoadingMore?: boolean
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

function getGravatarUrl(email: string, size: number = 40): string {
  const hash = md5(email.trim().toLowerCase())
  return `https://www.gravatar.com/avatar/${hash}?s=${size}&d=identicon`
}

export function RecentActivity({
  activities,
  onUserSelect,
  onProjectSelect,
  hideHeading,
  isLoading,
  onLoadMore,
  isLoadingMore,
}: RecentActivityProps) {
  if (isLoading) {
    return (
      <Card className="p-6">
        {!hideHeading && (
          <h2 className="mb-6 text-xl text-primary">Recent Activity</h2>
        )}
        <div className="py-8 text-center text-muted-foreground">Loading...</div>
      </Card>
    )
  }

  if (!activities || activities.length === 0) {
    return (
      <Card className="p-6">
        {!hideHeading && (
          <h2 className="mb-6 text-xl text-primary">Recent Activity</h2>
        )}
        <div className="py-8 text-center text-muted-foreground">
          No recent activity
        </div>
      </Card>
    )
  }

  const activityList = (
    <div className="max-h-[calc(100vh-380px)] space-y-4 overflow-y-auto pr-2">
      {activities.map((activity, index) => (
        <div
          key={index}
          className="border-b border-tertiary pb-4 last:border-0 last:pb-0"
        >
          <div className="flex gap-3">
            <img
              src={getGravatarUrl(activity.email_address)}
              alt={activity.display_name}
              className="h-10 w-10 flex-shrink-0 rounded-full"
            />

            <div className="min-w-0 flex-1">
              <p className="text-sm leading-relaxed text-secondary">
                <button
                  onClick={() => onUserSelect?.(activity.display_name)}
                  className="font-medium text-primary transition-colors hover:text-info"
                >
                  {activity.display_name}
                </button>{' '}
                {activity.type === 'OperationsLogEntry'
                  ? activity.change_type.toLowerCase()
                  : activity.what === 'updated facts'
                    ? 'updated facts for the'
                    : activity.what}{' '}
                {activity.project_name && (
                  <button
                    onClick={() => onProjectSelect?.(activity.project_name!)}
                    className="hover:text-info/80 font-medium text-info transition-colors"
                  >
                    {activity.project_name}
                  </button>
                )}
                {activity.type === 'OperationsLogEntry' &&
                  activity.environment && (
                    <span>
                      {activity.change_type === 'Deployed'
                        ? ' to the '
                        : ' in the '}
                      {activity.environment} environment.
                    </span>
                  )}
                {activity.type === 'ProjectFeedEntry' &&
                  activity.what === 'updated facts' &&
                  ' project.'}
                {activity.type === 'ProjectFeedEntry' &&
                  activity.what !== 'updated facts' &&
                  '.'}
                {activity.type === 'OperationsLogEntry' && activity.version && (
                  <span className="text-tertiary"> ({activity.version})</span>
                )}
              </p>

              <p className="mt-1 text-xs text-tertiary">
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
          <button
            onClick={onLoadMore}
            disabled={isLoadingMore}
            className="hover:text-info/80 text-sm text-info transition-colors disabled:opacity-50"
          >
            {isLoadingMore ? 'Loading more...' : 'Load more activity'}
          </button>
        </div>
      )}
    </div>
  )

  return (
    <Card className="p-6">
      {!hideHeading && (
        <h2 className="mb-6 text-xl text-primary">Recent Activity</h2>
      )}
      {activityList}
    </Card>
  )
}
