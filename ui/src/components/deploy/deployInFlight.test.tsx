import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useDeployRunBanners } from './deployInFlight'
import type { DeploymentRunStarted } from './DeploymentModal'

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    message: vi.fn(),
    success: vi.fn(),
  },
}))

const run = (
  over: Partial<DeploymentRunStarted> = {},
): DeploymentRunStarted => ({
  envName: 'Infrastructure',
  initialStatus: 'queued',
  originOrgSlug: 'acme',
  originProjectId: 'p1',
  refLabel: '2.27.0',
  runId: 'run-42',
  runUrl: 'https://gh/runs/42',
  ...over,
})

describe('useDeployRunBanners', () => {
  let toast: {
    error: ReturnType<typeof vi.fn>
    message: ReturnType<typeof vi.fn>
    success: ReturnType<typeof vi.fn>
  }

  beforeEach(async () => {
    vi.useFakeTimers()
    const sonner = await import('sonner')
    toast = sonner.toast as unknown as typeof toast
    toast.error.mockReset()
    toast.message.mockReset()
    toast.success.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('raises a deploying banner when a run starts', () => {
    const { result } = renderHook(() => useDeployRunBanners('p1'))
    act(() => result.current.start(run()))
    expect(result.current.banners).toHaveLength(1)
    const { state } = result.current.banners[0]
    expect(state.phase).toBe('deploying')
    expect(state.tag).toBe('2.27.0')
    expect(state.envName).toBe('Infrastructure')
    expect(state.runUrl).toBe('https://gh/runs/42')
    expect(state.endedAt).toBeNull()
  })

  it('does not duplicate a run started twice', () => {
    const { result } = renderHook(() => useDeployRunBanners('p1'))
    act(() => {
      result.current.start(run())
      result.current.start(run())
    })
    expect(result.current.banners).toHaveLength(1)
  })

  it('settles green and retires itself after the linger', () => {
    const { result } = renderHook(() => useDeployRunBanners('p1'))
    act(() => result.current.start(run()))
    act(() => result.current.onStatus('run-42', 'success'))
    expect(result.current.banners[0].state.phase).toBe('success')
    expect(result.current.banners[0].state.endedAt).not.toBeNull()
    act(() => vi.advanceTimersByTime(15_000))
    expect(result.current.banners).toHaveLength(0)
  })

  it('keeps a failure standing until dismissed', () => {
    const { result } = renderHook(() => useDeployRunBanners('p1'))
    act(() => result.current.start(run()))
    act(() => result.current.onStatus('run-42', 'failure'))
    expect(result.current.banners[0].state.phase).toBe('deploy_failed')
    act(() => vi.advanceTimersByTime(60_000))
    expect(result.current.banners).toHaveLength(1)
    act(() => result.current.banners[0].state.dismiss())
    expect(result.current.banners).toHaveLength(0)
  })

  it('freezes the clock on a run dispatched already terminal', () => {
    const { result } = renderHook(() => useDeployRunBanners('p1'))
    act(() => result.current.start(run({ initialStatus: 'failure' })))
    expect(result.current.banners[0].state.phase).toBe('deploy_failed')
    expect(result.current.banners[0].state.endedAt).not.toBeNull()
    // The watcher's first poll repeats the status; endedAt must hold.
    const before = result.current.banners[0].state.endedAt
    act(() => result.current.onStatus('run-42', 'failure'))
    expect(result.current.banners[0].state.endedAt).toBe(before)
  })

  it('clears the linger timer when a success is dismissed by hand', () => {
    const { result } = renderHook(() => useDeployRunBanners('p1'))
    act(() => result.current.start(run()))
    act(() => result.current.onStatus('run-42', 'success'))
    act(() => result.current.banners[0].state.dismiss())
    expect(result.current.banners).toHaveLength(0)
    // A re-triggered dispatch can reuse the workflow run id; the stale
    // timer must not dismiss the fresh banner or eat its linger.
    act(() => result.current.start(run()))
    act(() => vi.advanceTimersByTime(14_000))
    expect(result.current.banners).toHaveLength(1)
    act(() => result.current.onStatus('run-42', 'success'))
    act(() => vi.advanceTimersByTime(15_000))
    expect(result.current.banners).toHaveLength(0)
  })

  it('shows a banner only on the project that dispatched the run', () => {
    const { rerender, result } = renderHook(
      ({ projectId }) => useDeployRunBanners(projectId),
      { initialProps: { projectId: 'p1' } },
    )
    act(() => result.current.start(run()))
    expect(result.current.banners).toHaveLength(1)
    rerender({ projectId: 'p2' })
    expect(result.current.banners).toHaveLength(0)
    rerender({ projectId: 'p1' })
    expect(result.current.banners).toHaveLength(1)
  })

  it('toasts an outcome that lands while another project is viewed', () => {
    const { rerender, result } = renderHook(
      ({ projectId }) => useDeployRunBanners(projectId),
      { initialProps: { projectId: 'p1' } },
    )
    act(() => result.current.start(run()))
    rerender({ projectId: 'p2' })
    act(() => result.current.onStatus('run-42', 'failure'))
    expect(toast.error).toHaveBeenCalledWith(
      'Deployment to Infrastructure failed',
      expect.objectContaining({ action: expect.anything() }),
    )
    // Consumed: nothing left to banner when the user returns.
    rerender({ projectId: 'p1' })
    expect(result.current.banners).toHaveLength(0)
  })

  it('keeps a settled banner for the origin page while away', () => {
    // Settling while visible must not convert the banner into a toast
    // when the user navigates afterwards.
    const { rerender, result } = renderHook(
      ({ projectId }) => useDeployRunBanners(projectId),
      { initialProps: { projectId: 'p1' } },
    )
    act(() => result.current.start(run()))
    act(() => result.current.onStatus('run-42', 'failure'))
    rerender({ projectId: 'p2' })
    expect(toast.error).not.toHaveBeenCalled()
    rerender({ projectId: 'p1' })
    expect(result.current.banners[0].state.phase).toBe('deploy_failed')
  })

  it('leaves a still-running toast behind on unmount', () => {
    const { result, unmount } = renderHook(() => useDeployRunBanners('p1'))
    act(() => result.current.start(run()))
    unmount()
    expect(toast.message).toHaveBeenCalledWith(
      'Deployment to Infrastructure still running',
      expect.objectContaining({ action: expect.anything() }),
    )
  })

  it('does not toast a settled run on unmount', () => {
    const { result, unmount } = renderHook(() => useDeployRunBanners('p1'))
    act(() => result.current.start(run()))
    act(() => result.current.onStatus('run-42', 'success'))
    unmount()
    expect(toast.message).not.toHaveBeenCalled()
  })

  it('says a cancelled run was cancelled', () => {
    const { result } = renderHook(() => useDeployRunBanners('p1'))
    act(() => result.current.start(run()))
    act(() => result.current.onStatus('run-42', 'cancelled'))
    const { state } = result.current.banners[0]
    expect(state.phase).toBe('deploy_failed')
    expect(state.error).toMatch(/cancelled/)
  })

  it('maps lost polling onto the failed phase', () => {
    const { result } = renderHook(() => useDeployRunBanners('p1'))
    act(() => result.current.start(run()))
    act(() => result.current.onStatus('run-42', 'lost'))
    expect(result.current.banners[0].state.phase).toBe('failed')
  })

  it('drops javascript: run URLs', () => {
    const { result } = renderHook(() => useDeployRunBanners('p1'))
    // eslint-disable-next-line no-script-url
    act(() => result.current.start(run({ runUrl: 'javascript:alert(1)' })))
    expect(result.current.banners[0].state.runUrl).toBeNull()
  })
})
