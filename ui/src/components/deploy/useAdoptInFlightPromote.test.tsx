import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'

import { useAdoptInFlightPromote } from './useAdoptInFlightPromote'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/endpoints')>('@/api/endpoints')
  return {
    ...actual,
    getPromoteStatus: vi.fn(),
  }
})

vi.mock('sonner', () => ({
  toast: { loading: vi.fn() },
}))

function Harness({
  hasActiveBuild = false,
  onBuildStarted,
}: {
  hasActiveBuild?: boolean
  onBuildStarted: (build: unknown) => void
}) {
  useAdoptInFlightPromote({
    enabled: true,
    envName: (slug) => (slug === 'staging' ? 'Staging' : slug),
    hasActiveBuild,
    onBuildStarted: onBuildStarted as never,
    orgSlug: 'acme',
    projectId: 'p1',
  })
  return null
}

function renderHook(props: { hasActiveBuild?: boolean } = {}) {
  const onBuildStarted = vi.fn()
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const utils = render(
    <QueryClientProvider client={client}>
      <Harness {...props} onBuildStarted={onBuildStarted} />
    </QueryClientProvider>,
  )
  return { ...utils, client, onBuildStarted }
}

function status(
  overrides: Partial<endpoints.PromoteStatus> = {},
): endpoints.PromoteStatus {
  return {
    artifact_run_id: '4242',
    artifact_run_url: 'https://ghe/run/4242',
    committish: 'e6a13a0',
    environment: 'staging',
    error: null,
    from_environment: 'testing',
    requested_by: 'daves@aweber.com',
    status: 'building',
    tag: '0.1.9',
    updated_at: null,
    ...overrides,
  }
}

describe('useAdoptInFlightPromote', () => {
  let getPromoteStatus: ReturnType<typeof vi.fn>
  let toast: { loading: ReturnType<typeof vi.fn> }

  beforeEach(async () => {
    getPromoteStatus = vi.mocked(endpoints.getPromoteStatus)
    const sonner = await import('sonner')
    toast = sonner.toast as unknown as typeof toast
    getPromoteStatus.mockReset()
    toast.loading.mockReset()
    toast.loading.mockReturnValue('promote:p1')
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('adopts a build that was already running when it mounted', async () => {
    getPromoteStatus.mockResolvedValue(status())
    const { onBuildStarted } = renderHook()
    await waitFor(() => {
      expect(onBuildStarted).toHaveBeenCalled()
    })
    expect(toast.loading.mock.calls[0][0]).toMatch(/Building release 0\.1\.9/)
    expect(onBuildStarted.mock.calls[0][0]).toMatchObject({
      envName: 'Staging',
      originOrgSlug: 'acme',
      originProjectId: 'p1',
      tag: '0.1.9',
    })
  })

  it('adopts a rollout and resolves the env slug to its name', async () => {
    getPromoteStatus.mockResolvedValue(status({ status: 'deploying' }))
    const { onBuildStarted } = renderHook()
    await waitFor(() => {
      expect(onBuildStarted).toHaveBeenCalled()
    })
    expect(toast.loading.mock.calls[0][0]).toBe('Deploying 0.1.9 to Staging…')
  })

  it('ignores a project with nothing in flight', async () => {
    getPromoteStatus.mockResolvedValue(status({ status: 'idle' }))
    const { onBuildStarted } = renderHook()
    await waitFor(() => {
      expect(getPromoteStatus).toHaveBeenCalled()
    })
    expect(onBuildStarted).not.toHaveBeenCalled()
    expect(toast.loading).not.toHaveBeenCalled()
  })

  it('ignores a settled promote', async () => {
    getPromoteStatus.mockResolvedValue(status({ status: 'success' }))
    const { onBuildStarted } = renderHook()
    await waitFor(() => {
      expect(getPromoteStatus).toHaveBeenCalled()
    })
    expect(onBuildStarted).not.toHaveBeenCalled()
  })

  it('does not double up on a promote this page already started', async () => {
    // The dispatching mutation already mounted a watcher; adopting on top
    // of it would drive the same toast from two places.
    getPromoteStatus.mockResolvedValue(status())
    const { onBuildStarted } = renderHook({ hasActiveBuild: true })
    await waitFor(() => {
      expect(getPromoteStatus).toHaveBeenCalled()
    })
    expect(onBuildStarted).not.toHaveBeenCalled()
    expect(toast.loading).not.toHaveBeenCalled()
  })

  it('does not write into the watcher’s cache entry', async () => {
    // Regression guard: when both shared the ``promote-status`` key,
    // this fetch seeded that entry at page load, and a watcher mounting
    // on a later click read the finished promote synchronously and
    // settled against it before its own first fetch resolved.
    getPromoteStatus.mockResolvedValue(status({ status: 'success' }))
    const { client } = renderHook()
    await waitFor(() => {
      expect(getPromoteStatus).toHaveBeenCalled()
    })
    expect(
      client.getQueryData(['promote-status', 'acme', 'p1']),
    ).toBeUndefined()
  })

  it('adopts at most once per mount', async () => {
    // Guards the loop: the watcher removes itself on terminal, which
    // would flip ``hasActiveBuild`` back to false while the cache still
    // held ``building`` — re-adopting there would spawn watchers forever.
    getPromoteStatus.mockResolvedValue(status())
    const { onBuildStarted, rerender } = renderHook()
    await waitFor(() => {
      expect(onBuildStarted).toHaveBeenCalledTimes(1)
    })
    rerender(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: {} } })}
      >
        <Harness onBuildStarted={onBuildStarted} />
      </QueryClientProvider>,
    )
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(onBuildStarted).toHaveBeenCalledTimes(1)
  })
})
