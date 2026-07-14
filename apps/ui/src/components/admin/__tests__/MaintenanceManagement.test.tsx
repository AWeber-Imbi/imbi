import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import type { MaintenanceOperation } from '@/api/endpoints'
import { fireEvent, render, screen, waitFor, within } from '@/test/utils'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  cancelMaintenanceOperation: vi.fn(),
  getMaintenanceOperations: vi.fn(),
  runMaintenanceOperation: vi.fn(),
}))

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    info: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}))

const operation = (
  overrides: Partial<MaintenanceOperation> = {},
): MaintenanceOperation => ({
  description: 'Does a thing to every project.',
  label: 'Do Thing',
  running: false,
  slug: 'do-thing',
  state: 'idle',
  ...overrides,
})

// Render, wait for the registry rows, click the first Run button, and
// return the opened confirmation dialog.
const openRunConfirmation = async () => {
  const { MaintenanceManagement } = await import('../MaintenanceManagement')
  render(<MaintenanceManagement />)
  await waitFor(() => expect(screen.getByText('Do Thing')).toBeInTheDocument())
  fireEvent.click(screen.getAllByRole('button', { name: /run/i })[0])
  return screen.findByRole('alertdialog')
}

describe('MaintenanceManagement', () => {
  beforeEach(async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.getMaintenanceOperations).mockResolvedValue([
      operation(),
      operation({
        description: 'Other global operation.',
        label: 'Other Thing',
        slug: 'other-thing',
      }),
    ])
  })

  it('renders one row per registry operation', async () => {
    const { MaintenanceManagement } = await import('../MaintenanceManagement')
    render(<MaintenanceManagement />)
    await waitFor(() =>
      expect(screen.getByText('Do Thing')).toBeInTheDocument(),
    )
    expect(screen.getByText('Other Thing')).toBeInTheDocument()
    expect(screen.getByText('Other global operation.')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /run/i })).toHaveLength(2)
  })

  it('shows an empty state when the registry is empty', async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.getMaintenanceOperations).mockResolvedValue([])
    const { MaintenanceManagement } = await import('../MaintenanceManagement')
    render(<MaintenanceManagement />)
    await waitFor(() =>
      expect(
        screen.getByText('No maintenance operations are available.'),
      ).toBeInTheDocument(),
    )
  })

  it('shows an error banner when the registry fetch fails', async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.getMaintenanceOperations).mockRejectedValue(
      new Error('boom'),
    )
    const { MaintenanceManagement } = await import('../MaintenanceManagement')
    render(<MaintenanceManagement />)
    await waitFor(() => expect(screen.getByText('boom')).toBeInTheDocument())
  })

  it('confirms before starting a run', async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.runMaintenanceOperation).mockResolvedValue({
      run_id: 'r1',
      total: 5,
    })
    const dialog = await openRunConfirmation()
    expect(within(dialog).getByText('Run Do Thing?')).toBeInTheDocument()
    expect(endpoints.runMaintenanceOperation).not.toHaveBeenCalled()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Run' }))
    await waitFor(() =>
      expect(endpoints.runMaintenanceOperation).toHaveBeenCalledWith(
        'do-thing',
      ),
    )
  })

  it('renders progress and disables Run while running', async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.getMaintenanceOperations).mockResolvedValue([
      operation({
        progress: {
          failed: 1,
          in_flight: 1,
          remaining: 3,
          skipped: 0,
          succeeded: 6,
          total: 10,
        },
        running: true,
        started_at: '2026-07-13T00:00:00Z',
        started_by: 'admin@example.com',
        state: 'running',
      }),
    ])
    const { MaintenanceManagement } = await import('../MaintenanceManagement')
    render(<MaintenanceManagement />)
    await waitFor(() =>
      expect(screen.getByText('7 of 10 — 3 remaining')).toBeInTheDocument(),
    )
    expect(screen.getByText('1 failed')).toBeInTheDocument()
    expect(screen.getByText(/by admin@example\.com/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /run/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument()
  })

  it('tolerates a running operation without progress', async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.getMaintenanceOperations).mockResolvedValue([
      operation({ running: true, state: 'running' }),
    ])
    const { MaintenanceManagement } = await import('../MaintenanceManagement')
    render(<MaintenanceManagement />)
    await waitFor(() => expect(screen.getByText('Running')).toBeInTheDocument())
  })

  it('toasts info when the run 409s', async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.runMaintenanceOperation).mockRejectedValue(
      new ApiError(409, 'Conflict', { detail: 'already running' }),
    )
    const dialog = await openRunConfirmation()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Run' }))
    const { toast } = await import('sonner')
    await waitFor(() =>
      expect(toast.info).toHaveBeenCalledWith(
        'That operation is already running',
      ),
    )
  })
})
