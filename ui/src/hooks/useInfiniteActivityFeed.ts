import { useInfiniteQuery } from '@tanstack/react-query'

import { apiClient } from '@/api/client'
import type { ActivityFeedEntry } from '@/types'

interface ActivityFeedResponse {
  data: ActivityFeedEntry[]
  nextToken?: string
}

export function useInfiniteActivityFeed(orgSlug: string) {
  return useInfiniteQuery({
    enabled: Boolean(orgSlug),
    getNextPageParam: (lastPage) => lastPage.nextToken,
    initialPageParam: undefined,
    queryFn: fetchActivityFeed,
    queryKey: ['activityFeed', 'infinite', orgSlug],
    select: (data) => ({
      // Flatten all pages into a single array
      activities: data.pages.flatMap((page) => page.data),
      pageParams: data.pageParams,
      pages: data.pages,
    }),
  })
}

async function fetchActivityFeed({
  pageParam,
  signal,
}: {
  pageParam?: string
  signal?: AbortSignal
}): Promise<ActivityFeedResponse> {
  try {
    const params: Record<string, unknown> = { limit: 20 }
    if (pageParam) {
      params.token = pageParam
    }

    const { data, headers } = await apiClient.getWithHeaders<
      ActivityFeedEntry[]
    >('/activity-feed', params, signal)

    const items = Array.isArray(data) ? data : []
    const nextToken = parseLinkHeader(headers)

    console.log(
      '[Infinite Activity] Fetched',
      items.length,
      'items, next token:',
      nextToken,
    )

    return {
      data: items,
      nextToken,
    }
  } catch (error) {
    if (signal?.aborted) {
      throw error
    }
    console.error('[API] Activity feed error:', error)
    return { data: [] }
  }
}

function parseLinkHeader(headers: Headers): string | undefined {
  const linkHeader = headers.get('link')
  if (!linkHeader) return undefined

  // Parse Link header: <url>; rel="next"
  const nextMatch = linkHeader.match(/<([^>]+)>;\s*rel="next"/)
  if (!nextMatch) return undefined

  // Extract token parameter from URL
  const url = new URL(nextMatch[1], window.location.origin)
  return url.searchParams.get('token') || undefined
}
