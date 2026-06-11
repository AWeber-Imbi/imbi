import { useMemo, useState } from 'react'

import type { AdminEventsFilters, EventRecord } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { ErrorBanner } from '@/components/ui/error-banner'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Sk } from '@/components/ui/skeleton'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useInfiniteWebhookEvents } from '@/hooks/useInfiniteWebhookEvents'
import { useProjectsSlimMap } from '@/hooks/useProjectsSlimMap'
import { useWebhookEvent } from '@/hooks/useWebhookEvent'

import { WebhookHistoryRow } from './WebhookHistoryRow'

const TIME_RANGES = [
  { label: 'Last 24 hours', value: '24h' },
  { label: 'Last 7 days', value: '7d' },
  { label: 'Last 30 days', value: '30d' },
  { label: 'All time', value: 'all' },
] as const

type TimeRange = (typeof TIME_RANGES)[number]['value']

interface WebhookHistoryProps {
  eventId?: string
}

// fallow-ignore-next-line complexity
export function WebhookHistory({ eventId }: WebhookHistoryProps) {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''
  const { projectsById } = useProjectsSlimMap(orgSlug)

  const [tps, setTps] = useState('')
  const [eventType, setEventType] = useState('')
  const [projectId, setProjectId] = useState('')
  const [timeRange, setTimeRange] = useState<TimeRange>('7d')

  // fallow-ignore-next-line complexity
  const filters: AdminEventsFilters = useMemo(() => {
    // Always scope to the webhook category. The gateway records every
    // inbound delivery with `type='webhook'`; the per-source label
    // (e.g. `pull_request`) sits in `metadata.event_type` and the API
    // exposes that as the `event_type` query parameter.
    const f: AdminEventsFilters = { type: 'webhook' }
    if (tps) f.third_party_service = tps
    if (eventType) f.event_type = eventType
    if (projectId) f.project_id = projectId
    const since = sinceFromRange(timeRange)
    if (since) f.since = since
    return f
  }, [tps, eventType, projectId, timeRange])

  const {
    data,
    error,
    fetchNextPage,
    hasNextPage,
    isFetching,
    isFetchingNextPage,
    isLoading,
  } = useInfiniteWebhookEvents(filters)

  const pinnedQuery = useWebhookEvent(eventId)

  // fallow-ignore-next-line complexity
  const tpsOptions = useMemo(() => {
    const set = new Set<string>()
    for (const e of data?.entries ?? []) {
      if (e.third_party_service) set.add(e.third_party_service)
    }
    return Array.from(set).sort()
  }, [data?.entries])

  const projectLabel = (event: EventRecord) =>
    projectsById.get(event.project_id)?.slug ?? event.project_id

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-40">
          <label className="text-secondary mb-1 block text-xs" htmlFor="wh-tps">
            Third-party service
          </label>
          <Select
            onValueChange={(v) => setTps(v === '__all' ? '' : v)}
            value={tps || '__all'}
          >
            <SelectTrigger className="h-8" id="wh-tps">
              <SelectValue placeholder="All services" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all">All services</SelectItem>
              {tpsOptions.map((slug) => (
                <SelectItem key={slug} value={slug}>
                  {slug}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="min-w-40">
          <label
            className="text-secondary mb-1 block text-xs"
            htmlFor="wh-type"
          >
            Event type
          </label>
          <Input
            className="h-8"
            id="wh-type"
            onChange={(e) => setEventType(e.target.value)}
            placeholder="e.g. pull_request"
            value={eventType}
          />
        </div>
        <div className="min-w-40">
          <label
            className="text-secondary mb-1 block text-xs"
            htmlFor="wh-project"
          >
            Project
          </label>
          <Select
            onValueChange={(v) => setProjectId(v === '__all' ? '' : v)}
            value={projectId || '__all'}
          >
            <SelectTrigger className="h-8" id="wh-project">
              <SelectValue placeholder="All projects" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all">All projects</SelectItem>
              {Array.from(projectsById.values())
                .sort((a, b) => a.slug.localeCompare(b.slug))
                .map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.slug}
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>
        </div>
        <div className="min-w-35">
          <label
            className="text-secondary mb-1 block text-xs"
            htmlFor="wh-range"
          >
            Time range
          </label>
          <Select
            onValueChange={(v) => setTimeRange(v as TimeRange)}
            value={timeRange}
          >
            <SelectTrigger className="h-8" id="wh-range">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {TIME_RANGES.map((r) => (
                <SelectItem key={r.value} value={r.value}>
                  {r.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {pinnedQuery.data ? (
        <div className="space-y-2">
          <div className="text-secondary text-xs font-medium uppercase">
            Pinned event
          </div>
          <WebhookHistoryRow
            defaultOpen
            event={pinnedQuery.data}
            projectLabel={projectLabel(pinnedQuery.data)}
          />
        </div>
      ) : null}
      {eventId && pinnedQuery.isError ? (
        <ErrorBanner
          error={pinnedQuery.error}
          title={`Could not load event ${eventId}`}
        />
      ) : null}

      {isLoading ? (
        <WebhookHistorySkeleton />
      ) : error ? (
        <ErrorBanner error={error} title="Failed to load webhook events" />
      ) : (
        <div className="space-y-2">
          {(data?.entries ?? []).length === 0 ? (
            <div className="text-secondary py-12 text-center text-sm">
              No webhook events match the current filters.
            </div>
          ) : (
            (data?.entries ?? []).map((event) => (
              <WebhookHistoryRow
                event={event}
                key={event.id}
                projectLabel={projectLabel(event)}
              />
            ))
          )}
          <div className="flex justify-center pt-2">
            {hasNextPage ? (
              <Button
                disabled={isFetchingNextPage}
                onClick={() => void fetchNextPage()}
                size="sm"
                variant="outline"
              >
                {isFetchingNextPage ? 'Loading...' : 'Load more'}
              </Button>
            ) : isFetching ? (
              <span className="text-secondary text-xs">Refreshing...</span>
            ) : null}
          </div>
        </div>
      )}
    </div>
  )
}

function sinceFromRange(range: TimeRange): string | undefined {
  if (range === 'all') return undefined
  const now = Date.now()
  const ms =
    range === '24h'
      ? 24 * 60 * 60 * 1000
      : range === '7d'
        ? 7 * 24 * 60 * 60 * 1000
        : 30 * 24 * 60 * 60 * 1000
  return new Date(now - ms).toISOString()
}

function WebhookHistorySkeleton() {
  return (
    <div className="space-y-2">
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <div
          className="flex items-center gap-3 rounded-md border border-slate-200 bg-white px-4 py-3"
          key={i}
        >
          <Sk circle h={16} w={16} />
          <Sk line w={150} />
          <Sk h={18} r={4} w={70} />
          <Sk line w={110} />
          <Sk line w={90} />
          <Sk className="ml-auto" h={18} r={4} w={100} />
        </div>
      ))}
    </div>
  )
}
