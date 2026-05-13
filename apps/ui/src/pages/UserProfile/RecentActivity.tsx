import { useInfiniteQuery } from '@tanstack/react-query'

import { Button } from '@/components/ui/button'

import { ActivityRow } from './ActivityRow'
import { fetchActivity } from './api'
import type { ActivityResponse } from './api'

type ActivityPage = { data: ActivityResponse; nextCursor: null | string }

interface RecentActivityProps {
  email: string
}

export function RecentActivity({ email }: RecentActivityProps) {
  const {
    data,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
  } = useInfiniteQuery<
    ActivityPage,
    Error,
    { pageParams: unknown[]; pages: ActivityPage[] },
    string[],
    string | undefined
  >({
    getNextPageParam: (last) => last.nextCursor ?? undefined,
    initialPageParam: undefined,
    queryFn: ({ pageParam, signal }) =>
      fetchActivity(email, { cursor: pageParam, limit: 20 }, signal),
    queryKey: ['user-activity', email],
  })

  const records = data?.pages.flatMap((p) => p.data.data) ?? []

  return (
    <section className="border-tertiary bg-primary rounded-md border p-4">
      <h2 className="text-primary mb-3 text-sm font-medium">Recent activity</h2>
      {isLoading && <p className="text-tertiary text-xs">Loading…</p>}
      {error && (
        <p className="text-danger text-xs">Failed to load activity feed.</p>
      )}
      {!isLoading && !error && records.length === 0 && (
        <p className="text-tertiary text-xs">No recent activity.</p>
      )}
      <ul className="divide-tertiary divide-y">
        {records.map((record) => (
          <li key={`${record.source}-${record.id}`}>
            <ActivityRow record={record} />
          </li>
        ))}
      </ul>
      {hasNextPage && (
        <div className="mt-3 flex justify-center">
          <Button
            disabled={isFetchingNextPage}
            onClick={() => fetchNextPage()}
            size="sm"
            variant="outline"
          >
            {isFetchingNextPage ? 'Loading…' : 'Load more'}
          </Button>
        </div>
      )}
    </section>
  )
}
