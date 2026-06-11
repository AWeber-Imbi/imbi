import { useInfiniteQuery } from '@tanstack/react-query'

import { Button } from '@/components/ui/button'
import { Sk } from '@/components/ui/skeleton'

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
      {isLoading && <ActivityRowsSkeleton rows={6} />}
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
      {isFetchingNextPage && <ActivityRowsSkeleton rows={3} />}
      {hasNextPage && !isFetchingNextPage && (
        <div className="mt-3 flex justify-center">
          <Button onClick={() => fetchNextPage()} size="sm" variant="outline">
            Load more
          </Button>
        </div>
      )}
    </section>
  )
}

function ActivityRowsSkeleton({ rows }: { rows: number }) {
  return (
    <div aria-hidden className="divide-tertiary divide-y">
      {Array.from({ length: rows }).map((_, i) => (
        <div className="flex items-start gap-3 py-2" key={i}>
          <Sk circle h={16} w={16} />
          <div className="flex-1 space-y-1.5">
            <Sk h={14} w="70%" />
            <div className="flex gap-2">
              <Sk h={11} w={60} />
              <Sk h={16} r={2} w={56} />
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
