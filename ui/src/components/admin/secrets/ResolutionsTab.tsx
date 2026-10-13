import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  listSecretResolutions,
  releaseSecretResolution,
  revokeSecretProviderLease,
} from '@/api/endpoints'
import { AdminTable } from '@/components/ui/admin-table'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { extractApiErrorDetail } from '@/lib/apiError'

import type { SecretResolution } from './types'

const onError = (err: unknown) => toast.error(extractApiErrorDetail(err))

const STATE_VARIANT = {
  active: 'info',
  expired: 'neutral',
  failed: 'danger',
  released: 'neutral',
} as const

/** Resolutions, newest first. No handle or lease id is ever shown. */
// fallow-ignore-next-line complexity
export function ResolutionsTab({ orgSlug }: { orgSlug: string }) {
  const queryClient = useQueryClient()
  const queryKey = ['secret-resolutions', orgSlug]
  const resolutionsQuery = useQuery({
    queryFn: ({ signal }) => listSecretResolutions(orgSlug, undefined, signal),
    queryKey,
  })
  const refresh = () => queryClient.invalidateQueries({ queryKey })
  const releaseMutation = useMutation({
    mutationFn: (id: string) => releaseSecretResolution(orgSlug, id),
    onError,
    onSuccess: refresh,
  })
  const revokeMutation = useMutation({
    mutationFn: (id: string) => revokeSecretProviderLease(orgSlug, id),
    onError: (err: unknown) => {
      onError(err)
      void refresh()
    },
    onSuccess: refresh,
  })

  return (
    <AdminTable<SecretResolution>
      actions={(row) => (
        <div className="flex gap-2">
          {row.state === 'active' && (
            <Button
              disabled={releaseMutation.isPending}
              onClick={() => releaseMutation.mutate(row.id)}
              size="sm"
              variant="outline"
            >
              Release
            </Button>
          )}
          {['failed', 'pending'].includes(
            row.provider_lease.revocation_state,
          ) && (
            <Button
              disabled={revokeMutation.isPending}
              onClick={() => revokeMutation.mutate(row.id)}
              size="sm"
              variant="outline"
            >
              Revoke lease
            </Button>
          )}
        </div>
      )}
      columns={[
        {
          header: 'Reference',
          key: 'reference',
          render: (row) => (
            <span className="font-mono text-xs">{row.reference}</span>
          ),
        },
        { header: 'Purpose', key: 'purpose', render: (row) => row.purpose },
        { header: 'Agent', key: 'agent', render: (row) => row.agent_id },
        {
          header: 'Delivery',
          key: 'delivery',
          render: (row) =>
            row.delivery_target
              ? `${row.delivery_mode}: ${row.delivery_target}`
              : row.delivery_mode,
        },
        {
          header: 'State',
          key: 'state',
          render: (row) => (
            <Badge
              variant={
                STATE_VARIANT[row.state as keyof typeof STATE_VARIANT] ??
                'neutral'
              }
            >
              {row.failure_reason ?? row.state}
            </Badge>
          ),
        },
        {
          header: 'Lease',
          key: 'lease',
          render: (row) =>
            row.provider_lease.revocation_state === 'not_applicable' ? (
              <span className="text-tertiary">None</span>
            ) : (
              <Badge
                variant={
                  row.provider_lease.revocation_state === 'failed'
                    ? 'danger'
                    : 'neutral'
                }
              >
                {row.provider_lease.revocation_state}
              </Badge>
            ),
        },
        {
          cellAlign: 'right',
          header: 'Used',
          headerAlign: 'right',
          key: 'used',
          render: (row) =>
            `${row.materialization_count}/${row.materialization_limit}`,
        },
        {
          header: 'Created',
          key: 'created',
          render: (row) => <RelativeTime value={row.created_at} />,
        },
        {
          header: 'Expires',
          key: 'expires',
          render: (row) => <RelativeTime value={row.expires_at} />,
        },
      ]}
      emptyMessage="No secret resolutions."
      getRowKey={(row) => row.id}
      loading={resolutionsQuery.isLoading}
      rows={resolutionsQuery.data ?? []}
    />
  )
}
