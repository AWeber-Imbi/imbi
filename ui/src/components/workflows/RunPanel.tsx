import { type ReactNode, useState } from 'react'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ChevronDown, ChevronUp } from 'lucide-react'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import { cancelWorkflowRun } from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { extractApiErrorDetail } from '@/lib/apiError'
import { queryKeys } from '@/lib/queryKeys'
import { cn } from '@/lib/utils'

import type { StepTypes } from './graph'
import {
  durationMs,
  formatDuration,
  isOpen,
  STATUS,
  type StepResult,
} from './runs'
import type {
  RunStatus,
  StepRunStatus,
  TestRunResult,
  WorkflowRunDetail,
} from './types'
import { useWorkflowRuns } from './workflowQueries'

export type PanelTab = 'runs' | 'test'

interface RunPanelProps {
  canRun: boolean
  onClearTest: () => void
  onRunId: (id: null | string) => void
  onSelectNode: (id: string) => void
  onTab: (tab: PanelTab) => void
  onToggle: () => void
  open: boolean
  orgSlug: string
  /** Step results of the run or the test run on show, by node id. */
  results: Record<string, StepResult>
  /** The run that `runId` names, while it loads `undefined`. */
  run: undefined | WorkflowRunDetail
  runId: null | string
  slug: string | undefined
  tab: PanelTab
  testPending: boolean
  testRun: null | TestRunResult
  types: StepTypes
}

/** The bottom panel of the editor: the test run log and the run history. */
export function RunPanel(props: RunPanelProps) {
  const { onTab, onToggle, open, tab } = props
  const Chevron = open ? ChevronDown : ChevronUp
  return (
    <div className="border-tertiary bg-primary shrink-0 border-t">
      <div className="flex h-10 items-center gap-1 px-2.5">
        <button
          aria-label={open ? 'Close the run panel' : 'Open the run panel'}
          className="text-secondary hover:bg-secondary flex size-7 items-center justify-center rounded-md"
          onClick={onToggle}
          type="button"
        >
          <Chevron className="size-3.5" />
        </button>
        <TabButton
          active={open && tab === 'test'}
          label="Test log"
          onClick={() => onTab('test')}
        />
        <TabButton
          active={open && tab === 'runs'}
          label="Runs"
          onClick={() => onTab('runs')}
        />
        <span className="text-tertiary ml-2 min-w-0 flex-1 truncate text-xs">
          {tab === 'test' ? testSummary(props) : runSummary(props)}
        </span>
        <PanelActions {...props} />
      </div>
      {open && (
        <div className="border-tertiary h-45 overflow-auto border-t">
          {tab === 'test' ? (
            <TestLog {...props} />
          ) : props.runId ? (
            <RunSteps {...props} />
          ) : (
            <RunList {...props} />
          )}
        </div>
      )}
    </div>
  )
}

export function StatusBadge({ status }: { status: RunStatus | StepRunStatus }) {
  const { label, variant } = STATUS[status]
  return (
    <Badge className="justify-self-start" variant={variant}>
      {label}
    </Badge>
  )
}

function branchLabel(result: StepResult | undefined): string {
  return result?.branch ? `→ ${result.branch}` : ''
}

function Duration({ ms }: { ms: null | number }) {
  return (
    <span className="text-tertiary text-right font-mono text-xs">
      {formatDuration(ms)}
    </span>
  )
}

function Empty({ children }: { children: ReactNode }) {
  return <div className="text-tertiary p-7 text-center text-sm">{children}</div>
}

function PanelActions({
  canRun,
  onClearTest,
  onRunId,
  orgSlug,
  run,
  runId,
  slug,
  tab,
  testRun,
}: RunPanelProps) {
  const queryClient = useQueryClient()
  // The API refuses a cancel (403) when the run's trigger does not let
  // this person cancel it. Hide the button for that run after.
  const [refused, setRefused] = useState<null | string>(null)
  const cancel = useMutation({
    mutationFn: () => cancelWorkflowRun(orgSlug, slug!, runId!),
    onError: (error) => {
      if (error instanceof ApiError && error.status === 403) {
        setRefused(runId)
        toast.error(
          `You cannot cancel this run: ${extractApiErrorDetail(error)}`,
        )
        return
      }
      toast.error(`Failed to cancel the run: ${extractApiErrorDetail(error)}`)
    },
    onSuccess: () => {
      toast.success('Cancel requested. The run stops before its next step.')
      void queryClient.invalidateQueries({
        queryKey: queryKeys.workflowRuns(orgSlug, slug!),
      })
    },
  })
  if (tab === 'test') {
    return testRun ? (
      <SmallButton onClick={onClearTest}>Clear</SmallButton>
    ) : null
  }
  if (!runId) return null
  return (
    <>
      {canRun && run && isOpen(run.status) && refused !== run.id && (
        <SmallButton
          danger
          disabled={run.cancel_requested || cancel.isPending}
          onClick={() => cancel.mutate()}
        >
          {run.cancel_requested ? 'Cancelling…' : 'Cancel run'}
        </SmallButton>
      )}
      <SmallButton onClick={() => onRunId(null)}>
        <ArrowLeft className="size-3" />
        All runs
      </SmallButton>
    </>
  )
}

