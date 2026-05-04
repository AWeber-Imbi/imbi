import { useCallback, useEffect, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { RefreshCw, Search } from 'lucide-react'

import {
  getLogSchema,
  listProjectPlugins,
  searchProjectLogs,
} from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { LoadingState } from '@/components/ui/loading-state'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { LogEntryResponse } from '@/types'

interface LogsTabProps {
  environment?: string
  orgSlug: string
  projectId: string
}

type RelativeRange = '1h' | '6h' | '15m' | '24h' | '30m'

const RELATIVE_RANGES: { label: string; value: RelativeRange }[] = [
  { label: 'Last 15 min', value: '15m' },
  { label: 'Last 30 min', value: '30m' },
  { label: 'Last 1 hour', value: '1h' },
  { label: 'Last 6 hours', value: '6h' },
  { label: 'Last 24 hours', value: '24h' },
]

export function LogsTab({ environment, orgSlug, projectId }: LogsTabProps) {
  const [source, setSource] = useState<string | undefined>()
  const [range, setRange] = useState<RelativeRange>('30m')
  const [filterField, setFilterField] = useState('')
  const [filterOp, setFilterOp] = useState('eq')
  const [filterValue, setFilterValue] = useState('')
  const [activeFilters, setActiveFilters] = useState<string[]>([])
  const [cursor, setCursor] = useState<null | string>(null)
  const [allEntries, setAllEntries] = useState<LogEntryResponse[]>([])

  const { data: assignments } = useQuery({
    queryFn: ({ signal }) => listProjectPlugins(orgSlug, projectId, signal),
    queryKey: ['project-plugins', orgSlug, projectId],
    staleTime: 5 * 60 * 1000,
  })

  const logAssignments = assignments?.filter((a) => a.tab === 'logs') ?? []
  const sources = logAssignments.map((a) => ({
    id: a.plugin_id,
    label: a.label,
  }))
  const activeSource = source ?? sources[0]?.id

  const { data: schema } = useQuery({
    enabled: sources.length > 0 && !!activeSource,
    queryFn: ({ signal }) =>
      getLogSchema(
        orgSlug,
        projectId,
        { environment: environment ?? undefined, source: activeSource },
        signal,
      ),
    queryKey: ['log-schema', orgSlug, projectId, activeSource, environment],
    staleTime: 10 * 60 * 1000,
  })

  const datetimes = rangeToDatetimes(range)

  const {
    data: logResult,
    isFetching,
    refetch,
  } = useQuery({
    enabled: sources.length > 0 && !!activeSource,
    queryFn: ({ signal }) =>
      searchProjectLogs(
        orgSlug,
        projectId,
        {
          cursor: cursor ?? undefined,
          end_time: datetimes.end,
          environment: environment ?? undefined,
          filter: activeFilters.length ? activeFilters : undefined,
          limit: 100,
          source: activeSource,
          start_time: datetimes.start,
        },
        signal,
      ),
    queryKey: [
      'project-logs',
      orgSlug,
      projectId,
      activeSource,
      environment,
      range,
      activeFilters,
      cursor,
    ],
    staleTime: 0,
  })

  useEffect(() => {
    setAllEntries([])
    setCursor(null)
  }, [activeSource, environment, range, activeFilters])

  const handleSearch = useCallback(() => {
    setAllEntries([])
    setCursor(null)
    void refetch()
  }, [refetch])

  const handleLoadMore = useCallback(() => {
    if (logResult?.next_cursor) {
      setCursor(logResult.next_cursor)
      setAllEntries((prev) => [...prev, ...(logResult.entries ?? [])])
    }
  }, [logResult])

  const addFilter = () => {
    if (filterField && filterValue) {
      const f = `${filterField}:${filterOp}:${filterValue}`
      setActiveFilters((prev) => [...prev, f])
      setFilterField('')
      setFilterValue('')
    }
  }

  const removeFilter = (idx: number) => {
    setActiveFilters((prev) => prev.filter((_, i) => i !== idx))
  }

  const displayEntries =
    allEntries.length > 0
      ? [...allEntries, ...(logResult?.entries ?? [])]
      : (logResult?.entries ?? [])

  if (sources.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <CardTitle className="mb-2">No Logs Plugin</CardTitle>
          <p className="text-sm text-secondary">
            No logs plugin is assigned to this project. Configure plugins on the
            project type or in project settings.
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      {/* Source picker */}
      {sources.length > 1 && (
        <div className="flex items-center gap-3">
          <span className="text-sm text-secondary">Source:</span>
          <div className="flex gap-2">
            {sources.map((s) => (
              <Button
                className={
                  activeSource === s.id
                    ? 'bg-amber-bg text-amber-text hover:bg-amber-bg'
                    : ''
                }
                key={s.id}
                onClick={() => setSource(s.id)}
                size="sm"
                variant="outline"
              >
                {s.label}
              </Button>
            ))}
          </div>
        </div>
      )}

      {/* Controls */}
      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 p-4">
          {/* Time range */}
          <div className="space-y-1">
            <Label className="text-xs">Time Range</Label>
            <Select
              onValueChange={(v) => setRange(v as RelativeRange)}
              value={range}
            >
              <SelectTrigger className="h-8 w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {RELATIVE_RANGES.map((r) => (
                  <SelectItem key={r.value} value={r.value}>
                    {r.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Filter builder */}
          {schema && schema.length > 0 && (
            <>
              <div className="space-y-1">
                <Label className="text-xs">Filter Field</Label>
                <Select onValueChange={setFilterField} value={filterField}>
                  <SelectTrigger className="h-8 w-44">
                    <SelectValue placeholder="Field…" />
                  </SelectTrigger>
                  <SelectContent>
                    {schema.map((f) => (
                      <SelectItem key={f.name} value={f.name}>
                        {f.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Op</Label>
                <Select onValueChange={setFilterOp} value={filterOp}>
                  <SelectTrigger className="h-8 w-28">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {['eq', 'ne', 'contains', 'starts_with', 'regex'].map(
                      (op) => (
                        <SelectItem key={op} value={op}>
                          {op}
                        </SelectItem>
                      ),
                    )}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Value</Label>
                <Input
                  className="h-8 w-48"
                  onChange={(e) => setFilterValue(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && addFilter()}
                  placeholder="value"
                  value={filterValue}
                />
              </div>
              <Button
                className="h-8"
                disabled={!filterField || !filterValue}
                onClick={addFilter}
                size="sm"
                variant="outline"
              >
                Add Filter
              </Button>
            </>
          )}

          <Button className="h-8" onClick={handleSearch} size="sm">
            <Search className="mr-1 h-3 w-3" />
            Search
          </Button>
          <Button
            className="h-8"
            disabled={isFetching}
            onClick={() => void refetch()}
            size="icon"
            variant="outline"
          >
            <RefreshCw
              className={`h-3 w-3 ${isFetching ? 'animate-spin' : ''}`}
            />
          </Button>
        </CardContent>

        {/* Active filters */}
        {activeFilters.length > 0 && (
          <CardContent className="border-t px-4 pb-3 pt-2">
            <div className="flex flex-wrap gap-2">
              {activeFilters.map((f, i) => (
                <Badge
                  className="cursor-pointer gap-1"
                  key={i}
                  onClick={() => removeFilter(i)}
                  variant="secondary"
                >
                  {f} ✕
                </Badge>
              ))}
            </div>
          </CardContent>
        )}
      </Card>

      {/* Log entries */}
      <Card>
        <CardHeader className="px-6 py-4">
          <CardTitle className="flex items-center justify-between">
            <span>Log Entries</span>
            {logResult?.total != null && (
              <span className="text-sm font-normal text-secondary">
                {logResult.total.toLocaleString()} total
              </span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {isFetching && displayEntries.length === 0 ? (
            <LoadingState label="Loading..." />
          ) : displayEntries.length === 0 ? (
            <div className="py-8 text-center text-sm text-secondary">
              No log entries found for the selected time range
            </div>
          ) : (
            <div className="divide-y divide-border">
              {displayEntries.map((entry, i) => (
                <div className="px-6 py-3" key={i}>
                  <div className="flex items-start gap-3">
                    <span className="shrink-0 font-mono text-xs text-secondary">
                      {new Date(entry.timestamp).toLocaleTimeString()}
                    </span>
                    {entry.level && (
                      <Badge
                        className="shrink-0"
                        variant={levelBadgeVariant(entry.level)}
                      >
                        {entry.level}
                      </Badge>
                    )}
                    <span className="min-w-0 flex-1 break-all font-mono text-sm">
                      {entry.message}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
          {logResult?.next_cursor && !isFetching && (
            <div className="px-6 py-4">
              <Button
                className="w-full"
                onClick={handleLoadMore}
                variant="outline"
              >
                Load Older
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function levelBadgeVariant(
  level: null | string,
): 'default' | 'destructive' | 'secondary' | 'warning' {
  switch (level?.toLowerCase()) {
    case 'debug':
      return 'secondary'
    case 'error':
    case 'fatal':
      return 'destructive'
    case 'warn':
    case 'warning':
      return 'warning'
    default:
      return 'default'
  }
}

function rangeToDatetimes(range: RelativeRange): {
  end: string
  start: string
} {
  const end = new Date()
  const start = new Date(end)
  switch (range) {
    case '1h':
      start.setHours(start.getHours() - 1)
      break
    case '6h':
      start.setHours(start.getHours() - 6)
      break
    case '15m':
      start.setMinutes(start.getMinutes() - 15)
      break
    case '24h':
      start.setHours(start.getHours() - 24)
      break
    case '30m':
      start.setMinutes(start.getMinutes() - 30)
      break
  }
  return { end: end.toISOString(), start: start.toISOString() }
}
