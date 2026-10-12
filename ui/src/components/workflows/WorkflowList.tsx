import { useMemo, useState } from 'react'

import { Link, useNavigate } from 'react-router-dom'

import { AdminSection } from '@/components/admin/AdminSection'
import { agentsPath } from '@/components/agents/agentsNav'
import { AdminTable } from '@/components/ui/admin-table'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { useHasPermission } from '@/hooks/useHasPermission'
import { cn } from '@/lib/utils'

import { StatusBadge as RunStatusBadge } from './RunPanel'
import { STATUS } from './runs'
import { stepIcon } from './stepStyle'
import type {
  AttentionRun,
  RunStatus,
  StepType,
  WorkflowSummary,
} from './types'
import { StatusBadge } from './WorkflowStatusBadge'

const OUTCOME_TONE: Record<string, string> = {
  danger: 'text-danger',
  info: 'text-info',
  success: 'text-success',
  warning: 'text-warning',
}

interface WorkflowListProps {
  /** Failed and stuck runs; empty for people who are not admins. */
  attention: AttentionRun[]
  error: unknown
  loading: boolean
  stepTypes: StepType[]
  workflows: WorkflowSummary[]
}

export function WorkflowList({
  attention,
  error,
  loading,
  stepTypes,
  workflows,
}: WorkflowListProps) {
  const navigate = useNavigate()
  const canCreate = useHasPermission('workflow:create')
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
    <>
      {attention.length > 0 && <AttentionList runs={attention} />}
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
    </>
  )
}

/** Runs that an admin should look at: failed, or stuck with no engine. */
function AttentionList({ runs }: { runs: AttentionRun[] }) {
  return (
    <section className="border-tertiary mb-6 rounded-lg border">
      <header className="border-tertiary flex items-baseline gap-2 border-b px-4 py-2.5">
        <span className="font-medium">Runs that need attention</span>
        <span className="text-tertiary text-xs">
          Failed in the last 7 days, or stuck with no engine working on them
        </span>
      </header>
      {runs.map((run) => (
        <Link
          className="border-tertiary hover:bg-secondary grid grid-cols-[96px_minmax(0,1.2fr)_minmax(0,2fr)_120px] items-center gap-3 border-b px-4 py-2 text-sm last:border-b-0"
          key={run.id}
          to={`${agentsPath('workflows', run.workflow_slug)}?run=${run.id}`}
        >
          <RunStatusBadge status={run.status} />
          <span className="truncate font-medium">{run.workflow_name}</span>
          <span
            className={cn(
              'truncate',
              run.reason === 'stuck' ? 'text-warning' : 'text-danger',
            )}
          >
            {run.reason === 'stuck'
              ? run.worker_id
                ? `Stuck: the lease of ${run.worker_id} expired`
                : 'Stuck: no engine has picked it up'
              : (run.error ?? 'Failed')}
          </span>
          <RelativeTime
            className="text-tertiary text-right text-xs"
            value={run.closed_at ?? run.created_at}
          />
        </Link>
      ))}
    </section>
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
