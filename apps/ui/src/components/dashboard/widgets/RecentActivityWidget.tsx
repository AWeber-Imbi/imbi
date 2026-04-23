import { RecentActivity } from '../../RecentActivity'
import { useInfiniteActivityFeed } from '@/hooks/useInfiniteActivityFeed'
import { useOrganization } from '@/contexts/OrganizationContext'

interface RecentActivityWidgetProps {
  onUserSelect?: (userName: string) => void
  onProjectSelect?: (projectId: string) => void
}

export function RecentActivityWidget({
  onUserSelect,
  onProjectSelect,
}: RecentActivityWidgetProps) {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''
  const {
    data: activityData,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
  } = useInfiniteActivityFeed(orgSlug)

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
