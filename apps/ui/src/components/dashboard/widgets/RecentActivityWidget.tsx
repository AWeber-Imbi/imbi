import { RecentActivity } from '../../RecentActivity'
import { useInfiniteActivityFeed } from '@/hooks/useInfiniteActivityFeed'

interface RecentActivityWidgetProps {
  onUserSelect?: (userName: string) => void
  onProjectSelect?: (projectId: string) => void
}

export function RecentActivityWidget({
  onUserSelect,
  onProjectSelect,
}: RecentActivityWidgetProps) {
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
        hideHeading={false}
        isLoading={isLoading}
        onLoadMore={hasNextPage ? () => fetchNextPage() : undefined}
        isLoadingMore={isFetchingNextPage}
      />
    </div>
  )
}
