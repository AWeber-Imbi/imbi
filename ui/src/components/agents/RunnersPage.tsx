import { Link } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'
import { Server } from 'lucide-react'

import { listHarnessPools } from '@/api/endpoints'
import { Alert } from '@/components/ui/alert'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { ErrorBanner } from '@/components/ui/error-banner'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useHasPermission } from '@/hooks/useHasPermission'
import { formatRelativeDate } from '@/lib/formatDate'
import { queryKeys } from '@/lib/queryKeys'
import type { HarnessPool, HarnessRunner } from '@/types'

import { agentsPath } from './agentsNav'

/** How often the runner list refreshes. */
const POLL_MS = 15_000

const COLUMNS = ['Runner', 'Labels', 'State', 'Chain', 'Heartbeat', 'Version']

const STATE_VARIANT: Record<HarnessRunner['state'], BadgeProps['variant']> = {
  busy: 'info',
  fenced: 'danger',
  idle: 'success',
  offline: 'neutral',
}

/**
 * The runner pools that serve the organization and their live runners
 * (ADR 0022). Read only. Platform administrators see every chain; other
 * people see only the chains of their organization.
 */
export function RunnersPage() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug
  const canRead = useHasPermission('harness_pool:read')
  const pools = useQuery({
    enabled: !!orgSlug && canRead,
    queryFn: ({ signal }) => listHarnessPools(orgSlug!, signal),
    queryKey: queryKeys.harnessPools(orgSlug ?? ''),
    refetchInterval: POLL_MS,
  })

  if (!canRead) {
    return (
      <div className="p-8">
        <Alert>You need the harness_pool:read permission to see runners.</Alert>
      </div>
    )
  }
  if (!orgSlug) {
    return (
      <div className="text-tertiary p-8 text-center">
        Select an organization to see its runners.
      </div>
    )
  }

  // A failed refresh keeps the last data on the page, with a warning.
  return (
    <div className="flex flex-col gap-4 p-8">
      {pools.error && (
        <ErrorBanner
          error={pools.error}
          title={
            pools.data
              ? 'Failed to refresh runners; this is the last data'
              : 'Failed to load runners'
          }
        />
      )}
      {!pools.data ? (
        !pools.error && <p className="text-tertiary text-sm">Loading…</p>
      ) : pools.data.length === 0 ? (
        <p className="text-tertiary text-sm">
          No runner pool serves this organization.
        </p>
      ) : (
        pools.data.map((pool) => <PoolCard key={pool.name} pool={pool} />)
      )}
    </div>
  )
}

function PoolCard({ pool }: { pool: HarnessPool }) {
  const runners = pool.runners ?? []
  return (
    <Card className="overflow-hidden p-0">
      <div className="border-tertiary flex flex-wrap items-center gap-3 border-b px-5 py-3.5">
        <span className="bg-secondary text-secondary flex size-7 items-center justify-center rounded-md">
          <Server className="size-3.75" />
        </span>
        <div className="flex flex-col gap-0.5">
          <span className="text-[15px] font-semibold">{pool.name}</span>
          <span className="text-secondary font-mono text-xs">
            {runners.length} {runners.length === 1 ? 'runner' : 'runners'} ·{' '}
            {pool.organizations.length
              ? pool.organizations.join(', ')
              : 'all organizations'}
          </span>
        </div>
        <div className="ml-auto flex flex-wrap gap-1">
          {pool.labels.map((label) => (
            <Badge key={label} variant="outline">
              {label}
            </Badge>
          ))}
        </div>
      </div>
      {runners.length === 0 ? (
        <p className="text-tertiary px-5 py-4 text-sm">No live runners.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-tertiary border-b">
                {COLUMNS.map((column) => (
                  <th
                    className="text-tertiary h-9 px-4 text-left align-middle text-[11px] font-medium tracking-wider whitespace-nowrap uppercase"
                    key={column}
                  >
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {runners.map((runner) => (
                <RunnerRow key={runner.id} runner={runner} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

function RunnerRow({ runner }: { runner: HarnessRunner }) {
  const chain = runner.chain
  return (
    <tr className="border-tertiary border-b last:border-0">
      <td className="px-4 py-2 font-mono text-xs">
        {runner.instance ?? runner.id.slice(0, 8)}
      </td>
      <td className="text-secondary px-4 py-2 text-xs">
        {runner.labels.join(', ') || '—'}
      </td>
      <td className="px-4 py-2">
        <Badge variant={STATE_VARIANT[runner.state]}>{runner.state}</Badge>
      </td>
      <td className="px-4 py-2 text-xs">
        {!chain ? (
          <span className="text-tertiary">
            {/* Only a busy runner holds a chain that can be hidden. */}
            {runner.state === 'busy' ? 'Another organization' : '—'}
          </span>
        ) : (
          <span className="flex flex-wrap items-center gap-2">
            {chain.short_id && chain.organization_slug ? (
              <Link
                className="text-action font-mono hover:underline"
                to={agentsPath(
                  'tasks',
                  chain.organization_slug,
                  chain.short_id,
                )}
              >
                {chain.short_id}
              </Link>
            ) : (
              <span className="font-mono">{chain.root_task_id}</span>
            )}
            <span className="text-tertiary">attempt {chain.attempt}</span>
            {chain.state !== 'running' && (
              <Badge
                title={chain.fence_error ?? undefined}
                variant={chain.state === 'stuck' ? 'danger' : 'warning'}
              >
                {chain.state}
              </Badge>
            )}
          </span>
        )}
      </td>
      <td className="text-secondary px-4 py-2 text-xs whitespace-nowrap">
        {formatRelativeDate(runner.last_heartbeat)}
      </td>
      <td className="text-secondary px-4 py-2 font-mono text-xs">
        {runner.image_version ?? '—'}
      </td>
    </tr>
  )
}
