import { useState } from 'react'

import { Link, useSearchParams } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'

import { listSecretAuditEvents } from '@/api/endpoints'
import { AdminTable } from '@/components/ui/admin-table'
import { Badge } from '@/components/ui/badge'
import { ErrorBanner } from '@/components/ui/error-banner'
import { RelativeTime } from '@/components/ui/RelativeTime'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

import { ResolutionChip } from './controls'
import { AUDIT_CATEGORIES, type SecretAuditEvent } from './types'

const RESULT_VARIANT = {
  allowed: 'success',
  denied: 'danger',
  failed: 'danger',
  succeeded: 'neutral',
} as const

const ALL = 'all'

/**
 * The newest 100 audit events, from ClickHouse: the history. The
 * Resolutions tab shows what is active now. `?resolution=<id>` shows
 * the events of one resolution.
 */
// fallow-ignore-next-line complexity
export function AuditTab({ orgSlug }: { orgSlug: string }) {
  const [params, setParams] = useSearchParams()
  const resolutionId = params.get('resolution') ?? ''
  const [category, setCategory] = useState<string>(ALL)
  const [result, setResult] = useState<string>(ALL)
  const filter = {
    resolution_id: resolutionId,
    result: result === ALL ? '' : result,
    type:
      category === ALL
        ? []
        : [...AUDIT_CATEGORIES[category as keyof typeof AUDIT_CATEGORIES]],
  }
  const auditQuery = useQuery({
    queryFn: ({ signal }) => listSecretAuditEvents(orgSlug, filter, signal),
    queryKey: ['secret-audit-events', orgSlug, filter],
  })

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <FilterSelect
          all="All categories"
          label="Category"
          onChange={setCategory}
          options={Object.keys(AUDIT_CATEGORIES)}
          value={category}
        />
        <FilterSelect
          all="All results"
          label="Result"
          onChange={setResult}
          options={Object.keys(RESULT_VARIANT)}
          value={result}
        />
        {resolutionId && (
          <ResolutionChip
            id={resolutionId}
            onClear={() => setParams({})}
            title="Show the events of all resolutions"
          />
        )}
      </div>
      {auditQuery.error ? (
        <ErrorBanner
          error={auditQuery.error}
          title="Failed to load audit events"
        />
      ) : (
        <AdminTable<SecretAuditEvent>
          columns={[
            {
              header: 'When',
              key: 'at',
              render: (row) => <RelativeTime value={row.at} />,
            },
            {
              header: 'Event',
              key: 'type',
              render: (row) => <span className="font-mono">{row.type}</span>,
            },
            {
              header: 'Result',
              key: 'result',
              render: (row) => (
                <Badge
                  variant={
                    RESULT_VARIANT[row.result as keyof typeof RESULT_VARIANT] ??
                    'neutral'
                  }
                >
                  {row.reason ? `${row.result}: ${row.reason}` : row.result}
                </Badge>
              ),
            },
            { header: 'Actor', key: 'actor', render: (row) => row.actor },
            {
              header: 'Purpose',
              key: 'purpose',
              render: (row) => row.purpose,
            },
            {
              header: 'Resolution',
              interactive: true,
              key: 'resolution',
              render: (row) =>
                row.resolution_id && (
                  <Link
                    className="text-info font-mono text-xs hover:underline"
                    title="Open the resolution"
                    to={`/admin/secrets/resolutions?resolution=${row.resolution_id}`}
                  >
                    {row.resolution_id.slice(0, 8)}
                  </Link>
                ),
            },
          ]}
          emptyMessage="No audit events."
          getRowKey={(row) => row.event_id}
          loading={auditQuery.isLoading}
          rows={auditQuery.data ?? []}
        />
      )}
    </div>
  )
}

function FilterSelect({
  all,
  label,
  onChange,
  options,
  value,
}: {
  all: string
  label: string
  onChange: (value: string) => void
  options: string[]
  value: string
}) {
  return (
    <Select onValueChange={onChange} value={value}>
      <SelectTrigger aria-label={label} className="h-8 w-44">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>{all}</SelectItem>
        {options.map((o) => (
          <SelectItem key={o} value={o}>
            <span className="capitalize">{o}</span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
