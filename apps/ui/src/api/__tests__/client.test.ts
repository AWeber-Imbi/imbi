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
    // src/test/setup.ts stubs VITE_API_URL=http://localhost:8000
    expect(client.API_BASE_URL).toBe('http://localhost:8000')
    expect(client.API_URL).toBe('http://localhost:8000')
  })
})
