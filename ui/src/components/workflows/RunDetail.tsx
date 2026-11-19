import { type ReactNode, useState } from 'react'

import { Link, useNavigate } from 'react-router-dom'

import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'

import { startWorkflowRun } from '@/api/endpoints'
import { agentsPath, ticketsPath } from '@/components/agents/agentsNav'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ErrorBanner } from '@/components/ui/error-banner'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { RichMarkdown } from '@/components/ui/rich-markdown'
import { Sk } from '@/components/ui/skeleton'
import { useHasPermission } from '@/hooks/useHasPermission'
import { extractApiErrorDetail } from '@/lib/apiError'
import { formatDateTime } from '@/lib/formatDate'
import { cn } from '@/lib/utils'

import { JsonBlock } from './JsonBlock'
import { StatusBadge } from './RunPanel'
import {
  durationMs,
  failureReason,
  formatDuration,
  isFailed,
  isOpen,
  originLabel,
  workflowFailures,
} from './runs'
import type { StepRun, StepType, WorkflowRunDetail } from './types'
import {
  useOrgRuns,
  useStepTypes,
  useWorkflow,
  useWorkflowRun,
  useWorkflowVersion,
} from './workflowQueries'

/** What the agent task of an `agent` step reported. */
interface AgentOutput {
  outcome?: string
  reason?: null | string
  summary?: null | string
  task_id?: string
}

/** One step of a run, or a step of the graph that the run did not reach. */
interface StepLine {
  id: string
  step: null | StepRun
  title: string
  type: string
}

/** One run: why it failed first, then its steps. */
export function RunDetail({
  orgSlug,
  runId,
  slug,
}: {
  orgSlug: string
  runId: string
  slug: string
}) {
  const run = useWorkflowRun(orgSlug, slug, runId)
  const workflow = useWorkflow(orgSlug, slug)
  const version = useWorkflowVersion(orgSlug, slug, run.data?.version ?? null)
  const stepTypes = useStepTypes(orgSlug)

  const error = run.error ?? workflow.error
  if (error) {
    return (
      <div className="flex flex-col gap-4 p-8">
        <ErrorBanner error={error} title="Failed to load the run" />
        <Link className="text-action text-sm" to={runsPath()}>
          Back to runs
        </Link>
      </div>
    )
  }
  if (!run.data || !workflow.data) {
    return (
      <div className="flex flex-col gap-4 p-8">
        <Sk h={32} r={6} w={320} />
        <Sk h={480} r={12} />
      </div>
    )
  }
  const detail = run.data
  const types = Object.fromEntries(
    (stepTypes.data ?? []).map((t) => [t.type, t]),
  )
  const failed = lastFailed(detail.steps)
  const output = agentOutput(failed)
  const lines = stepLines(detail, version.data?.graph.nodes ?? [], types)

  return (
    <div className="flex flex-col gap-5 p-8">
      <nav
        aria-label="Breadcrumb"
        className="text-secondary flex flex-wrap gap-2 text-sm"
      >
        <Link className="hover:underline" to={agentsPath('workflows')}>
          Workflows
        </Link>
        <span aria-hidden="true">/</span>
        <Link className="hover:underline" to={runsPath()}>
          Runs
        </Link>
        <span aria-hidden="true">/</span>
        <span className="text-primary font-mono">{detail.id.slice(0, 8)}</span>
      </nav>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-2.5">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-h1">{workflow.data.name}</h1>
            <StatusBadge status={detail.status} />
            <Badge variant="neutral">v{detail.version}</Badge>
          </div>
          <div className="text-secondary flex flex-wrap gap-x-5 gap-y-1.5 text-sm">
            <span>{originLabel(detail)}</span>
            <span>Started {formatDateTime(detail.created_at)}</span>
            {detail.closed_at && (
              <span>
                Ran{' '}
                {formatDuration(
                  durationMs(
                    detail.started_at ?? detail.created_at,
                    detail.closed_at,
                  ),
                )}
              </span>
            )}
            <span className="font-mono">{detail.id}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="ghost">
            <Link to={agentsPath('workflows', slug)}>Edit workflow</Link>
          </Button>
          {output?.task_id && (
            <Button asChild variant="outline">
              <Link to={ticketsPath(orgSlug, output.task_id)}>
                Open task {output.task_id}
              </Link>
            </Button>
          )}
          {detail.origin_kind === 'human' &&
            !isOpen(detail.status) &&
            workflow.data.status === 'active' &&
            // Retry starts the active version with this run's inputs.
            detail.version === workflow.data.active_version && (
              <RetryButton orgSlug={orgSlug} run={detail} slug={slug} />
            )}
        </div>
      </div>

      <div className="flex flex-wrap items-start gap-5">
        <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-5">
          {isFailed(detail.status) && (
            <WhyCard failed={failed} output={output} run={detail} />
          )}
          {version.error && (
            <div className="flex flex-col items-start gap-2">
              <ErrorBanner
                error={version.error}
                title="Failed to load the workflow version: steps that the run did not reach are not shown"
              />
              <Button onClick={() => version.refetch()} variant="outline">
                Try again
              </Button>
            </div>
          )}
          <StepsCard lines={lines} types={types} />
        </div>
        <aside className="flex max-w-95 flex-[1_1_300px] flex-col gap-5">
          <History orgSlug={orgSlug} runId={detail.id} slug={slug} />
          <Card title="Run">
            <dl className="grid grid-cols-[110px_minmax(0,1fr)] gap-x-3 gap-y-2 px-5 pb-4 text-sm">
              <Fact label="Created">{formatDateTime(detail.created_at)}</Fact>
              <Fact label="Closed">{formatDateTime(detail.closed_at)}</Fact>
              <Fact label="Log archived">
                {formatDateTime(detail.log_archived_at)}
              </Fact>
              <Fact label="Origin">{detail.origin_kind}</Fact>
              <Fact label="Version">
                {detail.version}
                {detail.version === workflow.data.active_version && ' (active)'}
              </Fact>
            </dl>
          </Card>
        </aside>
      </div>
    </div>
  )
}

