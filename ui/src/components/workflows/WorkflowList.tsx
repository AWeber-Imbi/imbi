import { useMemo, useState } from 'react'

import { Link, useNavigate } from 'react-router-dom'

import { AdminSection } from '@/components/admin/AdminSection'
import { agentsPath } from '@/components/agents/agentsNav'
import { AdminTable } from '@/components/ui/admin-table'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useHasPermission } from '@/hooks/useHasPermission'
import { cn } from '@/lib/utils'

import { STATUS, type WorkflowFailures } from './runs'
import { stepIcon } from './stepStyle'
import type { RunStatus, StepType, WorkflowSummary } from './types'
import { StatusBadge } from './WorkflowStatusBadge'

const OUTCOME_TONE: Record<string, string> = {
  danger: 'text-danger',
  info: 'text-info',
  success: 'text-success',
  warning: 'text-warning',
}

interface WorkflowListProps {
  error: unknown
  /** The failed runs of the last 7 days, by workflow slug. */
  failures: Record<string, WorkflowFailures>
  loading: boolean
  stepTypes: StepType[]
  workflows: WorkflowSummary[]
}

export function WorkflowList({
  error,
  failures,
  loading,
  stepTypes,
  workflows,
}: WorkflowListProps) {
  const navigate = useNavigate()
  const { selectedOrganization } = useOrganization()
  const canCreate = useHasPermission(
    'workflow:create',
    selectedOrganization?.slug,
  )
  const [search, setSearch] = useState('')
  const labels = useMemo(
    () => Object.fromEntries(stepTypes.map((t) => [t.type, t.label])),
    [stepTypes],
  )

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return workflows
    return workflows.filter((w) =>
      [w.name, w.description, w.owner_team_slug]
        .join(' ')
        .toLowerCase()
        .includes(q),
    )
  }, [search, workflows])

  return (
    <AdminSection
      createLabel="New workflow"
      error={error}
      errorTitle="Failed to load workflows"
      onCreate={
        canCreate ? () => navigate(agentsPath('workflows', 'new')) : undefined
      }
      onSearchChange={setSearch}
      search={search}
      searchPlaceholder="Search workflows"
    >
      <AdminTable
        columns={[
          {
            header: 'Name',
            key: 'name',
            render: (w) => (
              <div className="flex min-w-0 flex-col">
                <span className="text-sm font-medium">{w.name}</span>
                {w.description && (
                  <span className="text-tertiary max-w-90 truncate text-xs">
                    {w.description}
                  </span>
                )}
              </div>
            ),
          },
          {
            header: 'Trigger',
            key: 'trigger',
            render: (w) => (
              <TriggerCell labels={labels} types={w.trigger_types} />
            ),
          },
          {
            header: 'Last run',
            key: 'last',
            render: (w) => <LastRun workflow={w} />,
          },
          {
            cellAlign: 'right',
            header: 'Runs 30d',
            headerAlign: 'right',
            key: 'runs',
            render: (w) => (
              <span className="font-mono text-sm">{w.runs_30d ?? '—'}</span>
            ),
          },
          {
            header: 'Failed 7d',
            interactive: true,
            key: 'failed',
            render: (w) => (
              <FailedCell failures={failures[w.slug]} slug={w.slug} />
            ),
          },
          {
            header: 'Status',
            key: 'status',
            render: (w) => <StatusBadge status={w.status} />,
          },
        ]}
        emptyMessage={
          workflows.length === 0
            ? 'No workflows yet.'
            : 'No workflows match that search.'
        }
        getRowHref={(w) => agentsPath('workflows', w.slug)}
        getRowKey={(w) => w.slug}
        getRowLabel={(w) => w.name}
        loading={loading}
        rows={rows}
      />
    </AdminSection>
  )
}

function FailedCell({
  failures,
  slug,
}: {
  failures: undefined | WorkflowFailures
  slug: string
}) {
  if (!failures) return <span className="text-tertiary text-sm">None</span>
  const { failed, others, top, topCount, total } = failures
  return (
    <Link
      className="flex flex-col hover:underline"
      to={`${agentsPath('workflows')}?view=runs&workflow=${encodeURIComponent(slug)}`}
    >
      <span className="text-danger text-sm font-medium">
        {failed === total && total > 1
          ? `${failed} of ${total} failed`
          : `${failed} failed`}
      </span>
      <span className="text-secondary text-xs">
        <span className="font-mono">{top}</span> ×{topCount}
        {others > 0 &&
          `, +${others} other ${others === 1 ? 'reason' : 'reasons'}`}
      </span>
    </Link>
  )
}

function LastRun({ workflow }: { workflow: WorkflowSummary }) {
  if (!workflow.last_run_at || !workflow.last_run_status) {
    return <span className="text-tertiary text-sm">—</span>
  }
  const status = STATUS[workflow.last_run_status as RunStatus]
  return (
    <div className="flex flex-col">
      <RelativeTime className="text-sm" value={workflow.last_run_at} />
      <span
        className={cn(
          'text-xs',
          OUTCOME_TONE[status?.variant ?? ''] ?? 'text-tertiary',
        )}
      >
        {status?.label ?? workflow.last_run_status}
      </span>
    </div>
  )
}

function TriggerCell({
  labels,
  types,
}: {
  labels: Record<string, string>
  types: string[]
}) {
  if (types.length === 0) {
    return <span className="text-tertiary text-sm">No trigger</span>
  }
  const Icon = stepIcon(types[0], 'trigger')
  return (
    <div className="flex min-w-0 items-center gap-2">
      <span className="bg-tertiary text-secondary flex size-6 shrink-0 items-center justify-center rounded-md">
        <Icon className="size-3.5" />
      </span>
      <span className="truncate text-sm">
        {types.map((t) => labels[t] ?? t).join(', ')}
      </span>
    </div>
  )
}
