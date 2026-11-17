import { useMemo, useState } from 'react'

import { Link, useSearchParams } from 'react-router-dom'

import { Search } from 'lucide-react'

import { agentsPath } from '@/components/agents/agentsNav'
import { AdminTable } from '@/components/ui/admin-table'
import { ErrorBanner } from '@/components/ui/error-banner'
import { Input } from '@/components/ui/input'
import { RelativeTime } from '@/components/ui/RelativeTime'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@/components/ui/segmented-control'
import { cn } from '@/lib/utils'

import { StatusBadge } from './RunPanel'
import {
  durationMs,
  type FailureCause,
  failureCauses,
  failureReason,
  formatDuration,
  isFailed,
  isOpen,
  originLabel,
} from './runs'
import type { OrgRun, WorkflowSummary } from './types'
import { useOrgRuns } from './workflowQueries'

type Segment = 'all' | 'failed' | 'open' | 'stuck' | 'succeeded'

const SEGMENTS: {
  label: string
  match: (r: OrgRun) => boolean
  value: Segment
}[] = [
  { label: 'All', match: () => true, value: 'all' },
  { label: 'Failed', match: (r) => isFailed(r.status), value: 'failed' },
  { label: 'Stuck', match: (r) => r.stuck, value: 'stuck' },
  {
    label: 'Running',
    match: (r) => isOpen(r.status) && !r.stuck,
    value: 'open',
  },
  {
    label: 'Succeeded',
    match: (r) => r.status === 'succeeded',
    value: 'succeeded',
  },
]

const WINDOWS = [1, 7, 30]
const TRIGGERS = [
  ['human', 'Manual'],
  ['schedule', 'Schedule'],
  ['webhook', 'Webhook'],
]
/** A run that waited this long for an engine shows the wait. */
const QUEUED_NOTE_MS = 30_000

