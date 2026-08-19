import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
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
function renderTestHook(enabled = true) {
  const client = new QueryClient({
    defaultOptions: { queries: { gcTime: 0, retry: false } },
  })
  return renderHook(() => useReleaseInFlightState({ ...OPTIONS, enabled }), {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  })
}
