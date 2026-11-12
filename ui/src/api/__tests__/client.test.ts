import { afterEach, describe, expect, it, vi } from 'vitest'

// The injected host (imbi.internal) is deliberately different from the
// jsdom document origin (http://localhost) so the assertions prove the
// request base is rebuilt same-origin rather than reusing the injected host.
const w = window as unknown as { __IMBI_API_URL__?: string }

describe('api client base URL resolution', () => {
  afterEach(() => {
    delete w.__IMBI_API_URL__
    vi.resetModules()
  })

  it('uses a same-origin path for requests, dropping the injected host', async () => {
    w.__IMBI_API_URL__ = 'https://imbi.internal/api'
    vi.resetModules()
    const client = await import('../client')
    expect(client.API_BASE_URL).toBe('/api')
    expect(client.apiUrl('/projects')).toBe('/api/projects')
  })

  it('keeps the absolute injected URL for IdP callback display', async () => {
    w.__IMBI_API_URL__ = 'https://imbi.internal/api'
    vi.resetModules()
    const client = await import('../client')
    expect(client.API_URL).toBe('https://imbi.internal/api')
  })

  it('trims a trailing slash from API_URL so callback URLs avoid `//`', async () => {
    w.__IMBI_API_URL__ = 'https://imbi.internal/api/'
    vi.resetModules()
    const client = await import('../client')
    expect(client.API_URL).toBe('https://imbi.internal/api')
  })

  it('handles a root-mounted API (no prefix) as a same-origin root', async () => {
    w.__IMBI_API_URL__ = 'https://imbi.internal'
    vi.resetModules()
    const client = await import('../client')
    expect(client.API_BASE_URL).toBe('')
    expect(client.apiUrl('/auth/token')).toBe('/auth/token')
  })

  it('falls back to VITE_API_URL verbatim when not injected (dev)', async () => {
    delete w.__IMBI_API_URL__
    vi.resetModules()
    const client = await import('../client')
    // test/setup.ts stubs VITE_API_URL=http://localhost:8000
    expect(client.API_BASE_URL).toBe('http://localhost:8000')
    expect(client.API_URL).toBe('http://localhost:8000')
  })
})

function makeJwt(exp: number) {
  const payload = btoa(JSON.stringify({ exp, iat: 1600000000, sub: 'u' }))
  return `e30.${payload}.sig`
}

describe('refreshAccessToken', () => {
  const nav = navigator as unknown as { locks?: unknown }
  const fresh = makeJwt(Math.floor(Date.now() / 1000) + 3600)

  afterEach(() => {
    delete nav.locks
    vi.mocked(localStorage.getItem).mockReturnValue(null)
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  async function load() {
    vi.resetModules()
    const client = await import('../client')
    const { useAuthStore } = await import('../../stores/authStore')
    return { client, useAuthStore }
  }

  function stubFetch() {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ access_token: fresh }), { status: 200 }),
      )
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
  }

  it('adopts a token another tab stored while this tab waited for the lock', async () => {
    const { client, useAuthStore } = await load()
    useAuthStore.getState().setTokens(makeJwt(1))
    const fetchMock = stubFetch()
    const request = vi.fn(async (_name: string, cb: () => Promise<string>) => {
      // The other tab refreshed and persisted its token first.
      vi.mocked(localStorage.getItem).mockReturnValue(
        JSON.stringify({
          state: { accessToken: fresh, tokenExpiry: Date.now() + 3600_000 },
          version: 0,
        }),
      )
      return cb()
    })
    nav.locks = { request }

    await expect(client.refreshAccessToken()).resolves.toBe(fresh)
    expect(request).toHaveBeenCalledWith('imbi-refresh', expect.any(Function))
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('calls the endpoint under the lock when no other tab refreshed', async () => {
    const { client, useAuthStore } = await load()
    useAuthStore.getState().setTokens(makeJwt(1))
    const fetchMock = stubFetch()
    nav.locks = {
      request: (_name: string, cb: () => Promise<string>) => cb(),
    }

    await expect(client.refreshAccessToken()).resolves.toBe(fresh)
    expect(fetchMock).toHaveBeenCalledOnce()
    expect(useAuthStore.getState().accessToken).toBe(fresh)
  })

  it('shares one refresh with the bootstrap path in endpoints', async () => {
    const { client } = await load()
    const endpoints = await import('../endpoints')
    const fetchMock = stubFetch()

    const [a, b] = await Promise.all([
      endpoints.refreshToken(),
      client.refreshAccessToken(),
    ])
    expect(a.access_token).toBe(fresh)
    expect(b).toBe(fresh)
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('calls the endpoint directly when Web Locks are not available', async () => {
    const { client } = await load()
    const fetchMock = stubFetch()

    await expect(client.refreshAccessToken()).resolves.toBe(fresh)
    expect(fetchMock).toHaveBeenCalledOnce()
  })
})
