import { useState } from 'react'

import { Link, useSearchParams } from 'react-router-dom'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  getSecretResolution,
  listSecretResolutions,
  releaseSecretResolution,
  revokeSecretProviderLease,
} from '@/api/endpoints'
import { AdminTable } from '@/components/ui/admin-table'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { RelativeTime } from '@/components/ui/RelativeTime'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@/components/ui/segmented-control'
import { extractApiErrorDetail } from '@/lib/apiError'

import type { SecretResolution } from './types'

const onError = (err: unknown) => toast.error(extractApiErrorDetail(err))

const STATES = ['active', 'released', 'expired', 'failed'] as const

const STATE_VARIANT = {
  active: 'info',
  expired: 'neutral',
  failed: 'danger',
  released: 'neutral',
} as const

/**
 * Resolutions, newest first: what is active now, Active by default. The
 * Audit tab has the history. `?resolution=<id>` shows one resolution.
 * No handle or lease id is ever shown.
 */
// fallow-ignore-next-line complexity
export function ResolutionsTab({ orgSlug }: { orgSlug: string }) {
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const resolutionId = params.get('resolution') ?? ''
  const [state, setState] = useState<string>('active')
  const queryKey = ['secret-resolutions', orgSlug]
  const resolutionsQuery = useQuery({
    queryFn: ({ signal }) =>
      resolutionId
        ? getSecretResolution(orgSlug, resolutionId, signal).then((r) => [r])
        : listSecretResolutions(
            orgSlug,
            state === 'all' ? undefined : state,
            signal,
          ),
    queryKey: [...queryKey, resolutionId || state],
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
    <div className="space-y-4">
      {resolutionId ? (
        <Button
          onClick={() => setParams({})}
          size="sm"
          title="Show all resolutions"
          variant="outline"
        >
          Resolution{' '}
          <span className="font-mono">{resolutionId.slice(0, 8)}</span> ×
        </Button>
      ) : (
        <SegmentedControl
          ariaLabel="State"
          onValueChange={setState}
          value={state}
        >
          {[...STATES, 'all'].map((s) => (
            <SegmentedControlItem key={s} value={s}>
              {s[0].toUpperCase() + s.slice(1)}
            </SegmentedControlItem>
          ))}
        </SegmentedControl>
      )}
      <AdminTable<SecretResolution>
        actions={(row) => (
          <div className="flex gap-2">
            <Button asChild size="sm" variant="outline">
              <Link to={`/admin/secrets/audit?resolution=${row.id}`}>
                History
              </Link>
            </Button>
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
        emptyMessage={
          state === 'active' && !resolutionId
            ? 'No active secret resolutions.'
            : 'No secret resolutions.'
        }
        getRowKey={(row) => row.id}
        loading={resolutionsQuery.isLoading}
        rows={resolutionsQuery.data ?? []}
      />
    </div>
  )
}