function agentOutput(step: null | StepRun): AgentOutput | null {
  return step?.node_type === 'agent' && step.output
    ? (step.output as AgentOutput)
    : null
}

function Card({
  border = 'border-tertiary',
  children,
  note,
  title,
}: {
  border?: string
  children: ReactNode
  note?: ReactNode
  title: string
}) {
  return (
    <section
      className={cn('overflow-hidden rounded-lg border bg-primary', border)}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2 px-5 py-4">
        <h2 className="text-card-title">{title}</h2>
        {note && <span className="text-secondary text-sm">{note}</span>}
      </div>
      {children}
    </section>
  )
}

function Fact({ children, label }: { children: ReactNode; label: string }) {
  return (
    <>
      <dt className="text-tertiary">{label}</dt>
      <dd className="m-0">{children}</dd>
    </>
  )
}

/** The failed runs of this workflow in the last 7 days. */
function History({
  orgSlug,
  runId,
  slug,
}: {
  orgSlug: string
  runId: string
  slug: string
}) {
  const recent = useOrgRuns(orgSlug, 7)
  const runs = recent.data ?? []
  const failed = runs.filter(
    (r) => r.workflow_slug === slug && isFailed(r.status),
  )
  const summary = workflowFailures(runs)[slug]
  return (
    <Card
      note={
        !recent.data ? (
          recent.error ? (
            <span className="text-danger">Failed to load the runs</span>
          ) : (
            'Loading…'
          )
        ) : summary ? (
          <span className="text-danger">
            {summary.failed} of {summary.total} runs failed,{' '}
            {summary.others + 1}{' '}
            {summary.others ? 'different reasons' : 'reason'}
          </span>
        ) : (
          'No runs failed'
        )
      }
      title="This workflow, last 7 days"
    >
      {failed.map((r) => (
        <Link
          className={cn(
            'flex flex-col gap-0.5 border-t border-tertiary px-5 py-3 hover:bg-secondary',
            r.id === runId && 'bg-tertiary',
          )}
          key={r.id}
          to={agentsPath('workflows', slug, 'runs', r.id)}
        >
          <span className="flex justify-between gap-2">
            <span className="text-secondary font-mono text-xs">
              {r.id.slice(0, 8)}
            </span>
            <RelativeTime
              className="text-tertiary text-xs"
              value={r.created_at}
            />
          </span>
          <span className="text-danger font-mono text-sm break-all">
            {failureReason(r)}
          </span>
        </Link>
      ))}
      <div className="border-tertiary border-t px-5 py-3">
        <Link
          className="text-action text-sm"
          to={`${runsPath()}&workflow=${encodeURIComponent(slug)}`}
        >
          All runs of this workflow
        </Link>
      </div>
    </Card>
  )
}

