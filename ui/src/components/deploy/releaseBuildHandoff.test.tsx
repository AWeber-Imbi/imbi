import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { DeploymentTriggerResponse } from '@/types'

import { handleDispatchedBuild } from './releaseBuildHandoff'

vi.mock('sonner', () => ({
  toast: {
    loading: vi.fn(() => 'toast-1'),
    warning: vi.fn(),
  },
}))

function response(
  overrides: Partial<DeploymentTriggerResponse> = {},
): DeploymentTriggerResponse {
  return {
    artifact_run_id: '4242',
    artifact_run_url: 'https://ghe/run/4242',
    phase: 'building',
    plugin_id: 'p-1',
    plugin_slug: 'github',
    recorded: true,
    run: { run_id: '', status: 'queued' },
    tag: '0.1.5',
    watched: true,
    ...overrides,
  }
}

describe('handleDispatchedBuild', () => {
  let toast: {
    loading: ReturnType<typeof vi.fn>
    warning: ReturnType<typeof vi.fn>
  }

  beforeEach(async () => {
    const sonner = await import('sonner')
    toast = sonner.toast as unknown as typeof toast
    toast.loading.mockReset()
    toast.loading.mockReturnValue('toast-1')
    toast.warning.mockReset()
  })

  const options = (onBuildStarted = vi.fn()) => ({
    envName: 'staging',
    onBuildStarted,
    orgSlug: 'acme',
    projectId: 'p1',
    tagFallback: 'fallback',
  })

  it('claims a dispatched build and hands it to the watcher', () => {
    const onBuildStarted = vi.fn()
    const handled = handleDispatchedBuild(response(), options(onBuildStarted))
    expect(handled).toBe(true)
    expect(toast.loading).toHaveBeenCalled()
    expect(toast.loading.mock.calls[0][0]).toMatch(/Building release 0\.1\.5/)
    expect(onBuildStarted).toHaveBeenCalledWith({
      envName: 'staging',
      originOrgSlug: 'acme',
      originProjectId: 'p1',
      runUrl: 'https://ghe/run/4242',
      tag: '0.1.5',
      toastId: 'toast-1',
    })
  })

  it('ignores the inline path so its caller keeps its own toast', () => {
    const onBuildStarted = vi.fn()
    const handled = handleDispatchedBuild(
      response({ phase: null, run: { run_id: '99', status: 'queued' } }),
      options(onBuildStarted),
    )
    expect(handled).toBe(false)
    expect(toast.loading).not.toHaveBeenCalled()
    expect(onBuildStarted).not.toHaveBeenCalled()
  })

  it('claims the response even when run_id is empty', () => {
    // The regression this helper exists for: callers gate their live
    // toast on ``data.run.run_id``, which is '' on the dispatch path, so
    // without this they fall through to a terminal "Promoted!" toast
    // minutes before the deployment exists.
    const handled = handleDispatchedBuild(
      response({ run: { run_id: '', status: 'queued' } }),
      options(),
    )
    expect(handled).toBe(true)
  })

  it('falls back to the requested tag when none is echoed', () => {
    handleDispatchedBuild(response({ tag: null }), options())
    expect(toast.loading.mock.calls[0][0]).toMatch(/Building release fallback/)
  })

  it('surfaces a dispatch warning alongside the build toast', () => {
    handleDispatchedBuild(
      response({ warning: 'no watcher queued', watched: false }),
      options(),
    )
    expect(toast.warning).toHaveBeenCalled()
    expect(toast.warning.mock.calls[0][1].description).toBe('no watcher queued')
  })
})
