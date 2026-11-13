import { describe, expect, it } from 'vitest'

import type { UserResponse } from '@/types'
import type { ScheduledRun, ScheduledTask } from '@/types/scheduler'

import {
  buildTaskPatch,
  runDisplayState,
  taskPermissions,
  triggerSummary,
} from '../scheduled-jobs/scheduledJobs'

const task = (overrides: Partial<ScheduledTask> = {}): ScheduledTask => ({
  created_at: '2026-11-13T00:00:00Z',
  created_by: 'owner@example.com',
  description: null,
  enabled: true,
  execution: {
    max_running_instances: 1,
    misfire_grace_time: 300,
    retries: 0,
    retry_backoff: 'exponential',
    timeout: 120,
  },
  id: '00000000-0000-0000-0000-000000000001',
  identity: { kind: 'service_account', subject: 'imbi-scheduler' },
  kind: 'user',
  last_run_at: null,
  name: 'Job',
  next_run_at: null,
  slug: 'job',
  target: { kind: 'api', method: 'POST', path: '/x' },
  timezone: 'UTC',
  trigger: { expression: '0 6 * * *', kind: 'cron' },
  updated_at: '2026-11-13T00:00:00Z',
  updated_by: null,
  ...overrides,
})

const run = (overrides: Partial<ScheduledRun>): ScheduledRun => ({
  attempt: 1,
  duration_ms: 10,
  error_message: '',
  error_type: '',
  finished_at: null,
  fired_at: '2026-11-13T00:00:00Z',
  http_status: 0,
  response_excerpt: '',
  run_id: 'r1',
  state: 'succeeded',
  task_slug: 'job',
  ...overrides,
})

const user = (permissions: string[], email = 'me@example.com') =>
  ({ email, is_admin: false, permissions }) as unknown as UserResponse

describe('triggerSummary', () => {
  it.each([
    [{ expression: '30 1 * * *', kind: 'cron' }, 'Daily at 01:30'],
    [{ expression: '0 2 * * 1-5', kind: 'cron' }, 'Weekdays at 02:00'],
    [{ expression: '15 * * * *', kind: 'cron' }, 'Hourly at :15'],
    [{ expression: '0 0 1 * *', kind: 'cron' }, '0 0 1 * *'],
    [{ hours: 6, kind: 'interval', minutes: 0 }, 'Every 6 hours'],
    [{ hours: 1, kind: 'interval' }, 'Every hour'],
    [{ hours: 1, kind: 'interval', minutes: 30 }, 'Every 1 hour 30 minutes'],
    [
      { at_time: '09:00:00', kind: 'calendar', months: 1 },
      'Every month at 09:00',
    ],
    [
      { at_time: '09:00', kind: 'calendar', weeks: 2 },
      'Every 2 weeks at 09:00',
    ],
    [
      { kind: 'date', run_at: '2026-11-14T09:00:00Z' },
      'Once at 2026-11-14 09:00 UTC',
    ],
  ] as const)('%j -> %s', (trigger, expected) => {
    expect(triggerSummary(trigger)).toBe(expected)
  })
})

describe('runDisplayState', () => {
  it('shows a failed 409 as already running', () => {
    expect(runDisplayState(run({ http_status: 409, state: 'failed' }))).toBe(
      'busy',
    )
  })

  it('keeps other failures as failed', () => {
    expect(runDisplayState(run({ http_status: 500, state: 'failed' }))).toBe(
      'failed',
    )
    expect(runDisplayState(run({ state: 'timed_out' }))).toBe('timed_out')
  })
})

describe('taskPermissions', () => {
  const all = ['read', 'write', 'delete', 'run'].map(
    (p) => `scheduled_task:${p}`,
  )

  it('lets an owner manage their own user task', () => {
    const can = taskPermissions(user(all, 'owner@example.com'), task())
    expect(can).toEqual({ delete: true, edit: true, readRuns: true, run: true })
  })

  it('hides actions the owner lacks a permission for', () => {
    const can = taskPermissions(
      user(['scheduled_task:read'], 'owner@example.com'),
      task(),
    )
    expect(can).toEqual({
      delete: false,
      edit: false,
      readRuns: true,
      run: false,
    })
  })

  it('refuses other principals’ tasks and system tasks without admin', () => {
    const none = { delete: false, edit: false, readRuns: false, run: false }
    expect(taskPermissions(user(all), task())).toEqual(none)
    expect(
      taskPermissions(user(all, 'owner@example.com'), task({ kind: 'system' })),
    ).toEqual(none)
  })

  it('lets scheduled_task:admin manage system tasks', () => {
    const can = taskPermissions(
      user([...all, 'scheduled_task:admin']),
      task({ kind: 'system' }),
    )
    expect(can.edit && can.readRuns && can.run && can.delete).toBe(true)
  })
})

describe('buildTaskPatch', () => {
  it('sends nothing when nothing changed', () => {
    const t = task()
    expect(buildTaskPatch(t, { ...t })).toEqual([])
  })

  it('replaces only the changed editable fields', () => {
    const t = task()
    expect(
      buildTaskPatch(t, {
        ...t,
        name: 'Renamed',
        timezone: 'Europe/London',
      }),
    ).toEqual([
      { op: 'replace', path: '/name', value: 'Renamed' },
      { op: 'replace', path: '/timezone', value: 'Europe/London' },
    ])
  })

  it('never patches the target or name of a system task', () => {
    const t = task({ kind: 'system' })
    const trigger = { hours: 2, kind: 'interval' } as const
    expect(
      buildTaskPatch(t, {
        ...t,
        name: 'Renamed',
        target: { kind: 'api', method: 'GET', path: '/y' },
        trigger,
      }),
    ).toEqual([{ op: 'replace', path: '/trigger', value: trigger }])
  })
})
