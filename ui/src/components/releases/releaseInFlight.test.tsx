import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'

import { useReleaseInFlightState } from './releaseInFlight'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/endpoints')>('@/api/endpoints')
  return { ...actual, getPromoteStatus: vi.fn() }
})

const OPTIONS = {
  enabled: true,
  envName: (slug: null | string) => (slug === 'staging' ? 'Staging' : slug),
  orgSlug: 'acme',
  projectId: 'p1',
  watching: false,
}

const status = (over: Record<string, unknown> = {}) => ({
  artifact_run_id: null,
  artifact_run_url: null,
  committish: 'aaa1111',
  environment: 'staging',
  error: null,
  from_environment: 'testing',
  requested_by: 'gavin',
  status: 'building',
  tag: 'v6.5.0',
  updated_at: new Date().toISOString(),
  ...over,
})

describe('useReleaseInFlightState', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('blocks actions before the first poll answers', async () => {
    // The load-bearing case for a mid-release reload: "we have not asked
    // yet" is indistinguishable from "nothing is running", and guessing
    // idle for one tick is exactly the window a second cut lands in.
    vi.mocked(endpoints.getPromoteStatus).mockImplementation(
      () => new Promise(() => {}),
    )
    const { result } = renderTestHook()
    expect(result.current.phase).toBe('adopting')
    expect(result.current.blocked).toBe(true)
  })

  it('reports a running build as blocking, with the target env named', async () => {
    vi.mocked(endpoints.getPromoteStatus).mockResolvedValue(status() as never)
    const { result } = renderTestHook()
    await waitFor(() => expect(result.current.phase).toBe('building'))
    expect(result.current.blocked).toBe(true)
    expect(result.current.tag).toBe('v6.5.0')
    expect(result.current.envName).toBe('Staging')
  })

  it('keeps the block on a failed build — the tag is blocked', async () => {
    vi.mocked(endpoints.getPromoteStatus).mockResolvedValue(
      status({ status: 'build_failed' }) as never,
    )
    const { result } = renderTestHook()
    await waitFor(() => expect(result.current.phase).toBe('build_failed'))
    expect(result.current.blocked).toBe(true)
  })

  it('releases the block on a failed deploy — the build was green', async () => {
    vi.mocked(endpoints.getPromoteStatus).mockResolvedValue(
      status({ status: 'deploy_failed' }) as never,
    )
    const { result } = renderTestHook()
    await waitFor(() => expect(result.current.phase).toBe('deploy_failed'))
    expect(result.current.blocked).toBe(false)
  })

  it('releases the block when Imbi lost track of the promote', async () => {
    vi.mocked(endpoints.getPromoteStatus).mockResolvedValue(
      status({ status: 'failed' }) as never,
    )
    const { result } = renderTestHook()
    await waitFor(() => expect(result.current.phase).toBe('failed'))
    expect(result.current.blocked).toBe(false)
  })

  it('shows a fresh success and stops blocking', async () => {
    vi.mocked(endpoints.getPromoteStatus).mockResolvedValue(
      status({ status: 'success' }) as never,
    )
    const { result } = renderTestHook()
    await waitFor(() => expect(result.current.phase).toBe('success'))
    expect(result.current.blocked).toBe(false)
  })

  it('retires the success banner on its own', async () => {
    // Nothing on a green banner needs answering, so it should not sit
    // pinned under the tabs waiting for the operator to close it.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      vi.mocked(endpoints.getPromoteStatus).mockResolvedValue(
        status({ status: 'success' }) as never,
      )
      const { result } = renderTestHook()
      await waitFor(() => expect(result.current.phase).toBe('success'))
      await act(async () => {
        await vi.advanceTimersByTimeAsync(15_000)
      })
      expect(result.current.phase).toBe('idle')
    } finally {
      vi.useRealTimers()
    }
  })

  it('refreshes the page on a failure, not only on a success', async () => {
    // A failed deploy still cut the tag and still moved the pipeline, so
    // a page left showing the pre-release view offers the next version
    // over drift that is no longer true.
    vi.mocked(endpoints.getPromoteStatus).mockResolvedValue(
      status({ status: 'deploy_failed' }) as never,
    )
    const client = new QueryClient({
      defaultOptions: { queries: { gcTime: 0, retry: false } },
    })
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    const { result } = renderHook(
      () => useReleaseInFlightState({ ...OPTIONS, watching: false }),
      {
        wrapper: ({ children }) => (
          <QueryClientProvider client={client}>{children}</QueryClientProvider>
        ),
      },
    )
    await waitFor(() => expect(result.current.phase).toBe('deploy_failed'))
    await waitFor(() => expect(invalidate).toHaveBeenCalled())
  })

  it('holds the cut after a failure, but not the redeploy', async () => {
    vi.mocked(endpoints.getPromoteStatus).mockResolvedValue(
      status({ status: 'deploy_failed' }) as never,
    )
    const { result } = renderTestHook()
    await waitFor(() => expect(result.current.phase).toBe('deploy_failed'))
    expect(result.current.cutBlocked).toBe(true)
    expect(result.current.blocked).toBe(false)
  })

  it('picks up a cut dispatched while the page is open', async () => {
    // The reported bug: an idle first poll turns the refetch interval
    // off, so a release cut a minute later never reached the banner and
    // the operator saw only the toast until they reloaded.
    vi.mocked(endpoints.getPromoteStatus)
      .mockResolvedValueOnce(status({ status: 'idle' }) as never)
      .mockResolvedValue(status() as never)
    const client = new QueryClient({
      defaultOptions: { queries: { gcTime: 0, retry: false } },
    })
    const { rerender, result } = renderHook(
      ({ watching }: { watching: boolean }) =>
        useReleaseInFlightState({ ...OPTIONS, watching }),
      {
        initialProps: { watching: false },
        wrapper: ({ children }) => (
          <QueryClientProvider client={client}>{children}</QueryClientProvider>
        ),
      },
    )
    await waitFor(() => expect(result.current.phase).toBe('idle'))
    rerender({ watching: true })
    await waitFor(() => expect(result.current.phase).toBe('building'))
  })

  it('ignores a settled promote from long ago', async () => {
    // `promote-status` reports the last promote forever. Without the
    // freshness window every page load would raise a banner for a release
    // cut weeks back — and a long-resolved build_failed would leave the
    // release form disabled with nothing to clear it.
    vi.mocked(endpoints.getPromoteStatus).mockResolvedValue(
      status({
        status: 'build_failed',
        updated_at: new Date(Date.now() - 86_400_000).toISOString(),
      }) as never,
    )
    const { result } = renderTestHook()
    await waitFor(() => expect(result.current.phase).toBe('idle'))
    expect(result.current.blocked).toBe(false)
  })

  it('reports idle when nothing has ever been promoted', async () => {
    vi.mocked(endpoints.getPromoteStatus).mockResolvedValue(
      status({ status: 'idle', tag: null }) as never,
    )
    const { result } = renderTestHook()
    await waitFor(() => expect(result.current.phase).toBe('idle'))
    expect(result.current.blocked).toBe(false)
  })

  it('never asks while disabled', () => {
    const { result } = renderTestHook(false)
    expect(endpoints.getPromoteStatus).not.toHaveBeenCalled()
    expect(result.current.phase).toBe('idle')
  })
})

/** `renderHook` under a throwaway QueryClient, retries off. */
function renderTestHook(enabled = true, watching = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { gcTime: 0, retry: false } },
  })
  return renderHook(
    () => useReleaseInFlightState({ ...OPTIONS, enabled, watching }),
    {
      wrapper: ({ children }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    },
  )
}
