import { beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  MaintenanceLogEntry,
  MaintenanceLogPage,
  MaintenanceOperation,
} from '@/api/endpoints'
import { fireEvent, render, screen, waitFor } from '@/test/utils'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  getMaintenanceLog: vi.fn(),
}))

const entry = (
  overrides: Partial<MaintenanceLogEntry> = {},
): MaintenanceLogEntry => ({
  action: '',
  attempt_id: 'attempt1',
  detail: {},
  disposition: 'failed',
  duration_ms: 17,
  event_type: 'attempt',
  id: 'row1',
  item_id: 'p1',
  message: 'Tag resolution failed',
  occurred_at: '2026-08-19T12:00:00Z',
  project_id: 'p1',
  project_slug: 'campaign-builder',
  run_id: 'run1abcdef',
  slug: 'release-repair',
  started_by: 'admin',
  ...overrides,
})

const page = (
  entries: MaintenanceLogEntry[],
  overrides: Partial<MaintenanceLogPage> = {},
): MaintenanceLogPage => ({
  counts: { deferred: 0, failed: 2, skipped: 1, succeeded: 3 },
  entries,
  ...overrides,
})

const operations: MaintenanceOperation[] = [
  {
    label: 'Repair Release Identity',
    running: false,
    slug: 'release-repair',
    state: 'idle',
  },
]

const renderLog = async () => {
  const { MaintenanceActivityLog } = await import('../MaintenanceActivityLog')
  render(<MaintenanceActivityLog operations={operations} />)
}

describe('MaintenanceActivityLog', () => {
  beforeEach(async () => {
    const endpoints = await import('@/api/endpoints')
    // Vitest does not clear mocks between tests here, and several of
    // these assert on `mock.calls[0]` -- a call left over from the
    // previous test would be the one they read.
    vi.clearAllMocks()
    vi.mocked(endpoints.getMaintenanceLog).mockResolvedValue(page([entry()]))
  })

  it('renders one row per attempt', async () => {
    await renderLog()
    await waitFor(() =>
      expect(screen.getByText('campaign-builder')).toBeInTheDocument(),
    )
    expect(screen.getByText('Tag resolution failed')).toBeInTheDocument()
    expect(screen.getByText('release-repair')).toBeInTheDocument()
  })

  it('asks for attempt rows across every disposition by default', async () => {
    const endpoints = await import('@/api/endpoints')
    await renderLog()
    await waitFor(() => expect(endpoints.getMaintenanceLog).toHaveBeenCalled())
    const [args] = vi.mocked(endpoints.getMaintenanceLog).mock.calls[0]
    expect(args.filters?.event_type).toBe('attempt')
    expect(args.filters?.disposition).toBeUndefined()
  })

  it('shows the outcome counts on the filter chips', async () => {
    await renderLog()
    await waitFor(() =>
      expect(screen.getByText(/succeeded 3/)).toBeInTheDocument(),
    )
    expect(screen.getByText(/failed 2/)).toBeInTheDocument()
  })

  it('filters by disposition', async () => {
    const endpoints = await import('@/api/endpoints')
    await renderLog()
    await waitFor(() =>
      expect(screen.getByText(/failed 2/)).toBeInTheDocument(),
    )
    fireEvent.click(screen.getByText(/failed 2/))
    await waitFor(() => {
      const calls = vi.mocked(endpoints.getMaintenanceLog).mock.calls
      expect(calls[calls.length - 1][0].filters?.disposition).toEqual([
        'failed',
      ])
    })
  })

  it('expanding an attempt reads its activity rows', async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.getMaintenanceLog).mockImplementation((params) =>
      Promise.resolve(
        params.filters?.event_type === 'activity'
          ? page([
              entry({
                action: 'normalize',
                disposition: 'succeeded',
                event_type: 'activity',
                id: 'row2',
                message: 'Normalized 2 committishes',
              }),
            ])
          : page([entry()]),
      ),
    )
    await renderLog()
    await waitFor(() =>
      expect(screen.getByText('campaign-builder')).toBeInTheDocument(),
    )
    fireEvent.click(screen.getByRole('button', { expanded: false }))
    await waitFor(() =>
      expect(screen.getByText('Normalized 2 committishes')).toBeInTheDocument(),
    )
    expect(screen.getByText(/17 ms/)).toBeInTheDocument()
  })

  it('offers more only when the server says there is more', async () => {
    const endpoints = await import('@/api/endpoints')
    // Distinct ids per page: React keys rows by id, and reusing one
    // across both pages logs a duplicate-key warning that has nothing
    // to do with what this test asserts.
    vi.mocked(endpoints.getMaintenanceLog)
      .mockResolvedValueOnce(page([entry()], { nextCursor: 'cursor2' }))
      .mockResolvedValueOnce(page([entry({ id: 'row2' })]))
    await renderLog()
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /load more/i }),
      ).toBeInTheDocument(),
    )
    fireEvent.click(screen.getByRole('button', { name: /load more/i }))
    await waitFor(() => {
      const calls = vi.mocked(endpoints.getMaintenanceLog).mock.calls
      expect(calls[calls.length - 1][0].cursor).toBe('cursor2')
    })
  })

  it('reports an empty log rather than an empty table', async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.getMaintenanceLog).mockResolvedValue(page([]))
    await renderLog()
    await waitFor(() =>
      expect(
        screen.getByText(/no maintenance activity recorded/i),
      ).toBeInTheDocument(),
    )
  })

  it('surfaces a failure to load', async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.getMaintenanceLog).mockRejectedValue(
      new Error('clickhouse down'),
    )
    await renderLog()
    await waitFor(() =>
      expect(screen.getByText(/clickhouse down/i)).toBeInTheDocument(),
    )
  })
})
