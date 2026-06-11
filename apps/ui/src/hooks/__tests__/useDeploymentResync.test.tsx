import type { ReactNode } from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import type { DeploymentResyncSummary } from '@/api/endpoints'
import { DEEP_RESYNC_LIMIT } from '@/lib/resync'

import { useProjectDeploymentResync } from '../useDeploymentResync'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/endpoints')>('@/api/endpoints')
  return { ...actual, resyncProjectDeployments: vi.fn() }
})

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn() },
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

function summary(): DeploymentResyncSummary {
  return {
    errors: [],
    events_recorded: 0,
    events_skipped: 0,
    observed: 0,
    projects: 1,
    releases_created: 0,
    releases_updated: 0,
  }
}

describe('useProjectDeploymentResync', () => {
  beforeEach(() => vi.clearAllMocks())

  it('requests a deep backfill so historical attribution is re-resolved', async () => {
    vi.mocked(endpoints.resyncProjectDeployments).mockResolvedValue(summary())
    const { result } = renderHook(
      () => useProjectDeploymentResync('acme', 'p1'),
      { wrapper: makeWrapper() },
    )
    await act(async () => {
      result.current.mutate()
    })
    await waitFor(() =>
      expect(endpoints.resyncProjectDeployments).toHaveBeenCalledWith(
        'acme',
        'p1',
        { limit: DEEP_RESYNC_LIMIT },
      ),
    )
  })
})
