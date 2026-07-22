import { beforeEach, describe, expect, it, vi } from 'vitest'

import { bootstrapAuth, type BootstrapDeps } from '../authBootstrap'

function makeDeps(overrides: Partial<BootstrapDeps> = {}): {
  clearTokens: ReturnType<typeof vi.fn>
  deps: BootstrapDeps
  onRedirect: ReturnType<typeof vi.fn>
  refreshTokenApi: ReturnType<typeof vi.fn>
  setTokens: ReturnType<typeof vi.fn>
} {
  const setTokens = vi.fn()
  const clearTokens = vi.fn()
  const refreshTokenApi = vi.fn()
  const onRedirect = vi.fn()
  return {
    clearTokens,
    deps: {
      accessToken: null,
      clearTokens,
      isTokenExpired: () => true,
      onRedirect,
      pathname: '/dashboard',
      refreshTokenApi,
      search: '',
      setTokens,
      ...overrides,
    },
    onRedirect,
    refreshTokenApi,
    setTokens,
  }
}

describe('bootstrapAuth', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('valid access token: no-op (no refresh, no redirect, no setTokens)', async () => {
    const { clearTokens, deps, onRedirect, refreshTokenApi, setTokens } =
      makeDeps({
        accessToken: 'good',
        isTokenExpired: () => false,
      })

    await bootstrapAuth(deps)

    expect(refreshTokenApi).not.toHaveBeenCalled()
    expect(setTokens).not.toHaveBeenCalled()
    expect(clearTokens).not.toHaveBeenCalled()
    expect(onRedirect).not.toHaveBeenCalled()
    expect(sessionStorage.getItem('imbi_redirect_after_login')).toBeNull()
  })

  it('no access token, cookie refresh succeeds: setTokens, no redirect', async () => {
    const { clearTokens, deps, onRedirect, refreshTokenApi, setTokens } =
      makeDeps({ pathname: '/projects', search: '?filter=x' })
    refreshTokenApi.mockResolvedValue({
      access_token: 'new',
      expires_in: 3600,
      refresh_token: 'ignored',
      token_type: 'bearer',
    })

    await bootstrapAuth(deps)

    expect(refreshTokenApi).toHaveBeenCalledOnce()
    expect(setTokens).toHaveBeenCalledWith('new')
    expect(clearTokens).not.toHaveBeenCalled()
    expect(onRedirect).not.toHaveBeenCalled()
    expect(sessionStorage.getItem('imbi_redirect_after_login')).toBeNull()
  })

  it('no access token, cookie refresh fails on protected path: clears, saves, redirects', async () => {
    const { clearTokens, deps, onRedirect, refreshTokenApi, setTokens } =
      makeDeps({ pathname: '/projects', search: '?filter=x' })
    refreshTokenApi.mockRejectedValue(new Error('boom'))

    await bootstrapAuth(deps)

    expect(refreshTokenApi).toHaveBeenCalledOnce()
    expect(setTokens).not.toHaveBeenCalled()
    expect(clearTokens).toHaveBeenCalledOnce()
    expect(onRedirect).toHaveBeenCalledOnce()
    expect(sessionStorage.getItem('imbi_redirect_after_login')).toBe(
      '/projects?filter=x',
    )
  })

  it('refresh fails on /login: clears but does NOT save redirect or call onRedirect', async () => {
    const { clearTokens, deps, onRedirect } = makeDeps({ pathname: '/login' })
    deps.refreshTokenApi = vi.fn().mockRejectedValue(new Error('boom'))

    await bootstrapAuth(deps)

    expect(clearTokens).toHaveBeenCalledOnce()
    expect(onRedirect).not.toHaveBeenCalled()
    expect(sessionStorage.getItem('imbi_redirect_after_login')).toBeNull()
  })

  it('expired access token still attempts a refresh', async () => {
    const { deps, refreshTokenApi, setTokens } = makeDeps({
      accessToken: 'old',
    })
    refreshTokenApi.mockResolvedValue({
      access_token: 'new',
      expires_in: 3600,
      refresh_token: 'ignored',
      token_type: 'bearer',
    })

    await bootstrapAuth(deps)

    expect(refreshTokenApi).toHaveBeenCalledOnce()
    expect(setTokens).toHaveBeenCalledWith('new')
  })

  it('resolves without throwing on any outcome', async () => {
    // The pre-refactor queryFn threw as control flow. bootstrapAuth must not.
    const { deps: a, refreshTokenApi: apiA } = makeDeps({ accessToken: 'old' })
    apiA.mockRejectedValue(new Error('boom'))
    await expect(bootstrapAuth(a)).resolves.toBeUndefined()

    const { deps: b, refreshTokenApi: apiB } = makeDeps({
      accessToken: 'old',
    })
    apiB.mockResolvedValue({
      access_token: 'new',
      expires_in: 3600,
      refresh_token: 'ignored',
      token_type: 'bearer',
    })
    await expect(bootstrapAuth(b)).resolves.toBeUndefined()
  })
})
