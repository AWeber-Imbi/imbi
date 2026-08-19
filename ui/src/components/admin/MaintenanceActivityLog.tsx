import { useState } from 'react'

import { ChevronDown, ChevronRight } from 'lucide-react'

import type {
  MaintenanceDisposition,
  MaintenanceLogEntry,
  MaintenanceOperation,
} from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { RelativeTime } from '@/components/ui/RelativeTime'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@/components/ui/segmented-control'
import { Sk } from '@/components/ui/skeleton'
import { useMaintenanceLog } from '@/hooks/useMaintenanceLog'
import { extractApiErrorDetail } from '@/lib/apiError'

const DISPOSITIONS = [
  'succeeded',
  'skipped',
  'failed',
  'deferred',
] as const satisfies readonly MaintenanceDisposition[]

const BADGE_VARIANT: Record<
  string,
  'danger' | 'info' | 'neutral' | 'success' | 'warning'
> = {
  cancelled: 'neutral',
  completed: 'success',
  deferred: 'info',
  failed: 'danger',
  skipped: 'neutral',
  succeeded: 'success',
}

// The Maintenance page's Activity tab: the durable log of what every
// operation did, newest first. One row per attempt — an operation's own
// activity rows hang off the attempt that produced them, so a run of
// thousands of projects stays readable.
export function MaintenanceActivityLog({
  operations,
}: {
  operations: MaintenanceOperation[]
}) {
  const [disposition, setDisposition] = useState<'' | MaintenanceDisposition>(
    '',
  )
  const [slug, setSlug] = useState('')
  const {
    counts,
    entries,
    error,
    fetchNextPage,
    hasNextPage,
    isError,
    isFetchingNextPage,
    isLoading,
  } = useMaintenanceLog({
    disposition: disposition ? [disposition] : undefined,
    event_type: 'attempt',
    slug: slug || undefined,
  })

  return (
    <div className="space-y-4">
      <p className="text-secondary text-sm">
        What maintenance operations did, kept for 90 days. Each row is one
        project's turn through an operation; expand it for what the operation
        recorded along the way.
      </p>

      <div className="flex flex-wrap items-center gap-3">
        <SegmentedControl
          ariaLabel="Filter by outcome"
          onValueChange={(v) =>
            setDisposition(v === '' ? '' : (v as MaintenanceDisposition))
          }
          value={disposition}
        >
          <SegmentedControlItem value="">All</SegmentedControlItem>
          {DISPOSITIONS.map((value) => (
            <SegmentedControlItem key={value} value={value}>
              {value}
              {counts ? ` ${counts[value]}` : ''}
            </SegmentedControlItem>
          ))}
        </SegmentedControl>

        <select
          aria-label="Filter by operation"
          className="border-secondary bg-primary text-primary rounded-md border px-2 py-1 text-xs"
          onChange={(e) => setSlug(e.target.value)}
          value={slug}
        >
          <option value="">All operations</option>
          {operations.map((op) => (
            <option key={op.slug} value={op.slug}>
              {op.label}
            </option>
          ))}
        </select>
      </div>

      <Card>
        <CardContent className="divide-border/50 divide-y p-0">
          {isError ? (
            <div className="text-destructive py-8 text-center text-sm">
              {extractApiErrorDetail(error) ??
                'Failed to load the maintenance log'}
            </div>
          ) : isLoading ? (
            Array.from({ length: 5 }).map((_, i) => (
              <div className="px-4 py-3" key={`sk-${i}`}>
                <Sk line w="45%" />
              </div>
            ))
          ) : entries.length === 0 ? (
            <div className="text-muted-foreground py-12 text-center text-sm">
              No maintenance activity recorded yet.
            </div>
          ) : (
            entries.map((entry) => <AttemptRow entry={entry} key={entry.id} />)
          )}
        </CardContent>
      </Card>

      {hasNextPage && (
        <div className="flex justify-center">
          <Button
            disabled={isFetchingNextPage}
            onClick={() => void fetchNextPage()}
            size="sm"
            variant="outline"
          >
            {isFetchingNextPage ? 'Loading…' : 'Load more'}
          </Button>
        </div>
      )}
    </div>
  )
}

// Loaded only when an attempt is expanded: the activity rows are far more
// numerous than the attempts, so fetching them up front would trade the
// readable view for a wall of text nobody asked for.
function AttemptDetail({ entry }: { entry: MaintenanceLogEntry }) {
  const {
    entries,
    fetchNextPage,
    hasNextPage,
    isError,
    isFetchingNextPage,
    isLoading,
  } = useMaintenanceLog({
    attempt_id: entry.attempt_id,
    event_type: 'activity',
  })
  const hasDetail = Object.keys(entry.detail).length > 0
  return (
    <div className="text-tertiary mt-2 ml-7 space-y-1 text-xs">
      <div>
        Run {entry.run_id.slice(0, 8)} · {entry.duration_ms} ms
        {entry.started_by ? ` · started by ${entry.started_by}` : ''}
      </div>
      {hasDetail && (
        <pre className="text-secondary overflow-x-auto">
          {JSON.stringify(entry.detail)}
        </pre>
      )}
      {isLoading && <div>Loading activity…</div>}
      {isError && <div className="text-destructive">Failed to load</div>}
      {!isLoading && !isError && entries.length === 0 && (
        <div>This operation recorded no activity for this item.</div>
      )}
      {entries.map((row) => (
        <div className="flex gap-2" key={row.id}>
          <span className="text-secondary w-40 shrink-0 truncate">
            {row.action}
          </span>
          <span className="min-w-0 flex-1 truncate">{row.message}</span>
          <span>{row.disposition}</span>
        </div>
      ))}
      {/* One item can buffer up to MAX_ITEM_ROWS activity rows, well
          past a page, so an attempt that recorded per release needs its
          own way to keep reading. */}
      {hasNextPage && (
        <button
          className="text-amber-text hover:underline disabled:opacity-50"
          disabled={isFetchingNextPage}
          onClick={() => void fetchNextPage()}
          type="button"
        >
          {isFetchingNextPage ? 'Loading…' : 'Load more activity'}
        </button>
      )}
    </div>
  )
}

function AttemptRow({ entry }: { entry: MaintenanceLogEntry }) {
  const [expanded, setExpanded] = useState(false)
  const Chevron = expanded ? ChevronDown : ChevronRight
  return (
    <div className="px-4 py-2.5">
      <button
        aria-expanded={expanded}
        className="flex w-full items-center gap-3 text-left"
        onClick={() => setExpanded((prev) => !prev)}
        type="button"
      >
        <Chevron className="text-tertiary size-3.5 shrink-0" />
        <RelativeTime
          className="text-tertiary w-20 shrink-0 text-xs"
          value={entry.occurred_at}
        />
        <span className="text-primary w-44 shrink-0 truncate text-xs">
          {entry.slug}
        </span>
        <span className="text-secondary w-48 shrink-0 truncate text-xs">
          {entry.project_slug || entry.item_id}
        </span>
        <span className="text-secondary min-w-0 flex-1 truncate text-xs">
          {entry.message}
        </span>
        <Badge
          className="shrink-0 text-xs"
          variant={BADGE_VARIANT[entry.disposition] ?? 'neutral'}
        >
          {entry.disposition}
        </Badge>
      </button>
      {expanded && <AttemptDetail entry={entry} />}
    </div>
  )
}