function Row({
  children,
  onClick,
}: {
  children: ReactNode
  onClick: () => void
}) {
  return (
    <button
      className="border-tertiary hover:bg-secondary grid w-full grid-cols-[96px_minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)_96px] items-center gap-3 border-b px-4 py-2 text-left text-sm"
      onClick={onClick}
      type="button"
    >
      {children}
    </button>
  )
}

function RunList({ onRunId, open, orgSlug, slug, tab }: RunPanelProps) {
  const runs = useWorkflowRuns(orgSlug, slug, open && tab === 'runs')
  if (!slug) return <Empty>Save the workflow before you run it.</Empty>
  if (runs.isLoading) return <Empty>Loading runs…</Empty>
  if (runs.error) {
    return (
      <Empty>Failed to load runs: {extractApiErrorDetail(runs.error)}</Empty>
    )
  }
  if (!runs.data?.length) {
    return <Empty>No runs yet. Use Run to start one.</Empty>
  }
  return runs.data.map((run) => (
    <Row key={run.id} onClick={() => onRunId(run.id)}>
      <StatusBadge status={run.status} />
      <span className="truncate font-mono text-xs">{run.id.slice(0, 8)}</span>
      <span className="text-tertiary truncate">
        <RelativeTime value={run.created_at} /> · {run.origin_id}
      </span>
      <span className="text-danger truncate">{run.error}</span>
      <Duration
        ms={durationMs(run.started_at ?? run.created_at, run.closed_at)}
      />
    </Row>
  ))
}

function RunSteps({ onSelectNode, results, run, types }: RunPanelProps) {
  if (!run) return <Empty>Loading the run…</Empty>
  return (
    <>
      {run.error && (
        <div className="bg-danger text-danger px-4 py-2 text-xs">
          The run {STATUS[run.status].label.toLowerCase()}: {run.error}
        </div>
      )}
      {run.steps.length === 0 && (
        <Empty>
          {run.status === 'queued'
            ? 'Waiting for the workflow engine to start this run.'
            : 'This run has no steps.'}
        </Empty>
      )}
      {run.steps.map((step) => (
        <Row key={step.node_id} onClick={() => onSelectNode(step.node_id)}>
          <StatusBadge status={step.status} />
          <span className="truncate font-medium">{step.title}</span>
          <span className="text-tertiary truncate">
            {types[step.node_type]?.label ?? step.node_type}
            {step.attempt > 1 && ` · attempt ${step.attempt}`}
          </span>
          <span
            className={cn(
              'truncate',
              step.error ? 'text-danger' : 'text-secondary',
            )}
          >
            {step.error ?? branchLabel(results[step.node_id])}
          </span>
          <Duration ms={results[step.node_id]?.durationMs ?? null} />
        </Row>
      ))}
    </>
  )
}

function runSummary({ run, runId }: RunPanelProps): string {
  if (!runId) return 'Runs of the active version, newest first.'
  if (!run) return 'Loading the run…'
  const label = `Run ${run.id.slice(0, 8)} · v${run.version} · ${STATUS[run.status].label}`
  return run.log_archived_at ? `${label} · from the archive` : label
}

function SmallButton({
  children,
  danger,
  disabled,
  onClick,
}: {
  children: ReactNode
  danger?: boolean
  disabled?: boolean
  onClick: () => void
}) {
  return (
    <button
      className={cn(
        'border-tertiary hover:bg-secondary flex h-7 items-center gap-1 rounded-md border px-2.5 text-xs disabled:opacity-50',
        danger && 'text-danger',
      )}
      disabled={disabled}
      onClick={onClick}
      type="button"
    >
      {children}
    </button>
  )
}

function TabButton({
  active,
  label,
  onClick,
}: {
  active: boolean
  label: string
  onClick: () => void
}) {
  return (
    <button
      className={cn(
        'h-10 border-b-2 px-2 text-sm font-medium',
        active
          ? 'text-primary border-amber-border'
          : 'text-tertiary hover:text-primary border-transparent',
      )}
      onClick={onClick}
      type="button"
    >
      {label}
    </button>
  )
}

function TestLog({ onSelectNode, testPending, testRun, types }: RunPanelProps) {
  if (!testRun) {
    return (
      <Empty>
        {testPending
          ? 'Starting…'
          : 'No test run yet. Test run walks the saved workflow with sample output. It sends and deploys nothing.'}
      </Empty>
    )
  }
  return testRun.steps.map((step) => (
    <Row key={step.node_id} onClick={() => onSelectNode(step.node_id)}>
      <StatusBadge status="succeeded" />
      <span className="truncate font-medium">{step.title}</span>
      <span className="text-tertiary truncate">
        {types[step.type]?.label ?? step.type}
      </span>
      <span className="text-secondary truncate">
        {step.port_name ? `→ ${step.port_name}` : ''}
      </span>
      <span className="text-tertiary text-right font-mono text-xs">sample</span>
    </Row>
  ))
}

function testSummary({ testPending, testRun }: RunPanelProps): string {
  if (testPending) return 'Running the test…'
  if (!testRun) return 'Walks the saved workflow. Nothing is sent or deployed.'
  return `Test run finished · ${testRun.steps.length} steps ran · ${testRun.skipped.length} skipped`
}