/** Workflows > Runs: the runs of every workflow, failures by cause. */
export function RunsTab({
  orgSlug,
  workflows,
}: {
  orgSlug: string
  workflows: WorkflowSummary[]
}) {
  const [params, setParams] = useSearchParams()
  const workflow = params.get('workflow') ?? ''
  const [days, setDays] = useState(7)
  const [trigger, setTrigger] = useState('')
  const [search, setSearch] = useState('')
  const [segment, setSegment] = useState<Segment>('failed')
  const [cause, setCause] = useState<null | string>(null)
  const runs = useOrgRuns(orgSlug, days)

  const base = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (runs.data ?? []).filter(
      (r) =>
        (!workflow || r.workflow_slug === workflow) &&
        (!trigger || r.origin_kind === trigger) &&
        (!q ||
          [
            r.id,
            r.workflow_name,
            r.origin_id,
            r.failure?.title,
            r.failure?.task_id,
            failureReason(r),
          ]
            .join(' ')
            .toLowerCase()
            .includes(q)),
    )
  }, [runs.data, search, trigger, workflow])
  const causes = useMemo(() => failureCauses(base), [base])
  const counts = useMemo(() => {
    const found: Partial<Record<Segment, number>> = {}
    for (const r of base) {
      for (const s of SEGMENTS) {
        if (s.match(r)) found[s.value] = (found[s.value] ?? 0) + 1
      }
    }
    return found
  }, [base])
  const shown = useMemo(() => {
    const match = SEGMENTS.find((s) => s.value === segment)!.match
    return base.filter(
      (r) => match(r) && (!cause || failureReason(r) === cause),
    )
  }, [base, cause, segment])

  const setWorkflow = (slug: string) => {
    const next = new URLSearchParams(params)
    if (slug) next.set('workflow', slug)
    else next.delete('workflow')
    setParams(next, { replace: true })
  }

  if (runs.error) {
    return <ErrorBanner error={runs.error} title="Failed to load runs" />
  }
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-2.5">
        <div className="relative max-w-md min-w-64 flex-1">
          <Search className="text-tertiary absolute top-1/2 left-3 size-4 -translate-y-1/2" />
          <Input
            aria-label="Search runs"
            className="pl-10"
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by run ID, workflow, step, task, or reason"
            value={search}
          />
        </div>
        <SegmentedControl
          ariaLabel="Run status"
          onValueChange={(v) => {
            setSegment(v as Segment)
            setCause(null)
          }}
          value={segment}
        >
          {SEGMENTS.map((s) => (
            <SegmentedControlItem key={s.value} value={s.value}>
              {s.label}
              {s.value !== 'all' && (
                <span className="text-tertiary">{counts[s.value] ?? 0}</span>
              )}
            </SegmentedControlItem>
          ))}
        </SegmentedControl>
        <FilterSelect
          label="Workflow"
          onChange={setWorkflow}
          options={workflows.map((w) => [w.slug, w.name])}
          value={workflow}
        />
        <FilterSelect
          label="Trigger"
          onChange={setTrigger}
          options={TRIGGERS}
          value={trigger}
        />
        <FilterSelect
          any={false}
          label="Time window"
          onChange={(v) => setDays(Number(v))}
          options={WINDOWS.map((d) => [String(d), `Last ${windowLabel(d)}`])}
          value={String(days)}
        />
      </div>

      {causes.length > 0 && (segment === 'failed' || segment === 'all') && (
        <CauseTable causes={causes} onPick={setCause} selected={cause} />
      )}

      <section className="flex flex-col gap-2">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div className="flex items-baseline gap-2.5">
            <h2 className="text-card-title">Runs</h2>
            <span className="text-secondary text-sm">
              {cause
                ? `${shown.length} failed with ${cause}`
                : `${shown.length} in the last ${windowLabel(days)}`}
            </span>
          </div>
          <span className="text-tertiary text-xs">Newest first</span>
        </div>
        <AdminTable
          columns={[
            {
              header: 'Run',
              key: 'run',
              render: (r) => (
                <div className="flex min-w-0 flex-col gap-1">
                  <span className="flex items-center gap-2">
                    <StatusBadge status={r.status} />
                    <span className="text-secondary font-mono text-xs">
                      {r.id.slice(0, 8)}
                    </span>
                  </span>
                  <span className="truncate text-sm font-medium">
                    {r.workflow_name}
                  </span>
                </div>
              ),
            },
            {
              header: 'Origin',
              key: 'origin',
              render: (r) => (
                <span className="text-secondary text-sm">{originLabel(r)}</span>
              ),
            },
            {
              header: 'Failed step',
              key: 'step',
              render: (r) =>
                r.failure ? (
                  <div className="flex flex-col">
                    <span className="text-sm">{r.failure.title}</span>
                    <span className="text-tertiary text-xs">
                      Attempt {r.failure.attempt}
                    </span>
                  </div>
                ) : (
                  <span className="text-tertiary text-sm">—</span>
                ),
            },
            {
              header: 'Why',
              key: 'why',
              render: (r) => <Why run={r} />,
            },
            {
              header: 'Task',
              interactive: true,
              key: 'task',
              render: (r) =>
                r.failure?.task_id ? (
                  <Link
                    className="text-secondary font-mono text-xs hover:underline"
                    to={agentsPath('tasks', orgSlug, r.failure.task_id)}
                  >
                    {r.failure.task_id}
                  </Link>
                ) : (
                  <span className="text-tertiary text-sm">—</span>
                ),
            },
            {
              header: 'Started',
              key: 'started',
              render: (r) => (
                <RelativeTime className="text-sm" value={r.created_at} />
              ),
            },
            {
              cellAlign: 'right',
              header: 'Duration',
              headerAlign: 'right',
              key: 'duration',
              render: (r) => <RunDuration run={r} />,
            },
          ]}
          emptyMessage="No runs match."
          getRowHref={(r) =>
            agentsPath('workflows', r.workflow_slug, 'runs', r.id)
          }
          getRowKey={(r) => r.id}
          getRowLabel={(r) => `Run ${r.id.slice(0, 8)} of ${r.workflow_name}`}
          loading={runs.isLoading}
          rows={shown}
        />
      </section>
    </div>
  )
}