/** The failed step that finished last. */
function lastFailed(steps: StepRun[]): null | StepRun {
  return steps
    .filter((s) => s.status === 'failed')
    .reduce<null | StepRun>(
      (last, s) =>
        !last || (s.finished_at ?? '') > (last.finished_at ?? '') ? s : last,
      null,
    )
}

function RetryButton({
  orgSlug,
  run,
  slug,
}: {
  orgSlug: string
  run: WorkflowRunDetail
  slug: string
}) {
  const navigate = useNavigate()
  const canRun = useHasPermission('workflow:run', orgSlug)
  // A manual run's payload is its inputs (ADR 0021).
  const retry = useMutation({
    mutationFn: () =>
      startWorkflowRun(
        orgSlug,
        slug,
        run.payload as Record<string, boolean | number | string>,
      ),
    onError: (error) => {
      toast.error(`Failed to start the run: ${extractApiErrorDetail(error)}`)
    },
    onSuccess: (started) => {
      navigate(agentsPath('workflows', slug, 'runs', started.id))
    },
  })
  if (!canRun) return null
  return (
    <Button
      className="bg-action text-action-foreground hover:bg-action-hover"
      disabled={retry.isPending}
      onClick={() => retry.mutate()}
    >
      Retry run
    </Button>
  )
}

const runsPath = () => `${agentsPath('workflows')}?view=runs`

function Field({ children, label }: { children: ReactNode; label: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-overline text-tertiary uppercase">{label}</span>
      {children}
    </div>
  )
}

/**
 * The steps of the run, then, for a closed run, the steps of its graph
 * that it did not reach. Triggers that did not start the run are left
 * out.
 */
function stepLines(
  run: WorkflowRunDetail,
  nodes: { id: string; title: string; type: string }[],
  types: Record<string, StepType>,
): StepLine[] {
  const ran = new Set(run.steps.map((s) => s.node_id))
  return [
    ...run.steps.map((s) => ({
      id: s.node_id,
      step: s,
      title: s.title,
      type: s.node_type,
    })),
    ...(isOpen(run.status) ? [] : nodes)
      .filter((n) => !ran.has(n.id) && types[n.type]?.category !== 'trigger')
      .map((n) => ({ id: n.id, step: null, title: n.title, type: n.type })),
  ]
}

