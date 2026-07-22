import type { ReactNode } from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { toast } from 'sonner'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import type { DeploymentSyncStatus } from '@/api/endpoints'
import { DEEP_RESYNC_LIMIT } from '@/lib/resync'

import { useProjectDeploymentResync } from '../useDeploymentResync'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/endpoints')>('@/api/endpoints')
  return {
    ...actual,
    getProjectDeploymentSyncStatus: vi.fn(),
    resyncProjectDeployments: vi.fn(),
  }
})

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), info: vi.fn(), success: vi.fn(), warning: vi.fn() },
}))

function makeClient() {
  return new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { gcTime: 0, retry: false },
    },
  })
}

function makeWrapper(client: QueryClient = makeClient()) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
}

function status(
  overrides: Partial<DeploymentSyncStatus> = {},
): DeploymentSyncStatus {
  return {
    error: null,
    errors: null,
    events_recorded: null,
    last_synced_at: null,
    observed: null,
    releases_created: null,
    releases_updated: null,
    requested_by: null,
    status: 'idle',
    ...overrides,
  }
}

describe('useProjectDeploymentResync', () => {
  beforeEach(() => vi.clearAllMocks())

  it('requests a deep backfill so historical attribution is re-resolved', async () => {
    vi.mocked(endpoints.getProjectDeploymentSyncStatus).mockResolvedValue(
      status(),
    )
    vi.mocked(endpoints.resyncProjectDeployments).mockResolvedValue({
      enqueued: true,
    })
    const { result } = renderHook(
      () => useProjectDeploymentResync('acme', 'p1'),
      { wrapper: makeWrapper() },
    )
    await act(async () => {
      result.current.sync()
    })
    await waitFor(() =>
      expect(endpoints.resyncProjectDeployments).toHaveBeenCalledWith(
        'acme',
        'p1',
        { limit: DEEP_RESYNC_LIMIT },
      ),
    )
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith('Deployment resync started'),
    )
  })

  it('shows an info toast when the resync was not enqueued', async () => {
    // A stale persisted terminal status must not read as this request's
    // outcome when nothing was enqueued (debounced or queue unavailable).
    vi.mocked(endpoints.getProjectDeploymentSyncStatus).mockResolvedValue(
      status({ events_recorded: 5, status: 'success' }),
    )
    vi.mocked(endpoints.resyncProjectDeployments).mockResolvedValue({
      enqueued: false,
    })
    const { result } = renderHook(
      () => useProjectDeploymentResync('acme', 'p1'),
      { wrapper: makeWrapper() },
    )
    await act(async () => {
      result.current.sync()
    })
    await waitFor(() => expect(toast.info).toHaveBeenCalled())
    expect(toast.success).not.toHaveBeenCalled()
    expect(toast.warning).not.toHaveBeenCalled()
  })

  it('reports isSyncing while the status is active', async () => {
    vi.mocked(endpoints.getProjectDeploymentSyncStatus).mockResolvedValue(
      status({ status: 'running' }),
    )
    const { result } = renderHook(
      () => useProjectDeploymentResync('acme', 'p1'),
      { wrapper: makeWrapper() },
    )
    await waitFor(() => expect(result.current.isSyncing).toBe(true))
  })

  it('does not toast a stale terminal status on mount', async () => {
    vi.mocked(endpoints.getProjectDeploymentSyncStatus).mockResolvedValue(
      status({ events_recorded: 5, status: 'success' }),
    )
    renderHook(() => useProjectDeploymentResync('acme', 'p1'), {
      wrapper: makeWrapper(),
    })
    await waitFor(() =>
      expect(endpoints.getProjectDeploymentSyncStatus).toHaveBeenCalled(),
    )
    await act(async () => {})
    expect(toast.success).not.toHaveBeenCalled()
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('toasts and invokes onComplete when a watched run succeeds', async () => {
    vi.mocked(endpoints.getProjectDeploymentSyncStatus)
      .mockResolvedValueOnce(status())
      .mockResolvedValueOnce(status({ status: 'running' }))
      .mockResolvedValue(
        status({
          errors: 0,
          events_recorded: 3,
          observed: 4,
          releases_created: 1,
          status: 'success',
        }),
      )
    vi.mocked(endpoints.resyncProjectDeployments).mockResolvedValue({
      enqueued: true,
    })
    const onComplete = vi.fn()
    const client = makeClient()
    const { result } = renderHook(
      () => useProjectDeploymentResync('acme', 'p1', onComplete),
      { wrapper: makeWrapper(client) },
    )
    await waitFor(() =>
      expect(endpoints.getProjectDeploymentSyncStatus).toHaveBeenCalled(),
    )
    await act(async () => {
      result.current.sync()
    })
    // The mutation's onSuccess invalidation refetches → 'running'.
    await waitFor(() => expect(result.current.isSyncing).toBe(true))
    // Simulate the next poll observing the terminal state.
    await act(async () => {
      await client.invalidateQueries({
        queryKey: ['deploymentSyncStatus', 'acme', 'p1'],
      })
    })
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        'Resync complete: 3 event(s) recorded, 1 release(s) created',
      ),
    )
    expect(onComplete).toHaveBeenCalled()
  })

  it('warns when a watched run finishes with per-env errors', async () => {
    vi.mocked(endpoints.getProjectDeploymentSyncStatus)
      .mockResolvedValueOnce(status())
      .mockResolvedValueOnce(status({ status: 'running' }))
      .mockResolvedValue(
        status({ errors: 2, events_recorded: 1, status: 'success' }),
      )
    vi.mocked(endpoints.resyncProjectDeployments).mockResolvedValue({
      enqueued: true,
    })
    const client = makeClient()
    const { result } = renderHook(
      () => useProjectDeploymentResync('acme', 'p1'),
      { wrapper: makeWrapper(client) },
    )
    await waitFor(() =>
      expect(endpoints.getProjectDeploymentSyncStatus).toHaveBeenCalled(),
    )
    await act(async () => {
      result.current.sync()
    })
    await waitFor(() => expect(result.current.isSyncing).toBe(true))
    await act(async () => {
      await client.invalidateQueries({
        queryKey: ['deploymentSyncStatus', 'acme', 'p1'],
      })
    })
    await waitFor(() =>
      expect(toast.warning).toHaveBeenCalledWith(
        'Resync finished with 2 error(s): 1 event(s) recorded',
      ),
    )
  })

  it('toasts an error when a watched run fails', async () => {
    vi.mocked(endpoints.getProjectDeploymentSyncStatus)
      .mockResolvedValueOnce(status())
      .mockResolvedValueOnce(status({ status: 'running' }))
      .mockResolvedValue(status({ error: 'boom', status: 'failed' }))
    vi.mocked(endpoints.resyncProjectDeployments).mockResolvedValue({
      enqueued: true,
    })
    const onComplete = vi.fn()
    const client = makeClient()
    const { result } = renderHook(
      () => useProjectDeploymentResync('acme', 'p1', onComplete),
      { wrapper: makeWrapper(client) },
    )
    await waitFor(() =>
      expect(endpoints.getProjectDeploymentSyncStatus).toHaveBeenCalled(),
    )
    await act(async () => {
      result.current.sync()
    })
    await waitFor(() => expect(result.current.isSyncing).toBe(true))
    await act(async () => {
      await client.invalidateQueries({
        queryKey: ['deploymentSyncStatus', 'acme', 'p1'],
      })
    })
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        'Deployment resync failed: boom',
      ),
    )
    expect(onComplete).not.toHaveBeenCalled()
  })

  it('invokes onComplete without a toast for an unwatched run', async () => {
    vi.mocked(endpoints.getProjectDeploymentSyncStatus)
      .mockResolvedValueOnce(status({ status: 'running' }))
      .mockResolvedValue(status({ events_recorded: 3, status: 'success' }))
    const onComplete = vi.fn()
    const client = makeClient()
    const { result } = renderHook(
      () => useProjectDeploymentResync('acme', 'p1', onComplete),
      { wrapper: makeWrapper(client) },
    )
    await waitFor(() => expect(result.current.isSyncing).toBe(true))
    // Someone else's run finishes; the next poll observes it.
    await act(async () => {
      await client.invalidateQueries({
        queryKey: ['deploymentSyncStatus', 'acme', 'p1'],
      })
    })
    await waitFor(() => expect(onComplete).toHaveBeenCalled())
    expect(toast.success).not.toHaveBeenCalled()
  })
})
