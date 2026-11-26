import { useMemo, useRef, useState } from 'react'

import { Link, useNavigate } from 'react-router-dom'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { startWorkflowRun } from '@/api/endpoints'
import { AdminSection } from '@/components/admin/AdminSection'
import { agentsPath } from '@/components/agents/agentsNav'
import { TagChips } from '@/components/tags/TagChip'
import { AdminTable } from '@/components/ui/admin-table'
import { RelativeTime } from '@/components/ui/RelativeTime'
import {
  headerWithFilter as header,
  useTableFacets,
  useTableSort,
} from '@/components/ui/table-controls'
import { UserIdentity } from '@/components/ui/user-identity'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useHasPermission } from '@/hooks/useHasPermission'
import { useServiceAccountAgents } from '@/hooks/useServiceAccountAgents'
import { useUserDisplayNames } from '@/hooks/useUserDisplayNames'
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
import type {
  RunStatus,
  StepType,
  WorkflowStatus,
  WorkflowSummary,
} from './types'
import { workflowVersionQuery } from './workflowQueries'
import { LABEL as STATUS_LABEL, StatusBadge } from './WorkflowStatusBadge'

const FACET_KEYS = [
  'author',
  'last',
  'status',
  'tag',
  'team',
  'trigger',
] as const
type FacetKey = (typeof FACET_KEYS)[number]
type SortKey = 'failed' | 'name' | 'runs' | 'tags' | Exclude<FacetKey, 'tag'>

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
    w.active_trigger_types.includes('manual')
  const [search, setSearch] = useState('')
  const labels = useMemo(
    () => Object.fromEntries(stepTypes.map((t) => [t.type, t.label])),
    [stepTypes],
  )
  const { displayNames } = useUserDisplayNames()
  const serviceAccounts = useServiceAccountAgents()
  const nameOf = (principal: string) =>
    serviceAccounts.get(principal)?.name ??
    displayNames.get(principal) ??
    principal
  const authorName = (w: WorkflowSummary) => nameOf(w.created_by)
  const sortValue = (w: WorkflowSummary, key: SortKey): number | string => {
    if (key === 'name') return w.name
    if (key === 'author') return authorName(w)
    if (key === 'team') return w.owner_team_name ?? ''
    if (key === 'tags')
      return w.tags
        .map((t) => t.name)
        .sort()
        .join(' ')
    if (key === 'trigger')
      return triggers(w)
        .map((t) => labels[t] ?? t)
        .join(', ')
    if (key === 'last') return w.last_run_at ? Date.parse(w.last_run_at) : 0
    if (key === 'runs') return w.runs_30d ?? 0
    if (key === 'failed') return failures?.[w.slug]?.failed ?? 0
    return STATUS_LABEL[w.status]
  }
  const { sortButton, sorted } = useTableSort(sortValue)
  const { facet, matches } = useTableFacets(FACET_KEYS, facetValues, workflows)

  const q = search.trim().toLowerCase()
  const rows = workflows.filter(
    (w) =>
      (!q ||
        [
          w.name,
          w.description,
          w.owner_team_name,
          w.owner_team_slug,
          authorName(w),
          ...w.tags.map((t) => t.name),
        ]
          .join(' ')
          .toLowerCase()
          .includes(q)) &&
      matches(w),
  )
  const teamNames = Object.fromEntries(
    workflows.map((w) => [w.owner_team_slug ?? '', w.owner_team_name ?? '']),
  )
  const tagNames = Object.fromEntries(
    workflows.flatMap((w) => w.tags.map((t) => [t.slug, t.name])),
  )

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
            header: sortButton('name', 'Name'),
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
            header: header(
              sortButton('team', 'Owner team'),
              facet('team', 'Owner team', (s) => teamNames[s]),
            ),
            key: 'team',
            render: (w) => (
              <span className="text-sm">{w.owner_team_name ?? '—'}</span>
            ),
          },
          {
            header: header(
              sortButton('author', 'Author'),
              facet('author', 'Author', nameOf),
            ),
            // The profile link stacks above the row link.
            interactive: true,
            key: 'author',
            render: (w) => (
              <UserIdentity
                displayNames={displayNames}
                email={w.created_by}
                size="small"
              />
            ),
          },
          {
            header: header(
              sortButton('tags', 'Tags'),
              facet('tag', 'Tags', (s) => tagNames[s]),
            ),
            key: 'tags',
            render: (w) => <TagChips tags={w.tags} />,
          },
          {
            header: header(
              sortButton('trigger', 'Trigger'),
              facet('trigger', 'Trigger', (s) => labels[s] ?? s),
            ),
            // Only a Run button stacks above the row link.
            interactive: runnable,
            key: 'trigger',
            render: (w) => (
              <TriggerCell
                labels={labels}
                onRun={runnable(w) ? () => void onRun(w) : undefined}
                pending={fetching || start.isPending}
                types={triggers(w)}
              />
            ),
          },
          {
            header: header(
              sortButton('last', 'Last run'),
              facet(
                'last',
                'Last run',
                (s) => STATUS[s as RunStatus]?.label ?? s,
              ),
            ),
            key: 'last',
            render: (w) => <LastRun workflow={w} />,
          },
          {
            cellAlign: 'right',
            header: sortButton('runs', 'Runs 30d'),
            headerAlign: 'right',
            key: 'runs',
            render: (w) => (
              <span className="font-mono text-sm">{w.runs_30d ?? '—'}</span>
            ),
          },
          {
            header: sortButton('failed', 'Failed 7d'),
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
            header: header(
              sortButton('status', 'Status'),
              facet(
                'status',
                'Status',
                (s) => STATUS_LABEL[s as WorkflowStatus],
              ),
            ),
            key: 'status',
            render: (w) => <StatusBadge status={w.status} />,
          },
        ]}
        emptyMessage={
          workflows.length === 0
            ? 'No workflows yet.'
            : 'No workflows match those filters.'
        }
        getRowHref={(w) => agentsPath('workflows', w.slug)}
        getRowKey={(w) => w.slug}
        getRowLabel={(w) => w.name}
        loading={loading}
        rows={sorted(rows)}
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

function facetValues(w: WorkflowSummary, key: FacetKey): string[] {
  if (key === 'author') return [w.created_by]
  if (key === 'last') return w.last_run_status ? [w.last_run_status] : []
  if (key === 'status') return [w.status]
  if (key === 'tag') return w.tags.map((t) => t.slug)
  if (key === 'team') return w.owner_team_slug ? [w.owner_team_slug] : []
  return triggers(w)
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
      className="flex min-w-0 items-center gap-2 enabled:cursor-pointer hover:enabled:underline disabled:cursor-wait"
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

/** The triggers a run starts from: the active version's, else the latest's. */
function triggers(w: WorkflowSummary): string[] {
  return w.active_version === null ? w.trigger_types : w.active_trigger_types
}
