import { useInfiniteQuery } from '@tanstack/react-query'
import { listOperationsLog } from '@/api/endpoints'
import type { OperationsLogFilters } from '@/types'

const PAGE_SIZE = 200

export function useInfiniteOperationsLog(filters: OperationsLogFilters) {
  return useInfiniteQuery({
    queryKey: ['operationsLog', 'infinite', filters],
    queryFn: ({ pageParam }) =>
      listOperationsLog({
        limit: PAGE_SIZE,
        cursor: pageParam as string | undefined,
        filters,
      }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage, _allPages, lastPageParam) => {
      if (!lastPage.nextCursor) return undefined
      // Guard against a stuck cursor: if the API returns the same cursor
      // it just received, stop paging to prevent an infinite fetch loop.
      if (lastPage.nextCursor === lastPageParam) return undefined
      return lastPage.nextCursor
    },
    select: (data) => {
      // Dedupe entries by id. Defends against a backend glitch where the
      // same row slips into multiple cursor pages (observed with the
      // ReplacingMergeTree FINAL cursor), which would otherwise inflate
      // sidebar counts and trigger more auto-fetches.
      const seen = new Set<string>()
      const entries = []
      for (const page of data.pages) {
        for (const entry of page.entries) {
          if (seen.has(entry.id)) continue
          seen.add(entry.id)
          entries.push(entry)
        }
      }
      // Metrics are returned only on page 1; hold onto that one.
      const metrics = data.pages.find((p) => p.metrics)?.metrics
      return {
        pages: data.pages,
        pageParams: data.pageParams,
        entries,
        metrics,
      }
    },
  })
}
