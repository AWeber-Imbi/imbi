import { afterEach, describe, expect, it, vi } from 'vitest'

import { listConversations, sendMessageSSE } from '@/api/assistant'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/client', () => ({
  ApiError: class extends Error {},
  withAuthRetry: (_path: string, call: (token: null) => Promise<Response>) =>
    call(null),
}))

describe('assistant API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('puts each call in the organization it is given', async () => {
    const fetch = vi.fn(async () => Response.json([]))
    vi.stubGlobal('fetch', fetch)
    await listConversations('acme', { limit: 5 })
    expect(fetch).toHaveBeenCalledWith(
      '/assistant/organizations/acme/conversations?limit=5',
      expect.anything(),
    )
  })

  it('streams a message in the organization it is given', async () => {
    const fetch = vi.fn(async () => new Response(''))
    vi.stubGlobal('fetch', fetch)
    await sendMessageSSE('acme', 'c-1', 'hi', {})
    expect(fetch).toHaveBeenCalledWith(
      '/assistant/organizations/acme/conversations/c-1/messages',
      expect.anything(),
    )
  })
})
