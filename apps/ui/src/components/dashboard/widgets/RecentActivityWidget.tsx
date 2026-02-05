import { RecentActivity } from '../../RecentActivity'
import { useInfiniteActivityFeed } from '@/hooks/useInfiniteActivityFeed'

interface RecentActivityWidgetProps {
  isDarkMode: boolean
  onUserSelect?: (userName: string) => void
  onProjectSelect?: (projectId: string) => void
}

export function RecentActivityWidget({ isDarkMode, onUserSelect, onProjectSelect }: RecentActivityWidgetProps) {
  const {
    data: activityData,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
  } = useInfiniteActivityFeed()

  const activityFeed = activityData?.activities || []

  return (
    <div className="h-full">
      <RecentActivity
        activities={activityFeed}
        onUserSelect={onUserSelect}
        onProjectSelect={onProjectSelect}
        isDarkMode={isDarkMode}
        hideHeading={false}
        isLoading={isLoading}
        onLoadMore={hasNextPage ? () => fetchNextPage() : undefined}
        isLoadingMore={isFetchingNextPage}
      />
    </div>
  )
}
