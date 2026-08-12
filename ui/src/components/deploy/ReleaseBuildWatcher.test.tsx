import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'

import { ReleaseBuildWatcher } from './ReleaseBuildWatcher'

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
  toast: {
    error: vi.fn(),
    loading: vi.fn(),
    message: vi.fn(),
    success: vi.fn(),
  },
}))

function renderWatcher(
  props: Partial<{
    envName: null | string
    onTerminal: () => void
    runUrl: null | string
    tag: string
    toastId: string
  }> = {},
) {
  const onTerminal = props.onTerminal ?? vi.fn()
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const utils = render(
    <QueryClientProvider client={client}>
      <ReleaseBuildWatcher
        envName={props.envName === undefined ? 'staging' : props.envName}
        onTerminal={onTerminal}
        orgSlug="acme"
        projectId="p1"
        runUrl={props.runUrl ?? null}
        tag={props.tag ?? '0.1.5'}
        toastId={props.toastId ?? 'toast-1'}
      />
    </QueryClientProvider>,
  )
  return { ...utils, client, onTerminal }
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
    tag: '0.1.5',
    updated_at: null,
    ...overrides,
  }
}

describe('ReleaseBuildWatcher', () => {
  let getPromoteStatus: ReturnType<typeof vi.fn>
  let toast: {
    error: ReturnType<typeof vi.fn>
    loading: ReturnType<typeof vi.fn>
    message: ReturnType<typeof vi.fn>
    success: ReturnType<typeof vi.fn>
  }

  beforeEach(async () => {
    getPromoteStatus = vi.mocked(endpoints.getPromoteStatus)
    const sonner = await import('sonner')
    toast = sonner.toast as unknown as typeof toast
    getPromoteStatus.mockReset()
    toast.error.mockReset()
    toast.loading.mockReset()
    toast.message.mockReset()
    toast.success.mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders nothing', async () => {
    getPromoteStatus.mockResolvedValue(status())
    const { container } = renderWatcher()
    expect(container.firstChild).toBeNull()
  })

  it('shows a build toast while building', async () => {
    getPromoteStatus.mockResolvedValue(status())
    const { onTerminal } = renderWatcher()
    await waitFor(() => {
      expect(toast.loading).toHaveBeenCalled()
    })
    expect(onTerminal).not.toHaveBeenCalled()
    expect(toast.loading.mock.calls[0][0]).toMatch(/Building release 0\.1\.5/)
  })

  it('keeps watching through the deploy phase', async () => {
    // ``deploying`` is not terminal: the rollout's outcome arrives on
    // this same status, so handing off here would drop it.
    getPromoteStatus.mockResolvedValue(status({ status: 'deploying' }))
    const { onTerminal } = renderWatcher()
    await waitFor(() => {
      expect(toast.loading).toHaveBeenCalled()
    })
    expect(toast.loading.mock.calls[0][0]).toMatch(/Deploying 0\.1\.5 to/)
    expect(onTerminal).not.toHaveBeenCalled()
  })

  it('ignores a terminal status left over from an earlier promote', async () => {
    // `promote-status` is project-scoped, so a warm cache (or a read
    // that beats the dispatch's own status write) can hand this watcher
    // the *previous* promote's `success`. Settling on it would report
    // that outcome against this tag and kill the toast on click.
    getPromoteStatus.mockResolvedValue(
      status({ status: 'success', tag: '0.1.9' }),
    )
    const { onTerminal } = renderWatcher({ tag: '0.1.10' })
    await waitFor(() => {
      expect(getPromoteStatus).toHaveBeenCalled()
    })
    expect(onTerminal).not.toHaveBeenCalled()
    expect(toast.success).not.toHaveBeenCalled()
  })

  it('settles once the status catches up to its own tag', async () => {
    getPromoteStatus
      .mockResolvedValueOnce(status({ status: 'success', tag: '0.1.9' }))
      .mockResolvedValue(status({ status: 'success', tag: '0.1.10' }))
    const { onTerminal } = renderWatcher({ tag: '0.1.10' })
    await waitFor(
      () => {
        expect(onTerminal).toHaveBeenCalled()
      },
      { timeout: 10_000 },
    )
    expect(toast.success.mock.calls[0][0]).toMatch(/Released 0\.1\.10/)
  }, 15_000)

  it('reports success', async () => {
    getPromoteStatus.mockResolvedValue(status({ status: 'success' }))
    const { onTerminal } = renderWatcher()
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalled()
      expect(onTerminal).toHaveBeenCalled()
    })
    expect(toast.success.mock.calls[0][0]).toMatch(/Released 0\.1\.5/)
    expect(toast.success.mock.calls[0][1].id).toBe('toast-1')
  })

  it('reports a failed build and says the release is blocked', async () => {
    getPromoteStatus.mockResolvedValue(
      status({
        error: 'The release build failure. The release is blocked;',
        status: 'build_failed',
      }),
    )
    const { onTerminal } = renderWatcher()
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalled()
      expect(onTerminal).toHaveBeenCalled()
    })
    expect(toast.error.mock.calls[0][0]).toMatch(/Release build for 0\.1\.5/)
    expect(toast.error.mock.calls[0][1].description).toMatch(/blocked/)
  })

  it('reports a failed rollout and says the release is not blocked', async () => {
    // The mirror of ``build_failed``: the build was green, so the tag is
    // real and redeployable — telling the user it is blocked would send
    // them to unblock something that was never blocked.
    getPromoteStatus.mockResolvedValue(
      status({
        error: 'The deployment of 0.1.5 to staging failure.',
        status: 'deploy_failed',
      }),
    )
    const { onTerminal } = renderWatcher()
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalled()
      expect(onTerminal).toHaveBeenCalled()
    })
    expect(toast.error.mock.calls[0][0]).toMatch(/Deploying 0\.1\.5 to staging/)
    expect(toast.error.mock.calls[0][1].description).not.toMatch(/blocked;/)
  })

  it('distinguishes a lost build from a failed one', async () => {
    // ``failed`` means Imbi could not confirm or finish, and the tag is
    // deliberately still shippable — so this must not read as an error.
    getPromoteStatus.mockResolvedValue(
      status({ error: 'no run id', status: 'failed' }),
    )
    const { onTerminal } = renderWatcher()
    await waitFor(() => {
      expect(toast.message).toHaveBeenCalled()
      expect(onTerminal).toHaveBeenCalled()
    })
    expect(toast.error).not.toHaveBeenCalled()
    expect(toast.message.mock.calls[0][0]).toMatch(/Lost track/)
  })

  it('omits the environment for a release-only cut', async () => {
    getPromoteStatus.mockResolvedValue(
      status({ environment: null, status: 'success' }),
    )
    renderWatcher({ envName: null })
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalled()
    })
    expect(toast.success.mock.calls[0][0]).toBe('Released 0.1.5')
  })

  it('links the toast action at the build run', async () => {
    getPromoteStatus.mockResolvedValue(status({ status: 'success' }))
    renderWatcher()
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalled()
    })
    const opts = toast.success.mock.calls[0][1]
    expect(opts.action.label).toBe('View build')
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
    opts.action.onClick()
    expect(openSpy).toHaveBeenCalledWith(
      'https://ghe/run/4242',
      '_blank',
      'noopener',
    )
  })

  // Slow by design: the watcher sets ``retry: 3``, so a persistent
  // error only surfaces after TanStack's backoff (1s + 2s + 4s) is
  // exhausted. Waiting it out tests the real give-up path rather than
  // weakening the component's retry policy for the test's convenience.
  it('gives up when status polling errors out', async () => {
    getPromoteStatus.mockRejectedValue(new Error('boom'))
    const { onTerminal } = renderWatcher()
    await waitFor(
      () => {
        expect(toast.message).toHaveBeenCalled()
        expect(onTerminal).toHaveBeenCalled()
      },
      { timeout: 15_000 },
    )
    expect(toast.message.mock.calls[0][1].description).toMatch(/polling failed/)
  }, 20_000)
})
