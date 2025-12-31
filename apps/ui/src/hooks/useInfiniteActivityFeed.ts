import { useInfiniteQuery } from '@tanstack/react-query'
import axios from 'axios'
import type { ActivityFeedEntry } from '@/types'

interface ActivityFeedResponse {
  data: ActivityFeedEntry[]
  nextToken?: string
}

function parseLinkHeader(linkHeader: string | null): string | undefined {
  if (!linkHeader) return undefined

  // Parse Link header: <url>; rel="next"
  const nextMatch = linkHeader.match(/<([^>]+)>;\s*rel="next"/)
  if (!nextMatch) return undefined

  // Extract token parameter from URL
  const url = new URL(nextMatch[1], window.location.origin)
  return url.searchParams.get('token') || undefined
}

async function fetchActivityFeed({ pageParam }: { pageParam?: string }): Promise<ActivityFeedResponse> {
  try {
    const params: Record<string, unknown> = { limit: 20 }
    if (pageParam) {
      params.token = pageParam
    }

    const API_BASE_URL = import.meta.env.VITE_API_URL || '/api'
    const response = await axios.get<ActivityFeedEntry[]>(`${API_BASE_URL}/activity-feed`, {
      params,
      withCredentials: true,
    })

    const data = Array.isArray(response.data) ? response.data : []
    const nextToken = parseLinkHeader(response.headers.link)

    console.log('[Infinite Activity] Fetched', data.length, 'items, next token:', nextToken)

    return {
      data,
      nextToken,
    }
  } catch (error) {
    console.error('[API] Activity feed error:', error)
    return { data: [] }
  }
}

export function useInfiniteActivityFeed() {
  return useInfiniteQuery({
    queryKey: ['activityFeed', 'infinite'],
    queryFn: fetchActivityFeed,
    initialPageParam: undefined,
    getNextPageParam: (lastPage) => lastPage.nextToken,
    select: (data) => ({
      pages: data.pages,
      pageParams: data.pageParams,
      // Flatten all pages into a single array
      activities: data.pages.flatMap(page => page.data),
    }),
  })
}
