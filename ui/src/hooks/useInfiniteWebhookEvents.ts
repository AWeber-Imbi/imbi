import { type InfiniteData, useInfiniteQuery } from '@tanstack/react-query'

import {
  type AdminEventsFilters,
  type EventRecord,
  type EventsPage,
  listAdminEvents,
} from '@/api/endpoints'

const PAGE_SIZE = 100

interface SelectedWebhookEventsData {
  entries: EventRecord[]
  pageParams: Array<string | undefined>
  pages: EventsPage[]
}

/**
 * Paginated webhook-history feed for the admin view. Reads the
 * coalesced `events_latest` projection on the server side, so each
 * event id appears at most once (with its highest-version metadata).
 */
export function useInfiniteWebhookEvents(filters: AdminEventsFilters) {
  return useInfiniteQuery<
    EventsPage,
    Error,
    SelectedWebhookEventsData,
    readonly unknown[],
    string | undefined
  >({
    getNextPageParam: (lastPage, _allPages, lastPageParam) => {
      if (!lastPage.nextCursor) return undefined
      if (lastPage.nextCursor === lastPageParam) return undefined
      return lastPage.nextCursor
    },
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) =>
      listAdminEvents(
        {
          cursor: pageParam as string | undefined,
          filters,
          limit: PAGE_SIZE,
        },
        signal,
      ),
    queryKey: ['webhookEvents', 'infinite', filters],
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
