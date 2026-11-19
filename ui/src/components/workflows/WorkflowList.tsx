import { useMemo, useRef, useState } from 'react'

import { Link, useNavigate } from 'react-router-dom'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { startWorkflowRun } from '@/api/endpoints'
import { AdminSection } from '@/components/admin/AdminSection'
import { agentsPath } from '@/components/agents/agentsNav'
import { AdminTable } from '@/components/ui/admin-table'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useHasPermission } from '@/hooks/useHasPermission'
import { extractApiErrorDetail } from '@/lib/apiError'
import { cn } from '@/lib/utils'

import {
  type ManualInput,
  manualTrigger,
  STATUS,
  type WorkflowFailures,
} from './runs'
import { StartRunDialog } from './StartRunDialog'
import { stepIcon } from './stepStyle'
import type { RunStatus, StepType, WorkflowSummary } from './types'
import { workflowVersionQuery } from './workflowQueries'
import { StatusBadge } from './WorkflowStatusBadge'

const OUTCOME_TONE: Record<string, string> = {
  danger: 'text-danger',
  info: 'text-info',
  success: 'text-success',
  warning: 'text-warning',
}

interface WorkflowListProps {
  error: unknown
  /**
   * The failed runs of the last 7 days, by workflow slug. `null` while
   * the run history is not loaded.
   */
  failures: null | Record<string, WorkflowFailures>
  /** Why the run history did not load. */
  failuresError: unknown
  loading: boolean
  stepTypes: StepType[]
  workflows: WorkflowSummary[]
}

export function WorkflowList({
  error,
  failures,
  failuresError,
  loading,
  stepTypes,
  workflows,
}: WorkflowListProps) {
  const navigate = useNavigate()
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug
  const canCreate = useHasPermission('workflow:create', orgSlug)
  const canRun = useHasPermission('workflow:run', orgSlug)
  const queryClient = useQueryClient()
  // The workflow whose manual trigger asks for inputs before a run.
  const [asking, setAsking] = useState<null | {
    inputs: ManualInput[]
    org: string
    slug: string
  }>(null)
  // The organization selected now, for a run that starts after a switch.
  const orgRef = useRef(orgSlug)
  orgRef.current = orgSlug
  // The organization comes from the click, not from the current render.
  const start = useMutation({
    mutationFn: (v: {
      inputs: Record<string, boolean | number | string>
      org: string
      slug: string
    }) => startWorkflowRun(v.org, v.slug, v.inputs),
    onError: startFailed,
    // The editor opens the run panel for `?run=<id>`. The editor reads
    // the selected organization, so do not open it after a switch.
    onSuccess: (run, { org, slug }) => {
      setAsking(null)
      if (org !== orgRef.current) toast.success(`Started a run of ${slug}.`)
      else navigate(`${agentsPath('workflows', slug)}?run=${run.id}`)
    },
  })
  // Blocks a second click from the version fetch through the run start.
  const launching = useRef(false)
  const [fetching, setFetching] = useState(false)
  // A run starts the active version: read its manual trigger inputs.
  const onRun = async (w: WorkflowSummary) => {
    if (launching.current) return
    launching.current = true
    setFetching(true)
    const org = orgSlug!
    try {
      const { graph } = await queryClient.fetchQuery(
        workflowVersionQuery(org, w.slug, w.active_version!),
      )
      const trigger = manualTrigger(graph)
      if (!trigger) toast.error('The active version has no manual trigger.')
      else if (trigger.inputs.length)
        setAsking({ inputs: trigger.inputs, org, slug: w.slug })
      // onError reports a failed start.
      else
        await start
          .mutateAsync({ inputs: {}, org, slug: w.slug })
          .catch(() => undefined)
    } catch (error) {
      startFailed(error)
    } finally {
      launching.current = false
      setFetching(false)
    }
  }
  const runnable = (w: WorkflowSummary) =>
    canRun &&
    w.status === 'active' &&
    w.active_version !== null &&
    w.trigger_types.includes('manual')
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
            // Only a Run button stacks above the row link.
            interactive: runnable,
            key: 'trigger',
            render: (w) => (
              <TriggerCell
                labels={labels}
                onRun={runnable(w) ? () => void onRun(w) : undefined}
                pending={fetching || start.isPending}
                types={w.trigger_types}
              />
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
            render: (w) =>
              failures ? (
                <FailedCell failures={failures[w.slug]} slug={w.slug} />
              ) : failuresError ? (
                <span className="text-danger text-sm">Unavailable</span>
              ) : (
                <span className="text-tertiary text-sm">—</span>
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
      {asking && (
        <StartRunDialog
          inputs={asking.inputs}
          onClose={() => setAsking(null)}
          onStart={(inputs) =>
            start.mutate({ inputs, org: asking.org, slug: asking.slug })
          }
          open
          pending={start.isPending}
        />
      )}
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

function startFailed(error: unknown) {
  toast.error(`Failed to start the run: ${extractApiErrorDetail(error)}`)
}

function TriggerCell({
  labels,
  onRun,
  pending,
  types,
}: {
  labels: Record<string, string>
  /** Starts a run; set only when the user can run the workflow now. */
  onRun?: () => void
  pending: boolean
  types: string[]
}) {
  if (types.length === 0) {
    return <span className="text-tertiary text-sm">No trigger</span>
  }
  const Icon = stepIcon(types[0])
  const Wrap = onRun ? 'button' : 'div'
  return (
    <Wrap
      className="flex min-w-0 items-center gap-2 enabled:cursor-pointer enabled:hover:underline disabled:cursor-wait"
      {...(onRun && {
        disabled: pending,
        onClick: onRun,
        title: 'Start a run of the active version',
        type: 'button' as const,
      })}
    >
      <span className="bg-tertiary text-secondary flex size-6 shrink-0 items-center justify-center rounded-md">
        <Icon className="size-3.5" />
      </span>
      <span className="truncate text-sm">
        {types.map((t) => labels[t] ?? t).join(', ')}
      </span>
    </Wrap>
  )
}
