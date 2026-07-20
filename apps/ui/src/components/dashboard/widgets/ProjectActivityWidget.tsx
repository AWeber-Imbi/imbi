import { useOrganization } from '@/contexts/OrganizationContext'
import { useInfiniteActivityFeed } from '@/hooks/useInfiniteActivityFeed'

import { ProjectActivityFeed } from '../../activityFeed/ProjectActivityFeed'

interface ProjectActivityWidgetProps {
  onProjectSelect?: (projectName: string) => void
}

// Thin data-wiring wrapper (mirrors RecentActivityWidget).
// fallow-ignore-next-line complexity
export function ProjectActivityWidget({
  onProjectSelect,
}: ProjectActivityWidgetProps) {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''
  const {
    data: activityData,
    fetchNextPage,
    hasNextPage,
    isError,
    isFetchingNextPage,
    isLoading,
  } = useInfiniteActivityFeed(orgSlug)

  const subtitle = selectedOrganization?.name
    ? `Across all projects · ${selectedOrganization.name}`
    : 'Across all projects'

  return (
    <div className="h-full">
      <ProjectActivityFeed
        activities={activityData?.activities ?? []}
        isError={isError}
        isLoading={isLoading}
        isLoadingMore={isFetchingNextPage}
        onLoadMore={hasNextPage ? () => fetchNextPage() : undefined}
        onProjectSelect={onProjectSelect}
        subtitle={subtitle}
      />
    </div>
  )
}
