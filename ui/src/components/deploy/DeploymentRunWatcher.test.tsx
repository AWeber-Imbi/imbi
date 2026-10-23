import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import type { DeploymentRun } from '@/types'

import { DeploymentRunWatcher } from './DeploymentRunWatcher'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/endpoints')>('@/api/endpoints')
  return {
    ...actual,
    getDeploymentRunStatus: vi.fn(),
  }
})

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    loading: vi.fn(),
    message: vi.fn(),
    success: vi.fn(),
  },
}))

// The watcher is a render-nothing side-effect component, but it lives
// inside ``useQuery`` so we need a real QueryClient to drive it.
function renderWatcher(
  props: Partial<{
    actionLabel: string
    actionUrl: null | string
    initialStatus: DeploymentRun['status']
    onTerminal: (id: string) => void
    runId: string
    runUrl: null | string
    toastId: string
  }> = {},
) {
  const onTerminal = props.onTerminal ?? vi.fn()
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const utils = render(
    <QueryClientProvider client={client}>
      <DeploymentRunWatcher
        actionLabel={props.actionLabel}
        actionUrl={props.actionUrl ?? null}
        envName="staging"
        initialStatus={props.initialStatus}
        onTerminal={onTerminal}
        orgSlug="acme"
        projectId="p1"
        runId={props.runId ?? 'run-42'}
        runUrl={props.runUrl ?? null}
        toastId={props.toastId ?? 'toast-1'}
      />
    </QueryClientProvider>,
  )
  return { ...utils, client, onTerminal }
}

describe('DeploymentRunWatcher', () => {
  let getDeploymentRunStatus: ReturnType<typeof vi.fn>
  let toast: {
    error: ReturnType<typeof vi.fn>
    loading: ReturnType<typeof vi.fn>
    message: ReturnType<typeof vi.fn>
    success: ReturnType<typeof vi.fn>
  }

  beforeEach(async () => {
    getDeploymentRunStatus = vi.mocked(endpoints.getDeploymentRunStatus)
    const sonner = await import('sonner')
    toast = sonner.toast as unknown as typeof toast
    getDeploymentRunStatus.mockReset()
    toast.error.mockReset()
    toast.loading.mockReset()
    toast.message.mockReset()
    toast.success.mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders nothing', async () => {
    getDeploymentRunStatus.mockResolvedValue({
      run_id: 'run-42',
      run_url: null,
      status: 'in_progress',
    } satisfies DeploymentRun)
    const { container } = renderWatcher()
    expect(container.firstChild).toBeNull()
  })

  it('flips the toast to success on terminal status', async () => {
    getDeploymentRunStatus.mockResolvedValue({
      run_id: 'run-42',
      run_url: 'https://gh/runs/42',
      status: 'success',
    } satisfies DeploymentRun)
    const { onTerminal } = renderWatcher({ runUrl: 'https://gh/runs/42' })
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalled()
      expect(onTerminal).toHaveBeenCalledWith('run-42')
    })
    const call = toast.success.mock.calls[0]
    expect(call[0]).toMatch(/Deployed to staging/)
    expect(call[1].id).toBe('toast-1')
  })

  it('flips the toast to error on failure', async () => {
    getDeploymentRunStatus.mockResolvedValue({
      run_id: 'run-42',
      run_url: null,
      status: 'failure',
    } satisfies DeploymentRun)
    const { onTerminal } = renderWatcher()
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalled()
      expect(onTerminal).toHaveBeenCalledWith('run-42')
    })
    const call = toast.error.mock.calls[0]
    expect(call[0]).toMatch(/failed/)
  })

  it('flips the toast to error on cancelled', async () => {
    getDeploymentRunStatus.mockResolvedValue({
      run_id: 'run-42',
      run_url: null,
      status: 'cancelled',
    } satisfies DeploymentRun)
    const { onTerminal } = renderWatcher()
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalled()
      expect(onTerminal).toHaveBeenCalledWith('run-42')
    })
    const call = toast.error.mock.calls[0]
    expect(call[0]).toMatch(/cancelled/)
  })

  it('keeps loading toast for in_progress', async () => {
    getDeploymentRunStatus.mockResolvedValue({
      run_id: 'run-42',
      run_url: null,
      status: 'in_progress',
    } satisfies DeploymentRun)
    const { onTerminal } = renderWatcher()
    await waitFor(() => {
      expect(toast.loading).toHaveBeenCalled()
    })
    expect(onTerminal).not.toHaveBeenCalled()
    const call = toast.loading.mock.calls[0]
    expect(call[0]).toMatch(/Deploying to staging/)
    expect(call[1].id).toBe('toast-1')
  })

  it('prefers actionUrl over runUrl for the toast action', async () => {
    getDeploymentRunStatus.mockResolvedValue({
      run_id: 'run-42',
      run_url: 'https://gh/runs/42',
      status: 'success',
    } satisfies DeploymentRun)
    renderWatcher({
      actionLabel: 'View release',
      actionUrl: 'https://gh/releases/v1',
      runUrl: 'https://gh/runs/42',
    })
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalled()
    })
    const opts = toast.success.mock.calls[0][1]
    expect(opts.action.label).toBe('View release')
    // ``onClick`` should open the actionUrl, not the runUrl.
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
    opts.action.onClick()
    expect(openSpy).toHaveBeenCalledWith(
      'https://gh/releases/v1',
      '_blank',
      'noopener',
    )
  })
})
