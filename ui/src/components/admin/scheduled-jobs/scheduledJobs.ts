import { hasPermission } from '@/hooks/useHasPermission'
import { buildDiffPatch } from '@/lib/json-patch'
import type { PatchOperation, UserResponse } from '@/types'
import type {
  ScheduledRun,
  ScheduledRunState,
  ScheduledTask,
  ScheduledTaskCreate,
  Trigger,
} from '@/types/scheduler'

// What the UI shows for a run or a job. `busy` is a `failed` run whose
// target answered 409: the previous run was still active, so the work
// itself did not fail.
export type DisplayState = 'busy' | 'never' | 'paused' | ScheduledRunState

export interface TaskPermissions {
  delete: boolean
  edit: boolean
  readRuns: boolean
  run: boolean
}

export const STATE_LABELS: Record<DisplayState, string> = {
  busy: 'Already running',
  cancelled: 'Cancelled',
  failed: 'Failed',
  never: 'Never run',
  no_effect: 'No effect',
  paused: 'Paused',
  running: 'Running',
  skipped: 'Skipped',
  succeeded: 'Succeeded',
  timed_out: 'Timed out',
}

const HTTP_CONFLICT = 409

export const NO_PERMISSIONS: TaskPermissions = {
  delete: false,
  edit: false,
  readRuns: false,
  run: false,
}

export const CODE_BLOCK =
  'bg-secondary overflow-x-auto rounded-md p-3 font-mono text-xs'

const ADMIN = 'scheduled_task:admin'

// The scheduler refuses a patch to a server-owned field, and a system
// task's target is fixed, so only these fields are ever sent.
const USER_FIELDS = [
  'name',
  'description',
  'trigger',
  'timezone',
  'identity',
  'target',
  'execution',
]
const SYSTEM_FIELDS = ['trigger', 'timezone', 'execution']

const pad = (n: number) => String(n).padStart(2, '0')

// "Every hour" rather than "Every 1 hour".
const every = (parts: string[]) =>
  parts.length === 1 && parts[0].startsWith('1 ')
    ? `Every ${parts[0].slice(2)}`
    : `Every ${parts.join(' ')}`

const plural = (n: number, unit: string) =>
  `${n} ${n === 1 ? unit : `${unit}s`}`

export function buildTaskPatch(
  task: ScheduledTask,
  draft: ScheduledTaskCreate,
): PatchOperation[] {
  return buildDiffPatch(
    task as unknown as Record<string, unknown>,
    draft as unknown as Record<string, unknown>,
    { fields: task.kind === 'system' ? SYSTEM_FIELDS : USER_FIELDS },
  )
}

export function isFailing(state: DisplayState | undefined): boolean {
  return state === 'failed' || state === 'timed_out'
}

// The last-run column. `undefined` runs means the caller cannot read them.
export function jobDisplayState(
  task: ScheduledTask,
  runs: ScheduledRun[] | undefined,
): DisplayState | undefined {
  if (!task.enabled) return 'paused'
  if (!runs) return undefined
  return runs.length ? runDisplayState(runs[0]) : 'never'
}

// The scheduler records the target's status code in `http_status` and only
// the response body in `response_excerpt`, so the 409 is read from there.
export function runDisplayState(run: ScheduledRun): DisplayState {
  return run.state === 'failed' && run.http_status === HTTP_CONFLICT
    ? 'busy'
    : run.state
}

export function targetSummary(task: ScheduledTask): string {
  return task.target.kind === 'api'
    ? `${task.target.method} ${task.target.path}`
    : `gateway → ${task.target.webhook_id}`
}

// Mirrors the scheduler's ownership rule (endpoints/dependencies.py): a
// caller manages the user tasks they created; anything else, system tasks
// included, needs scheduled_task:admin.
export function taskPermissions(
  user: null | undefined | UserResponse,
  task: ScheduledTask,
): TaskPermissions {
  const manage =
    hasPermission(user, ADMIN) ||
    (task.kind === 'user' && !!user && task.created_by === user.email)
  const can = (permission: string) =>
    manage && hasPermission(user, `scheduled_task:${permission}`)
  return {
    delete: can('delete'),
    edit: can('write'),
    readRuns: can('read'),
    run: can('run'),
  }
}

// A one-line, human summary of a trigger.
export function triggerSummary(trigger: Trigger): string {
  switch (trigger.kind) {
    case 'calendar': {
      const at = trigger.at_time.slice(0, 5)
      const parts = [
        trigger.months ? plural(trigger.months, 'month') : '',
        trigger.weeks ? plural(trigger.weeks, 'week') : '',
        trigger.days ? plural(trigger.days, 'day') : '',
      ].filter(Boolean)
      return `${every(parts)} at ${at}`
    }
    case 'cron':
      return cronSummary(trigger.expression)
    case 'date':
      return `Once at ${trigger.run_at.replace('T', ' ').slice(0, 16)} UTC`
    case 'interval': {
      const parts = (['days', 'hours', 'minutes', 'seconds'] as const)
        .filter((unit) => trigger[unit])
        .map((unit) => plural(trigger[unit]!, unit.slice(0, -1)))
      return every(parts)
    }
  }
}

function cronSummary(expression: string): string {
  const [minute, hour, dom, month, dow, extra] = expression.split(/\s+/)
  const fixed = (v: string) => /^\d+$/.test(v)
  if (extra === undefined && dom === '*' && month === '*') {
    if (fixed(minute) && fixed(hour)) {
      const at = `${pad(+hour)}:${pad(+minute)}`
      if (dow === '*') return `Daily at ${at}`
      if (dow === '1-5') return `Weekdays at ${at}`
    }
    if (fixed(minute) && hour === '*' && dow === '*') {
      return `Hourly at :${pad(+minute)}`
    }
  }
  return expression
}