function CauseTable({
  causes,
  onPick,
  selected,
}: {
  causes: FailureCause[]
  onPick: (reason: null | string) => void
  selected: null | string
}) {
  const failed = causes.reduce((n, c) => n + c.count, 0)
  const most = causes[0].count
  const grid =
    'grid grid-cols-[minmax(0,2.4fr)_minmax(0,1.1fr)_minmax(0,2fr)_minmax(0,2.2fr)_90px] gap-4'
  return (
    <section className="border-tertiary bg-primary overflow-hidden rounded-lg border">
      <div className="border-tertiary flex flex-wrap items-baseline justify-between gap-2 border-b px-5 py-4">
        <div className="flex flex-wrap items-baseline gap-2.5">
          <h2 className="text-card-title">Failure causes</h2>
          <span className="text-secondary text-sm">
            {failed} failed {failed === 1 ? 'run' : 'runs'}, {causes.length}{' '}
            {causes.length === 1 ? 'cause' : 'causes'}. The reason comes from
            the failed step.
          </span>
        </div>
        {selected && (
          <button
            className="text-action text-sm"
            onClick={() => onPick(null)}
            type="button"
          >
            Show all causes
          </button>
        )}
      </div>
      <div className="overflow-x-auto">
        <div className="min-w-225">
          <div
            className={cn(
              grid,
              'border-b border-tertiary px-5 py-2.5 text-overline text-tertiary uppercase',
            )}
          >
            <span>Reason</span>
            <span>Runs</span>
            <span>Workflow</span>
            <span>Failed step</span>
            <span>Last seen</span>
          </div>
          {causes.map((c) => (
            <button
              aria-pressed={selected === c.reason}
              className={cn(
                grid,
                'w-full items-center border-b border-tertiary px-5 py-3 text-left last:border-b-0 hover:bg-secondary',
                selected === c.reason && 'bg-tertiary',
              )}
              key={c.reason}
              onClick={() => onPick(selected === c.reason ? null : c.reason)}
              type="button"
            >
              <span className="flex min-w-0 flex-col">
                <span className="text-danger truncate font-mono text-sm">
                  {c.reason}
                </span>
                {c.outcome && (
                  <span className="text-tertiary text-xs">{c.outcome}</span>
                )}
              </span>
              <span className="flex items-center gap-2.5">
                <span className="w-6 text-right text-sm font-medium">
                  {c.count}
                </span>
                <span className="bg-tertiary h-1.5 flex-1 overflow-hidden rounded-sm">
                  <span
                    className="bg-danger block h-1.5"
                    style={{ width: `${(c.count / most) * 100}%` }}
                  />
                </span>
              </span>
              <span className="text-secondary text-sm">
                {c.workflows.join(', ')}
              </span>
              <span className="text-secondary text-sm">{c.steps}</span>
              <RelativeTime className="text-tertiary text-sm" value={c.last} />
            </button>
          ))}
        </div>
      </div>
    </section>
  )
}

function FilterSelect({
  any = true,
  label,
  onChange,
  options,
  value,
}: {
  /** Offer an empty "Any" option. */
  any?: boolean
  label: string
  onChange: (value: string) => void
  options: string[][]
  value: string
}) {
  return (
    <select
      aria-label={label}
      className="border-tertiary bg-primary text-primary h-9 rounded-md border px-2 text-sm"
      onChange={(e) => onChange(e.target.value)}
      value={value}
    >
      {any && <option value="">{label}: Any</option>}
      {options.map(([v, text]) => (
        <option key={v} value={v}>
          {text}
        </option>
      ))}
    </select>
  )
}

function RunDuration({ run }: { run: OrgRun }) {
  const queued = durationMs(run.created_at, run.started_at)
  return (
    <div className="flex flex-col items-end">
      <span className="text-sm">
        {formatDuration(
          durationMs(run.started_at ?? run.created_at, run.closed_at),
        )}
      </span>
      {queued !== null && queued >= QUEUED_NOTE_MS && (
        <span className="text-warning text-xs">
          queued {formatDuration(queued)}
        </span>
      )}
    </div>
  )
}

function Why({ run }: { run: OrgRun }) {
  const reason = failureReason(run)
  if (!reason) {
    return run.stuck ? (
      <span className="text-warning text-sm">No engine works on it</span>
    ) : (
      <span className="text-tertiary text-sm">—</span>
    )
  }
  return (
    <div className="flex max-w-90 flex-col gap-1">
      <span className="text-danger font-mono text-sm break-all">{reason}</span>
      {run.failure?.summary && (
        <span className="text-secondary line-clamp-2 text-xs">
          {run.failure.summary}
        </span>
      )}
    </div>
  )
}

const windowLabel = (days: number) => (days === 1 ? '24 hours' : `${days} days`)
