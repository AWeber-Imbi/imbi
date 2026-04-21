import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useProjectPatch } from '../useProjectPatch'
import * as endpoints from '@/api/endpoints'
import { ApiError } from '@/api/client'
import { toast } from 'sonner'

vi.mock('sonner', () => ({ toast: { error: vi.fn() } }))

function wrapper(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

const baseProject = {
  id: 'p1',
  name: 'Alpha',
  slug: 'alpha',
  description: 'desc',
  team: { slug: 't', name: 'T', organization: { slug: 'o' } },
} as unknown as import('@/types').Project

describe('useProjectPatch', () => {
  let qc: QueryClient

  beforeEach(() => {
    qc = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    })
    qc.setQueryData(['project', 'o', 'p1'], baseProject)
    vi.clearAllMocks()
  })

  it('applies optimistic update and leaves it in cache on success', async () => {
    // The hook invalidates the project query after a successful PATCH rather
    // than writing the server response into the cache (the PATCH and GET
    // bodies can differ in shape). Until the next GET completes, the cache
    // holds the locally-applied optimistic value. Use a server payload that
    // intentionally differs from the optimistic value so this test would fail
    // if the hook ever started writing the PATCH response back into cache.
    const optimistic = { ...baseProject, name: 'Beta' }
    const serverPayload = { ...baseProject, name: 'Server Beta' }
    vi.spyOn(endpoints, 'patchProject').mockResolvedValue(
      serverPayload as never,
    )

    const { result } = renderHook(() => useProjectPatch('o', 'p1'), {
      wrapper: wrapper(qc),
    })

    await act(async () => {
      await result.current.patch('/name', 'Beta')
    })

    expect(endpoints.patchProject).toHaveBeenCalledWith('o', 'p1', [
      { op: 'replace', path: '/name', value: 'Beta' },
    ])
    expect(qc.getQueryData(['project', 'o', 'p1'])).toEqual(optimistic)
  })

  it('rolls back on error and toasts', async () => {
    vi.spyOn(endpoints, 'patchProject').mockRejectedValue(
      new ApiError(400, 'Bad Request', { detail: 'nope' }),
    )

    const { result } = renderHook(() => useProjectPatch('o', 'p1'), {
      wrapper: wrapper(qc),
    })

    await expect(
      act(async () => {
        await result.current.patch('/name', 'Beta')
      }),
    ).rejects.toThrow()

    expect(qc.getQueryData(['project', 'o', 'p1'])).toEqual(baseProject)
    // Verify the ApiError.response.data.detail branch is used for the toast.
    expect(toast.error).toHaveBeenCalledWith('Save failed: nope')
  })

  it('emits remove op when value is null', async () => {
    const updated = { ...baseProject }
    vi.spyOn(endpoints, 'patchProject').mockResolvedValue(updated as never)

    const { result } = renderHook(() => useProjectPatch('o', 'p1'), {
      wrapper: wrapper(qc),
    })

    await act(async () => {
      await result.current.patch('/description', null)
    })

    expect(endpoints.patchProject).toHaveBeenCalledWith('o', 'p1', [
      { op: 'remove', path: '/description' },
    ])
  })

  it('still sends the network PATCH when the optimistic apply fails', async () => {
    // Nested paths are not supported by applyJsonPatch and will throw, so the
    // optimistic update is skipped. After the PATCH succeeds the hook
    // invalidates the query; the cache retains its prior value until the next
    // GET refetches, so it must NOT have been clobbered with a stale snapshot.
    const updated = { ...baseProject, name: 'Beta' }
    const spy = vi
      .spyOn(endpoints, 'patchProject')
      .mockResolvedValue(updated as never)

    const { result } = renderHook(() => useProjectPatch('o', 'p1'), {
      wrapper: wrapper(qc),
    })

    await act(async () => {
      await result.current.patch('/team/slug', 'new-team')
    })

    expect(spy).toHaveBeenCalledWith('o', 'p1', [
      { op: 'replace', path: '/team/slug', value: 'new-team' },
    ])
    expect(qc.getQueryData(['project', 'o', 'p1'])).toEqual(baseProject)
  })

  it('does not roll back to stale snapshot when optimistic apply was skipped', async () => {
    // Force the optimistic update to be skipped (nested path throws) then
    // fail the network PATCH; the cached project should be unchanged (not
    // overwritten with a stale snapshot).
    vi.spyOn(endpoints, 'patchProject').mockRejectedValue(
      new ApiError(500, 'Internal Server Error', { detail: 'boom' }),
    )

    const { result } = renderHook(() => useProjectPatch('o', 'p1'), {
      wrapper: wrapper(qc),
    })

    await expect(
      act(async () => {
        await result.current.patch('/team/slug', 'new-team')
      }),
    ).rejects.toThrow()

    expect(qc.getQueryData(['project', 'o', 'p1'])).toEqual(baseProject)
    expect(toast.error).toHaveBeenCalled()
  })

  it('tracks pendingPath during the mutation', async () => {
    let resolveIt!: (v: unknown) => void
    vi.spyOn(endpoints, 'patchProject').mockImplementation(
      () =>
        new Promise((r) => {
          resolveIt = r
        }),
    )

    const { result } = renderHook(() => useProjectPatch('o', 'p1'), {
      wrapper: wrapper(qc),
    })

    act(() => {
      result.current.patch('/name', 'Beta')
    })
    await waitFor(() => expect(result.current.pendingPath).toBe('/name'))

    act(() => resolveIt({ ...baseProject, name: 'Beta' }))
    await waitFor(() => expect(result.current.pendingPath).toBeNull())
  })
})
