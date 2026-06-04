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

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { gcTime: 0, retry: false },
    },
  })
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
})
