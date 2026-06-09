import { useEffect, useMemo, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ExternalLink, RefreshCw } from 'lucide-react'

import { searchProjectIncidents } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { LoadingState } from '@/components/ui/loading-state'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@/components/ui/segmented-control'
import type { IncidentView } from '@/types'

interface IncidentsTabProps {
  orgSlug: string
  projectId: string
}

type RelativeRange = '1d' | '7d' | '30d' | '90d'

const RANGES: { key: RelativeRange; label: string; ms: number }[] = [
  { key: '1d', label: '1d', ms: 24 * 60 * 60_000 },
  { key: '7d', label: '7d', ms: 7 * 24 * 60 * 60_000 },
  { key: '30d', label: '30d', ms: 30 * 24 * 60 * 60_000 },
  { key: '90d', label: '90d', ms: 90 * 24 * 60 * 60_000 },
]

const STATUSES = ['triggered', 'acknowledged', 'resolved'] as const

const URGENCY_CLASS: Record<string, string> = {
  high: 'text-red-600 dark:text-red-400',
  low: 'text-amber-600 dark:text-amber-400',
}

const STATUS_CLASS: Record<string, string> = {
  acknowledged: 'text-amber-600 dark:text-amber-400',
  resolved: 'text-muted-foreground',
  triggered: 'text-red-600 dark:text-red-400',
}

// fallow-ignore-next-line complexity
export function IncidentsTab({ orgSlug, projectId }: IncidentsTabProps) {
  const [range, setRange] = useState<RelativeRange>('7d')
  const [statuses, setStatuses] = useState<Set<string>>(() => new Set(STATUSES))
  // Accumulated rows across "Load more" cursor pages. Reset whenever the
  // filters change (handled by the effect below keyed on filterKey).
  const [accumulated, setAccumulated] = useState<IncidentView[]>([])
  const [cursor, setCursor] = useState<string | undefined>(undefined)

  const filterKey = `${range}|${[...statuses].sort().join(',')}`
  useEffect(() => {
    setAccumulated([])
    setCursor(undefined)
  }, [filterKey])

  const window = useMemo(() => {
    const ms = RANGES.find((r) => r.key === range)?.ms ?? RANGES[1].ms
    const end = new Date()
    return {
      end_time: end.toISOString(),
      start_time: new Date(end.getTime() - ms).toISOString(),
    }
  }, [range])

  const statusList = useMemo(() => [...statuses], [statuses])

  const query = useQuery({
    queryFn: ({ signal }) =>
      searchProjectIncidents(
        orgSlug,
        projectId,
        {
          cursor,
          end_time: window.end_time,
          start_time: window.start_time,
          status:
            statusList.length === STATUSES.length ? undefined : statusList,
        },
        signal,
      ),
    queryKey: ['projectIncidents', orgSlug, projectId, filterKey, cursor ?? ''],
  })

  // Append each fetched page to the accumulator. Keyed on the data
  // object identity so a refetch of the same cursor doesn't double-append.
  useEffect(() => {
    if (!query.data) return
    setAccumulated((prev) =>
      cursor ? [...prev, ...query.data.incidents] : query.data.incidents,
    )
  }, [query.data, cursor])

  const toggleStatus = (status: string) => {
    setStatuses((prev) => {
      const next = new Set(prev)
      if (next.has(status)) next.delete(status)
      else next.add(status)
      // Never allow an empty selection -- treat it as "all".
      return next.size === 0 ? new Set(STATUSES) : next
    })
  }

  const nextCursor = query.data?.next_cursor ?? null

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <SegmentedControl
          onValueChange={(value) => setRange(value as RelativeRange)}
          value={range}
        >
          {RANGES.map((r) => (
            <SegmentedControlItem key={r.key} value={r.key}>
              {r.label}
            </SegmentedControlItem>
          ))}
        </SegmentedControl>
        <div className="flex items-center gap-1">
          {STATUSES.map((status) => (
            <Button
              key={status}
              onClick={() => toggleStatus(status)}
              size="sm"
              variant={statuses.has(status) ? 'secondary' : 'ghost'}
            >
              {status}
            </Button>
          ))}
        </div>
        <Button
          aria-label="Refresh incidents"
          className="ml-auto"
          disabled={query.isFetching}
          onClick={() => void query.refetch()}
          size="sm"
          variant="ghost"
        >
          <RefreshCw
            className={`size-4 ${query.isFetching ? 'animate-spin' : ''}`}
          />
        </Button>
      </div>

      {query.isLoading && accumulated.length === 0 ? (
        <LoadingState label="Loading incidents…" />
      ) : query.isError ? (
        <div className="border-destructive/40 bg-destructive/5 text-destructive flex items-center gap-2 rounded-md border p-4 text-sm">
          <AlertTriangle className="size-4" />
          Failed to load incidents.
        </div>
      ) : accumulated.length === 0 ? (
        <div className="text-muted-foreground rounded-md border p-8 text-center text-sm">
          No incidents in the selected window.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-muted-foreground border-b text-left text-xs uppercase">
              <tr>
                <th className="px-3 py-2 font-medium">Incident</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Urgency</th>
                <th className="px-3 py-2 font-medium">Opened</th>
                <th className="px-3 py-2 font-medium">Resolved</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {accumulated.map((incident) => (
                <IncidentRow incident={incident} key={incident.id} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {nextCursor && (
        <div className="flex justify-center">
          <Button
            disabled={query.isFetching}
            onClick={() => setCursor(nextCursor)}
            size="sm"
            variant="outline"
          >
            Load more
          </Button>
        </div>
      )}
    </div>
  )
}

function formatTimestamp(value: null | string | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString()
}

// fallow-ignore-next-line complexity
function IncidentRow({ incident }: { incident: IncidentView }) {
  return (
    <tr className="hover:bg-muted/40">
      <td className="px-3 py-2">
        <a
          className="text-foreground inline-flex items-center gap-1 hover:text-amber-600 hover:underline hover:dark:text-amber-400"
          href={incident.url}
          rel="noreferrer"
          target="_blank"
        >
          {incident.title || incident.id}
          <ExternalLink className="size-3 opacity-60" />
        </a>
      </td>
      <td className={`px-3 py-2 ${STATUS_CLASS[incident.status] ?? ''}`}>
        {incident.status}
      </td>
      <td
        className={`px-3 py-2 ${URGENCY_CLASS[incident.urgency ?? ''] ?? 'text-muted-foreground'}`}
      >
        {incident.urgency ?? '—'}
      </td>
      <td className="text-muted-foreground px-3 py-2">
        {formatTimestamp(incident.created_at)}
      </td>
      <td className="text-muted-foreground px-3 py-2">
        {formatTimestamp(incident.resolved_at)}
      </td>
    </tr>
  )
}
