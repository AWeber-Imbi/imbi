import { type InfiniteData, useInfiniteQuery } from '@tanstack/react-query'

import {
  type EventRecord,
  type EventsPage,
  listProjectEvents,
} from '@/api/endpoints'

const PAGE_SIZE = 100

interface SelectedEventsData {
  entries: EventRecord[]
  pageParams: Array<string | undefined>
  pages: EventsPage[]
}

export function useInfiniteProjectEvents(
  orgSlug: string,
  projectId: string,
  type?: string,
) {
  return useInfiniteQuery<
    EventsPage,
    Error,
    SelectedEventsData,
    readonly unknown[],
    string | undefined
  >({
    enabled: Boolean(orgSlug) && Boolean(projectId),
    getNextPageParam: (lastPage, _allPages, lastPageParam) => {
      if (!lastPage.nextCursor) return undefined
      if (lastPage.nextCursor === lastPageParam) return undefined
      return lastPage.nextCursor
    },
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) =>
      listProjectEvents(
        {
          cursor: pageParam as string | undefined,
          limit: PAGE_SIZE,
          orgSlug,
          projectId,
          type,
        },
        signal,
      ),
    queryKey: ['events', 'infinite', orgSlug, projectId, type],
    select: (data: InfiniteData<EventsPage, string | undefined>) => {
      const seen = new Set<string>()
      const entries: EventRecord[] = []
      for (const page of data.pages) {
        for (const entry of page.entries) {
          if (seen.has(entry.id)) continue
          seen.add(entry.id)
          entries.push(entry)
        }
      }
      return {
        entries,
        pageParams: data.pageParams,
        pages: data.pages,
      }
    },
  })
}
