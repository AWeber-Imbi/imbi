import { portsOf, type StepTypes } from './graph'
import type {
  RunStatus,
  StepRun,
  StepRunStatus,
  TestRunResult,
  WorkflowGraph,
} from './types'

// Pure helpers for runs and test runs (ADR 0021). The panel and the
// inspector show both through one shape, `StepResult`.

type BadgeVariant = 'danger' | 'info' | 'neutral' | 'success' | 'warning'

export const STATUS: Record<
  RunStatus | StepRunStatus,
  { label: string; variant: BadgeVariant }
> = {
  cancelled: { label: 'Cancelled', variant: 'neutral' },
  failed: { label: 'Failed', variant: 'danger' },
  pending: { label: 'Pending', variant: 'neutral' },
  queued: { label: 'Queued', variant: 'neutral' },
  running: { label: 'Running', variant: 'info' },
  skipped: { label: 'Skipped', variant: 'neutral' },
  succeeded: { label: 'Succeeded', variant: 'success' },
  timed_out: { label: 'Timed out', variant: 'warning' },
}

export interface ManualInput {
  name: string
  type: 'boolean' | 'number' | 'string'
}

/** What one step of a run or a test run did. */
export interface StepResult {
  /** The name of the output that the step took, when it has names. */
  branch: null | string
  durationMs: null | number
  error: null | string
  input: null | Record<string, unknown>
  output: null | Record<string, unknown>
  status: StepRunStatus
}

export function durationMs(
  start: null | string | undefined,
  end: null | string | undefined,
): null | number {
  if (!start || !end) return null
  return Math.max(0, Date.parse(end) - Date.parse(start))
}

export function formatDuration(ms: null | number): string {
  if (ms === null) return '—'
  if (ms < 1000) return `${ms} ms`
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s} s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} m ${s % 60} s`
  return `${Math.floor(m / 60)} h ${m % 60} m`
}

export const isOpen = (status: RunStatus) =>
  status === 'queued' || status === 'running'

/** The first manual trigger and the inputs that a run of it needs. */
export function manualTrigger(
  graph: WorkflowGraph,
): null | { id: string; inputs: ManualInput[] } {
  const node = graph.nodes.find((n) => n.type === 'manual')
  if (!node) return null
  const inputs = Array.isArray(node.params.inputs)
    ? (node.params.inputs as Partial<ManualInput>[])
    : []
  return {
    id: node.id,
    inputs: inputs
      .filter((i) => !!i.name)
      .map((i) => ({ name: i.name!, type: i.type ?? 'string' })),
  }
}

/** The step results of a run, by node id. */
export function runResults(
  steps: StepRun[],
  graph: WorkflowGraph,
  types: StepTypes,
): Record<string, StepResult> {
  const nodes = Object.fromEntries(graph.nodes.map((n) => [n.id, n]))
  return Object.fromEntries(
    steps.map((step) => {
      const node = nodes[step.node_id]
      const ports = node ? portsOf(node, types) : []
      return [
        step.node_id,
        {
          branch: step.port === null ? null : ports[step.port] || null,
          durationMs: durationMs(step.started_at, step.finished_at),
          error: step.error,
          input: step.input,
          output: step.output,
          status: step.status,
        },
      ]
    }),
  )
}

/** The step results of a test run, by node id. Skipped nodes included. */
export function testResults(result: TestRunResult): Record<string, StepResult> {
  const found: Record<string, StepResult> = {}
  for (const id of result.skipped) {
    found[id] = {
      branch: null,
      durationMs: null,
      error: null,
      input: null,
      output: null,
      status: 'skipped',
    }
  }
  for (const step of result.steps) {
    found[step.node_id] = {
      branch: step.port_name || null,
      durationMs: null,
      error: null,
      input: null,
      output: step.output,
      status: 'succeeded',
    }
  }
  return found
}
