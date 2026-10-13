import { useQuery } from '@tanstack/react-query'

import { listSecretAuditEvents } from '@/api/endpoints'
import { AdminTable } from '@/components/ui/admin-table'
import { Badge } from '@/components/ui/badge'
import { ErrorBanner } from '@/components/ui/error-banner'
import { RelativeTime } from '@/components/ui/RelativeTime'

import type { SecretAuditEvent } from './types'

const RESULT_VARIANT = {
  allowed: 'success',
  denied: 'danger',
  failed: 'danger',
  succeeded: 'neutral',
} as const

/** The newest 100 audit events, from ClickHouse. */
export function AuditTab({ orgSlug }: { orgSlug: string }) {
  const auditQuery = useQuery({
    queryFn: ({ signal }) => listSecretAuditEvents(orgSlug, signal),
    queryKey: ['secret-audit-events', orgSlug],
  })
  if (auditQuery.error) {
    return (
      <ErrorBanner
        error={auditQuery.error}
        title="Failed to load audit events"
      />
    )
  }
  return (
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
        { header: 'Purpose', key: 'purpose', render: (row) => row.purpose },
        {
          header: 'Resolution',
          key: 'resolution',
          render: (row) => (
            <span className="font-mono text-xs">
              {row.resolution_id.slice(0, 8)}
            </span>
          ),
        },
      ]}
      emptyMessage="No audit events."
      getRowKey={(row) => row.event_id}
      loading={auditQuery.isLoading}
      rows={auditQuery.data ?? []}
    />
  )
}