function StepRow({
  line,
  types,
}: {
  line: StepLine
  types: Record<string, StepType>
}) {
  const { step } = line
  const [open, setOpen] = useState(step?.status === 'failed')
  const output = agentOutput(step)
  const meta = [
    types[line.type]?.label ?? line.type,
    step && `attempt ${step.attempt}`,
    output?.task_id && `task ${output.task_id}`,
  ]
    .filter(Boolean)
    .join(' · ')
  const failed = step?.status === 'failed'
  return (
    <div className={cn('border-t border-tertiary', failed && 'bg-secondary')}>
      <div className="grid grid-cols-[96px_minmax(0,1fr)_minmax(0,1fr)_90px] items-center gap-3.5 px-5 py-3.5">
        {step ? (
          <StatusBadge status={step.status} />
        ) : (
          <Badge className="justify-self-start" variant="neutral">
            Not reached
          </Badge>
        )}
        <div className="flex min-w-0 flex-col">
          <span
            className={cn(
              'truncate text-sm font-medium',
              !step && 'text-secondary',
            )}
          >
            {line.title}
          </span>
          <span className="text-tertiary truncate text-xs">{meta}</span>
        </div>
        <span
          className={cn(
            'truncate text-sm',
            step?.error ? 'font-mono text-danger' : 'text-secondary',
          )}
        >
          {step?.error ?? ''}
        </span>
        <span className="text-secondary text-right text-sm">
          {step
            ? formatDuration(durationMs(step.started_at, step.finished_at))
            : '—'}
        </span>
      </div>
      {step && (step.input || step.output) && (
        <div className="flex flex-col gap-2.5 pr-5 pb-4 pl-33.5">
          <button
            aria-expanded={open}
            className="text-action self-start text-sm"
            onClick={() => setOpen(!open)}
            type="button"
          >
            {open ? 'Hide step input and output' : 'Show step input and output'}
          </button>
          {open && step.input && <JsonBlock label="Input" value={step.input} />}
          {open && step.output && (
            <JsonBlock label="Output" value={step.output} />
          )}
        </div>
      )}
    </div>
  )
}

function StepsCard({
  lines,
  types,
}: {
  lines: StepLine[]
  types: Record<string, StepType>
}) {
  const count = (status: string) =>
    lines.filter((l) => (l.step?.status ?? 'not reached') === status).length
  const parts = ['succeeded', 'failed', 'running', 'not reached']
    .filter((status) => count(status) > 0)
    .map((status) => `${count(status)} ${status}`)
  return (
    <Card
      note={`${lines.length} steps${parts.length ? `: ${parts.join(', ')}` : ''}`}
      title="Steps"
    >
      {lines.length === 0 && (
        <div className="border-tertiary text-tertiary border-t p-7 text-center text-sm">
          This run has no steps.
        </div>
      )}
      {lines.map((line) => (
        <StepRow key={line.id} line={line} types={types} />
      ))}
    </Card>
  )
}

function WhyCard({
  failed,
  output,
  run,
}: {
  failed: null | StepRun
  output: AgentOutput | null
  run: WorkflowRunDetail
}) {
  const reason = failureReason({
    ...run,
    failure: failed && { error: failed.error, reason: output?.reason },
  })
  return (
    <Card
      border="border-danger"
      note={
        failed &&
        `Step “${failed.title}”, attempt ${failed.attempt}, after ${formatDuration(
          durationMs(failed.started_at, failed.finished_at),
        )}`
      }
      title="Why it failed"
    >
      <div className="flex flex-col gap-4 px-5 pb-5">
        <div className="grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-4">
          <Field label="Reason">
            <span className="text-danger font-mono text-sm break-all">
              {reason}
            </span>
          </Field>
          {output?.outcome && (
            <Field label="Outcome">
              <span className="font-mono text-sm">{output.outcome}</span>
            </Field>
          )}
          {typeof failed?.input?.agent_id === 'string' && (
            <Field label="Agent">
              <span className="font-mono text-sm">{failed.input.agent_id}</span>
            </Field>
          )}
        </div>
        {output?.summary && (
          <div className="bg-secondary flex flex-col gap-2.5 rounded-md px-4 py-4">
            <span className="text-overline text-tertiary uppercase">
              Agent summary
            </span>
            <div className="document-markdown text-sm [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
              <RichMarkdown deferImages>{output.summary}</RichMarkdown>
            </div>
          </div>
        )}
      </div>
    </Card>
  )
}
