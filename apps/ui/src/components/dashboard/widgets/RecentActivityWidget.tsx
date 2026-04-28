import { useOrganization } from '@/contexts/OrganizationContext'
import { useInfiniteActivityFeed } from '@/hooks/useInfiniteActivityFeed'

import { RecentActivity } from '../../RecentActivity'

interface RecentActivityWidgetProps {
  onProjectSelect?: (projectId: string) => void
  onUserSelect?: (userName: string) => void
}

export function RecentActivityWidget({
  onProjectSelect,
  onUserSelect,
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
        hideHeading={false}
        isLoading={isLoading}
        isLoadingMore={isFetchingNextPage}
        onLoadMore={hasNextPage ? () => fetchNextPage() : undefined}
        onProjectSelect={onProjectSelect}
        onUserSelect={onUserSelect}
      />
    </div>
  )
}
