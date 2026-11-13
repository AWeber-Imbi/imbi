import { describe, expect, it, vi } from 'vitest'

import { render, screen, waitFor } from '@/test/utils'
import type { ScheduledRun, ScheduledTask } from '@/types/scheduler'

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ user: { email: 'me@example.com', is_admin: true } }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/scheduler', () => ({
  listScheduledTaskRuns: vi.fn(),
  listScheduledTasks: vi.fn(),
  pauseScheduledTask: vi.fn(),
  resumeScheduledTask: vi.fn(),
}))

const base = {
  created_at: '2026-11-13T00:00:00Z',
  created_by: 'imbi-scheduler',
  description: null,
  execution: {
    max_running_instances: 1,
    misfire_grace_time: 300,
    retries: 0,
    retry_backoff: 'exponential',
    timeout: 120,
  },
  identity: { kind: 'service_account', subject: 'imbi-scheduler' },
  last_run_at: null,
  next_run_at: '2026-11-13T18:00:00Z',
  timezone: 'UTC',
  updated_at: '2026-11-13T00:00:00Z',
  updated_by: null,
} as const

const tasks: ScheduledTask[] = [
  {
    ...base,
    enabled: true,
    id: '1',
    kind: 'system',
    name: 'Sync agent marketplaces',
    slug: 'marketplace-sync',
    target: {
      kind: 'api',
      method: 'POST',
      path: '/maintenance/operations/marketplace-sync/run',
    },
    trigger: { hours: 6, kind: 'interval' },
  },
  {
    ...base,
    enabled: false,
    id: '2',
    kind: 'user',
    name: 'Weekly scoring webhook',
    slug: 'weekly-scoring',
    target: { kind: 'gateway', payload: {}, webhook_id: 'nightly-scoring' },
    trigger: { expression: '0 2 * * 1-5', kind: 'cron' },
  },
]

const busyRun: ScheduledRun = {
  attempt: 1,
  duration_ms: 120,
  error_message: '',
  error_type: 'http_409',
  finished_at: '2026-11-13T14:00:01Z',
  fired_at: '2026-11-13T14:00:00Z',
  http_status: 409,
  response_excerpt: '{"detail":"Marketplace Sync is already running."}',
  run_id: 'r1',
  state: 'failed',
  task_slug: 'marketplace-sync',
}

describe('ScheduledJobsManagement list', () => {
  it('renders jobs with schedule, system badge, and last state', async () => {
    const api = await import('@/api/scheduler')
    vi.mocked(api.listScheduledTasks).mockResolvedValue(tasks)
    vi.mocked(api.listScheduledTaskRuns).mockImplementation(async (slug) =>
      slug === 'marketplace-sync' ? [busyRun] : [],
    )
    const { ScheduledJobsManagement } =
      await import('../ScheduledJobsManagement')
    render(<ScheduledJobsManagement />)

    await waitFor(() =>
      expect(screen.getByText('Sync agent marketplaces')).toBeInTheDocument(),
    )
    expect(screen.getByText('system')).toBeInTheDocument()
    expect(screen.getByText('Every 6 hours')).toBeInTheDocument()
    expect(screen.getByText('Weekdays at 02:00')).toBeInTheDocument()
    expect(screen.getByText('gateway → nightly-scoring')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getAllByText('Already running').length).toBeGreaterThan(0),
    )
    // The paused job shows Paused in the next-run and last-run columns.
    expect(screen.getAllByText('Paused').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /new job/i })).toBeInTheDocument()
  })
})
