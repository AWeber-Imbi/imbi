import type { ReactNode } from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { toast } from 'sonner'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import type { CommitSyncStatus } from '@/api/endpoints'

import { useCommitSync } from '../useCommitSync'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/endpoints')>('@/api/endpoints')
  return {
    ...actual,
    getProjectCommitSyncStatus: vi.fn(),
    syncProjectCommitsAndTags: vi.fn(),
  }
})

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), info: vi.fn(), success: vi.fn() },
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

async function renderAndSync(enqueued: boolean) {
  vi.mocked(endpoints.getProjectCommitSyncStatus).mockResolvedValue(status())
  vi.mocked(endpoints.syncProjectCommitsAndTags).mockResolvedValue({
    enqueued,
  })
  const { result } = renderHook(() => useCommitSync('acme', 'p1', true), {
    wrapper: makeWrapper(),
  })
  await act(async () => {
    result.current.sync()
  })
  return result
}

function status(overrides: Partial<CommitSyncStatus> = {}): CommitSyncStatus {
  return {
    commits_synced: null,
    error: null,
    last_synced_at: null,
    requested_by: null,
    status: 'idle',
    tags_synced: null,
    ...overrides,
  }
}

describe('useCommitSync', () => {
  beforeEach(() => vi.clearAllMocks())

  it('enqueues and toasts success when accepted', async () => {
    await renderAndSync(true)
    await waitFor(() =>
      expect(endpoints.syncProjectCommitsAndTags).toHaveBeenCalledWith(
        'acme',
        'p1',
      ),
    )
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith('Commit & tag sync started'),
    )
  })

  it('shows an info toast when a sync is already running', async () => {
    await renderAndSync(false)
    await waitFor(() => expect(toast.info).toHaveBeenCalled())
  })

  it('reports isSyncing while the status is active', async () => {
    vi.mocked(endpoints.getProjectCommitSyncStatus).mockResolvedValue(
      status({ status: 'running' }),
    )
    const { result } = renderHook(() => useCommitSync('acme', 'p1', true), {
      wrapper: makeWrapper(),
    })
    await waitFor(() => expect(result.current.isSyncing).toBe(true))
  })

  it('does not toast a stale terminal status on mount', async () => {
    vi.mocked(endpoints.getProjectCommitSyncStatus).mockResolvedValue(
      status({ commits_synced: 5, status: 'success', tags_synced: 2 }),
    )
    renderHook(() => useCommitSync('acme', 'p1', true), {
      wrapper: makeWrapper(),
    })
    await waitFor(() =>
      expect(endpoints.getProjectCommitSyncStatus).toHaveBeenCalled(),
    )
    await act(async () => {})
    expect(toast.success).not.toHaveBeenCalled()
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('toasts and invokes onComplete when a watched run succeeds', async () => {
    vi.mocked(endpoints.getProjectCommitSyncStatus)
      .mockResolvedValueOnce(status())
      .mockResolvedValueOnce(status({ status: 'running' }))
      .mockResolvedValue(
        status({ commits_synced: 5, status: 'success', tags_synced: 2 }),
      )
    vi.mocked(endpoints.syncProjectCommitsAndTags).mockResolvedValue({
      enqueued: true,
    })
    const onComplete = vi.fn()
    const client = makeClient()
    const { result } = renderHook(
      () => useCommitSync('acme', 'p1', true, onComplete),
      { wrapper: makeWrapper(client) },
    )
    await waitFor(() =>
      expect(endpoints.getProjectCommitSyncStatus).toHaveBeenCalled(),
    )
    await act(async () => {
      result.current.sync()
    })
    // The mutation's onSuccess invalidation refetches → 'running'.
    await waitFor(() => expect(result.current.isSyncing).toBe(true))
    // Simulate the next poll observing the terminal state.
    await act(async () => {
      await client.invalidateQueries({
        queryKey: ['commitSyncStatus', 'acme', 'p1'],
      })
    })
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        'Synced 5 commit(s) and 2 tag(s)',
      ),
    )
    expect(onComplete).toHaveBeenCalled()
  })

  it('toasts a watched run that completes before the first refetch', async () => {
    vi.mocked(endpoints.getProjectCommitSyncStatus)
      .mockResolvedValueOnce(status())
      // Fast job: the refetch after enqueue is already terminal.
      .mockResolvedValueOnce(
        status({ commits_synced: 5, status: 'success', tags_synced: 2 }),
      )
      // A later foreign run observed by this instance.
      .mockResolvedValueOnce(status({ status: 'running' }))
      .mockResolvedValue(
        status({ commits_synced: 9, status: 'success', tags_synced: 9 }),
      )
    vi.mocked(endpoints.syncProjectCommitsAndTags).mockResolvedValue({
      enqueued: true,
    })
    const onComplete = vi.fn()
    const client = makeClient()
    const { result } = renderHook(
      () => useCommitSync('acme', 'p1', true, onComplete),
      { wrapper: makeWrapper(client) },
    )
    await waitFor(() =>
      expect(endpoints.getProjectCommitSyncStatus).toHaveBeenCalled(),
    )
    await act(async () => {
      result.current.sync()
    })
    // The onSuccess invalidation refetches straight to 'success'.
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        'Synced 5 commit(s) and 2 tag(s)',
      ),
    )
    expect(onComplete).toHaveBeenCalledTimes(1)
    // Foreign run: running → success. onComplete fires but no toast,
    // because `watching` was consumed by the fast job's result.
    await act(async () => {
      await client.invalidateQueries({
        queryKey: ['commitSyncStatus', 'acme', 'p1'],
      })
    })
    // Ensure the 'running' state renders before the terminal poll, as it
    // would between real poll intervals.
    await waitFor(() => expect(result.current.isSyncing).toBe(true))
    await act(async () => {
      await client.invalidateQueries({
        queryKey: ['commitSyncStatus', 'acme', 'p1'],
      })
    })
    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(2))
    // Only the "started" toast and the fast job's result toast.
    expect(toast.success).toHaveBeenCalledTimes(2)
    expect(toast.success).not.toHaveBeenCalledWith(
      'Synced 9 commit(s) and 9 tag(s)',
    )
  })

  it('refetches and toasts a joined run despite a stale idle status', async () => {
    vi.mocked(endpoints.getProjectCommitSyncStatus)
      // Stale cache: the poll hasn't seen the foreign run yet.
      .mockResolvedValueOnce(status())
      // The post-join invalidation observes the run in flight.
      .mockResolvedValueOnce(status({ status: 'running' }))
      .mockResolvedValue(
        status({ commits_synced: 4, status: 'success', tags_synced: 1 }),
      )
    vi.mocked(endpoints.syncProjectCommitsAndTags).mockResolvedValue({
      enqueued: false,
    })
    const client = makeClient()
    const { result } = renderHook(() => useCommitSync('acme', 'p1', true), {
      wrapper: makeWrapper(client),
    })
    await waitFor(() =>
      expect(endpoints.getProjectCommitSyncStatus).toHaveBeenCalled(),
    )
    await act(async () => {
      result.current.sync()
    })
    // Joining must invalidate too, or the idle cache never starts polling.
    await waitFor(() => expect(result.current.isSyncing).toBe(true))
    await act(async () => {
      await client.invalidateQueries({
        queryKey: ['commitSyncStatus', 'acme', 'p1'],
      })
    })
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        'Synced 4 commit(s) and 1 tag(s)',
      ),
    )
  })

  it('invokes onComplete without a toast for an unwatched run', async () => {
    vi.mocked(endpoints.getProjectCommitSyncStatus)
      .mockResolvedValueOnce(status({ status: 'running' }))
      .mockResolvedValue(
        status({ commits_synced: 3, status: 'success', tags_synced: 1 }),
      )
    const onComplete = vi.fn()
    const client = makeClient()
    const { result } = renderHook(
      () => useCommitSync('acme', 'p1', true, onComplete),
      { wrapper: makeWrapper(client) },
    )
    await waitFor(() => expect(result.current.isSyncing).toBe(true))
    // Someone else's run finishes; the next poll observes it.
    await act(async () => {
      await client.invalidateQueries({
        queryKey: ['commitSyncStatus', 'acme', 'p1'],
      })
    })
    await waitFor(() => expect(onComplete).toHaveBeenCalled())
    expect(toast.success).not.toHaveBeenCalled()
  })
})
