import { type InfiniteData, useInfiniteQuery } from '@tanstack/react-query'

import {
  listOperationsLog,
  type OperationsLogMetrics,
  type OperationsLogPage,
} from '@/api/endpoints'
import type { OperationsLogFilters, OperationsLogRecord } from '@/types'

const PAGE_SIZE = 200

interface SelectedOperationsLogData {
  entries: OperationsLogRecord[]
  metrics?: OperationsLogMetrics
  pageParams: Array<string | undefined>
  pages: OperationsLogPage[]
}

export function useInfiniteOperationsLog(
  orgSlug: string,
  filters: OperationsLogFilters,
) {
  return useInfiniteQuery<
    OperationsLogPage,
    Error,
    SelectedOperationsLogData,
    readonly unknown[],
    string | undefined
  >({
    enabled: Boolean(orgSlug),
    getNextPageParam: (lastPage, _allPages, lastPageParam) => {
      if (!lastPage.nextCursor) return undefined
      // Guard against a stuck cursor: if the API returns the same cursor
      // it just received, stop paging to prevent an infinite fetch loop.
      if (lastPage.nextCursor === lastPageParam) return undefined
      return lastPage.nextCursor
    },
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) =>
      listOperationsLog(
        {
          cursor: pageParam as string | undefined,
          filters,
          limit: PAGE_SIZE,
        },
        signal,
      ),
    queryKey: ['operationsLog', 'infinite', orgSlug, filters],
    select: (data: InfiniteData<OperationsLogPage, string | undefined>) => {
      // Dedupe entries by id. Defends against a backend glitch where the
      // same row slips into multiple cursor pages (observed with the
      // ReplacingMergeTree FINAL cursor), which would otherwise inflate
      // sidebar counts and trigger more auto-fetches.
      const seen = new Set<string>()
      const entries: OperationsLogRecord[] = []
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
        entries,
        metrics,
        pageParams: data.pageParams,
        pages: data.pages,
      }
    },
  })
}
