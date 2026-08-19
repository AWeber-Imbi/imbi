import { useInfiniteQuery } from '@tanstack/react-query'

import type { MaintenanceLogFilters, MaintenanceLogPage } from '@/api/endpoints'
import { getMaintenanceLog } from '@/api/endpoints'

const PAGE_SIZE = 50

// Pages the maintenance activity log, newest first. The counts ride on
// the first page only — the server does not recompute ninety days of
// totals per "load more" — so they are read from `pages[0]` rather than
// merged across pages.
export function useMaintenanceLog(filters: MaintenanceLogFilters) {
  const query = useInfiniteQuery({
    getNextPageParam: (lastPage: MaintenanceLogPage) => lastPage.nextCursor,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) =>
      getMaintenanceLog(
        { cursor: pageParam, filters, limit: PAGE_SIZE },
        signal,
      ),
    queryKey: ['maintenance-log', filters],
  })

  return {
    counts: query.data?.pages[0]?.counts,
    entries: query.data?.pages.flatMap((page) => page.entries) ?? [],
    error: query.error,
    fetchNextPage: query.fetchNextPage,
    hasNextPage: query.hasNextPage,
    isError: query.isError,
    isFetching: query.isFetching,
    isFetchingNextPage: query.isFetchingNextPage,
    isLoading: query.isLoading,
    refetch: query.refetch,
  }
}
