import md5 from 'md5'
import { Card } from './ui/card'
import type { ActivityFeedEntry } from '@/types'

interface RecentActivityProps {
  activities: ActivityFeedEntry[]
  onUserSelect?: (userName: string) => void
  onProjectSelect?: (projectName: string) => void
  isDarkMode: boolean
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
  isDarkMode,
  hideHeading,
  isLoading,
  onLoadMore,
  isLoadingMore
}: RecentActivityProps) {
  if (isLoading) {
    return (
      <Card className={`p-6 ${isDarkMode ? 'bg-gray-800 border-gray-700' : ''}`}>
        {!hideHeading && (
          <h2 className={`text-xl mb-6 ${isDarkMode ? 'text-white' : 'text-slate-900'}`}>
            Recent Activity
          </h2>
        )}
        <div className="text-center py-8 text-muted-foreground">Loading...</div>
      </Card>
    )
  }

  if (!activities || activities.length === 0) {
    return (
      <Card className={`p-6 ${isDarkMode ? 'bg-gray-800 border-gray-700' : ''}`}>
        {!hideHeading && (
          <h2 className={`text-xl mb-6 ${isDarkMode ? 'text-white' : 'text-slate-900'}`}>
            Recent Activity
          </h2>
        )}
        <div className="text-center py-8 text-muted-foreground">No recent activity</div>
      </Card>
    )
  }

  const activityList = (
    <div className="space-y-4 max-h-[calc(100vh-380px)] overflow-y-auto pr-2">
      {activities.map((activity, index) => (
        <div
          key={index}
          className={`pb-4 border-b last:border-0 last:pb-0 ${
            isDarkMode ? 'border-gray-700' : 'border-slate-100'
          }`}
        >
          <div className="flex gap-3">
            <img
              src={getGravatarUrl(activity.email_address)}
              alt={activity.display_name}
              className="w-10 h-10 rounded-full flex-shrink-0"
            />

            <div className="flex-1 min-w-0">
              <p className={`text-sm leading-relaxed ${isDarkMode ? 'text-gray-300' : 'text-slate-700'}`}>
                <button
                  onClick={() => onUserSelect?.(activity.display_name)}
                  className={`font-medium ${
                    isDarkMode
                      ? 'text-white hover:text-blue-400'
                      : 'text-slate-900 hover:text-blue-600'
                  } transition-colors`}
                >
                  {activity.display_name}
                </button>
                {' '}
                {activity.type === 'OperationsLogEntry'
                  ? activity.change_type.toLowerCase()
                  : activity.what === 'updated facts' ? 'updated facts for the' : activity.what
                }
                {' '}
                {activity.project_name && (
                  <button
                    onClick={() => onProjectSelect?.(activity.project_name!)}
                    className={`font-medium ${
                      isDarkMode
                        ? 'text-blue-400 hover:text-blue-300'
                        : 'text-blue-600 hover:text-blue-700'
                    } transition-colors`}
                  >
                    {activity.project_name}
                  </button>
                )}
                {activity.type === 'OperationsLogEntry' && activity.environment && (
                  <span>
                    {activity.change_type === 'Deployed' ? ' to the ' : ' in the '}
                    {activity.environment} environment.
                  </span>
                )}
                {activity.type === 'ProjectFeedEntry' && activity.what === 'updated facts' && ' project.'}
                {activity.type === 'ProjectFeedEntry' && activity.what !== 'updated facts' && '.'}
                {activity.type === 'OperationsLogEntry' && activity.version && (
                  <span className={isDarkMode ? 'text-gray-500' : 'text-slate-500'}> ({activity.version})</span>
                )}
              </p>

              <p className={`text-xs mt-1 ${isDarkMode ? 'text-gray-500' : 'text-slate-400'}`}>
                {getRelativeTime(activity.occurred_at || (activity.type === 'ProjectFeedEntry' ? activity.when : undefined) || '')}
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
            className={`text-sm ${
              isDarkMode
                ? 'text-blue-400 hover:text-blue-300'
                : 'text-blue-600 hover:text-blue-700'
            } disabled:opacity-50 transition-colors`}
          >
            {isLoadingMore ? 'Loading more...' : 'Load more activity'}
          </button>
        </div>
      )}
    </div>
  )

  return (
    <Card className={`p-6 ${isDarkMode ? 'bg-gray-800 border-gray-700' : ''}`}>
      {!hideHeading && (
        <h2 className={`text-xl mb-6 ${isDarkMode ? 'text-white' : 'text-slate-900'}`}>
          Recent Activity
        </h2>
      )}
      {activityList}
    </Card>
  )
}
