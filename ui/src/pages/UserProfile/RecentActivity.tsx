import { useMemo, useState } from 'react'

import { useInfiniteQuery } from '@tanstack/react-query'
import { Activity, ChevronRight } from 'lucide-react'

import { ACTIVITY_GROUP_WINDOW_MS } from '@/components/activityFeed/entryAdapters'
import { clusterConsecutive } from '@/components/activityFeed/grouping'
import type { ActivityCluster } from '@/components/activityFeed/grouping'
import { Button } from '@/components/ui/button'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { Sk } from '@/components/ui/skeleton'

import { ActivityRow } from './ActivityRow'
import { fetchActivity } from './api'
import type { ActivityRecord, ActivityResponse } from './api'

type ActivityPage = { data: ActivityResponse; nextCursor: null | string }

interface RecentActivityProps {
  email: string
}

// fallow-ignore-next-line complexity
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

  const records = useMemo(
    () => data?.pages.flatMap((p) => p.data.data) ?? [],
    [data],
  )

  // Single-user feed: cluster consecutive same-source+type bursts (e.g. a run
  // of deploys) into one collapsible group, mirroring the dashboard grouping.
  const clusters = useMemo(
    () =>
      clusterConsecutive(records, {
        keyOf: (r) => `${r.source}|${r.type}|${r.project_slug ?? ''}`,
        timeOf: (r) => {
          const ms = Date.parse(r.occurred_at)
          return Number.isFinite(ms) ? ms : 0
        },
        windowMs: ACTIVITY_GROUP_WINDOW_MS,
      }),
    [records],
  )

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
      <ClusterList clusters={clusters} />
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

function ActivityGroup({
  cluster,
}: {
  cluster: ActivityCluster<ActivityRecord>
}) {
  const [open, setOpen] = useState(false)
  const lead = cluster.items[0]
  return (
    <div className="py-2">
      <button
        aria-expanded={open}
        className="hover:bg-secondary flex w-full items-start gap-3 rounded-sm text-left"
        onClick={() => setOpen((v) => !v)}
        type="button"
      >
        <span className="text-tertiary mt-0.5 shrink-0">
          <Activity className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-primary text-sm">
            {cluster.items.length} {lead.type} activities
          </p>
          <p className="text-tertiary mt-0.5 flex flex-wrap items-center gap-2 text-xs">
            <RelativeTime
              tooltip={false}
              value={new Date(cluster.newest).toISOString()}
            />
            <span className="border-tertiary rounded-sm border px-1.5 py-0.5">
              {lead.type}
            </span>
          </p>
        </div>
        <ChevronRight
          className="text-tertiary mt-0.5 size-4 shrink-0 transition-transform"
          style={{ transform: open ? 'rotate(90deg)' : 'none' }}
        />
      </button>
      {open && (
        <ul className="divide-tertiary border-tertiary mt-1 ml-7 divide-y border-l pl-3">
          {cluster.items.map((record) => (
            <li key={rowKey(record)}>
              <ActivityRow record={record} />
            </li>
          ))}
        </ul>
      )}
    </div>
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

function ClusterList({
  clusters,
}: {
  clusters: ActivityCluster<ActivityRecord>[]
}) {
  return (
    <ul className="divide-tertiary divide-y">
      {clusters.map((cluster) =>
        cluster.items.length === 1 ? (
          <li key={rowKey(cluster.items[0])}>
            <ActivityRow record={cluster.items[0]} />
          </li>
        ) : (
          <li key={cluster.key}>
            <ActivityGroup cluster={cluster} />
          </li>
        ),
      )}
    </ul>
  )
}

function rowKey(record: ActivityRecord): string {
  return `${record.source}-${record.id}`
}
