import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import * as releases from '@/api/releases'

import { useReleaseBlockMutation } from './useReleaseBlockMutation'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/releases', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/releases')>('@/api/releases')
  return { ...actual, blockRelease: vi.fn(), unblockRelease: vi.fn() }
})

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}))

function renderTestHook(onUnblocked?: () => void) {
  const client = new QueryClient({
    defaultOptions: { queries: { gcTime: 0, retry: false } },
  })
  return renderHook(
    () =>
      useReleaseBlockMutation({
        onUnblocked,
        orgSlug: 'acme',
        projectId: 'p1',
      }),
    {
      wrapper: ({ children }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    },
  )
}

describe('useReleaseBlockMutation', () => {
  it('retires the in-flight banner after a successful unblock', async () => {
    // The banner keys off `promote-status`, which still reads
    // `build_failed` after the block record is cleared — without this
    // callback the page keeps claiming the tag is blocked right after
    // the operator unblocked it.
    vi.mocked(releases.unblockRelease).mockResolvedValue({
      blocked: false,
      tag: 'v6.5.0',
    } as never)
    const onUnblocked = vi.fn()
    const { result } = renderTestHook(onUnblocked)
    result.current.unblock('v6.5.0')
    await waitFor(() => expect(onUnblocked).toHaveBeenCalledOnce())
  })

  it('leaves the banner standing when the unblock fails', async () => {
    vi.mocked(releases.unblockRelease).mockRejectedValue(
      new Error('nope') as never,
    )
    const onUnblocked = vi.fn()
    const { result } = renderTestHook(onUnblocked)
    result.current.unblock('v6.5.0')
    await waitFor(() => expect(releases.unblockRelease).toHaveBeenCalled())
    expect(onUnblocked).not.toHaveBeenCalled()
  })
})
