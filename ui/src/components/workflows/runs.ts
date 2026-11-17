import { portsOf, type StepTypes } from './graph'
import type {
  OrgRun,
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

/** The runs that failed with one reason. */
export interface FailureCause {
  count: number
  /** When the newest run with the reason started. */
  last: string
  outcome: null | string
  reason: string
  /** The failed steps, by title, with a count when there are more. */
  steps: string
  workflows: string[]
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

/** The failed runs of a workflow. */
export interface WorkflowFailures {
  failed: number
  /** How many other reasons than the top one. */
  others: number
  top: string
  topCount: number
  /** Runs that were not skipped. */
  total: number
}

/** The id of the earlier run that a skipped run repeats. */
export function duplicateOf(run: {
  duplicate_of: null | string
  status: RunStatus
}): null | string {
  return run.status === 'skipped' ? run.duplicate_of : null
}

export function durationMs(
  start: null | string | undefined,
  end: null | string | undefined,
): null | number {
  if (!start || !end) return null
  return Math.max(0, Date.parse(end) - Date.parse(start))
}

/** Failed runs grouped by reason, the most frequent first. */
export function failureCauses(runs: OrgRun[]): FailureCause[] {
  const found = new Map<
    string,
    FailureCause & { titles: Map<string, number> }
  >()
  for (const run of runs) {
    const reason = failureReason(run)
    if (!reason) continue
    const cause = found.get(reason) ?? {
      count: 0,
      last: run.created_at,
      outcome: run.failure?.outcome ?? null,
      reason,
      steps: '',
      titles: new Map<string, number>(),
      workflows: [],
    }
    cause.count += 1
    if (run.created_at > cause.last) cause.last = run.created_at
    if (!cause.workflows.includes(run.workflow_name)) {
      cause.workflows.push(run.workflow_name)
    }
    const title = run.failure?.title
    if (title) cause.titles.set(title, (cause.titles.get(title) ?? 0) + 1)
    found.set(reason, cause)
  }
  return [...found.values()]
    .map(({ titles, ...cause }) => ({
      ...cause,
      steps: [...titles]
        .map(([title, n]) => (titles.size > 1 ? `${title} ×${n}` : title))
        .join(', '),
    }))
    .sort((a, b) => b.count - a.count || b.last.localeCompare(a.last))
}

/**
 * Why a run failed: the reason of the agent task of the failed step,
 * the error of the step, or the error of the run. `null` for a run
 * that did not fail.
 */
export function failureReason(run: {
  error: null | string
  failure?: null | { error: null | string; reason?: null | string }
  status: RunStatus
}): null | string {
  if (!isFailed(run.status)) return null
  return run.failure?.reason ?? run.failure?.error ?? run.error ?? run.status
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

export const isFailed = (status: RunStatus) =>
  status === 'failed' || status === 'timed_out'

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

/** Who or what started a run. */
export function originLabel(run: {
  origin: Record<string, unknown>
  origin_id: string
  origin_kind: string
}): string {
  if (run.origin_kind === 'human') {
    return `Manual run by ${String(run.origin.user ?? run.origin_id)}`
  }
  if (run.origin_kind === 'schedule') return 'Scheduled run'
  if (run.origin_kind === 'webhook') return 'Webhook run'
  return run.origin_kind
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

const DAY_SECONDS = 86400

/** A dedupe window in days for the settings form. Empty: no limit. */
export function windowDays(seconds: null | number | undefined): string {
  return seconds ? String(seconds / DAY_SECONDS) : ''
}

/**
 * The dedupe window in seconds of what the form holds: `null` for an
 * empty field, `undefined` for a value that is not a positive number.
 */
export function windowSeconds(days: string): null | number | undefined {
  if (days.trim() === '') return null
  const value = Number(days)
  if (!(value > 0)) return undefined
  return Math.max(1, Math.round(value * DAY_SECONDS))
}

/** The failed runs of each workflow, by slug. Skipped runs not counted. */
export function workflowFailures(
  runs: OrgRun[],
): Record<string, WorkflowFailures> {
  // A Map: a slug such as `constructor` must not find an inherited value.
  const bySlug = new Map<string, OrgRun[]>()
  for (const run of runs) {
    if (run.status !== 'skipped') {
      const mine = bySlug.get(run.workflow_slug) ?? []
      mine.push(run)
      bySlug.set(run.workflow_slug, mine)
    }
  }
  // Prototype-free, so that a lookup by such a slug finds nothing.
  const found: Record<string, WorkflowFailures> = Object.create(null)
  for (const [slug, mine] of bySlug) {
    const causes = failureCauses(mine)
    if (causes.length === 0) continue
    found[slug] = {
      failed: causes.reduce((n, c) => n + c.count, 0),
      others: causes.length - 1,
      top: causes[0].reason,
      topCount: causes[0].count,
      total: mine.length,
    }
  }
  return found
}
