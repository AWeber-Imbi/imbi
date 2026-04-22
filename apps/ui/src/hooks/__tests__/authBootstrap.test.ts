import { beforeEach, describe, expect, it, vi } from 'vitest'
import { bootstrapAuth, type BootstrapDeps } from '../authBootstrap'

function makeDeps(overrides: Partial<BootstrapDeps> = {}): {
  deps: BootstrapDeps
  setTokens: ReturnType<typeof vi.fn>
  clearTokens: ReturnType<typeof vi.fn>
  refreshTokenApi: ReturnType<typeof vi.fn>
  onRedirect: ReturnType<typeof vi.fn>
} {
  const setTokens = vi.fn()
  const clearTokens = vi.fn()
  const refreshTokenApi = vi.fn()
  const onRedirect = vi.fn()
  return {
    deps: {
      accessToken: null,
      refreshToken: null,
      isTokenExpired: () => true,
      setTokens,
      clearTokens,
      refreshTokenApi,
      pathname: '/dashboard',
      search: '',
      onRedirect,
      ...overrides,
    },
    setTokens,
    clearTokens,
    refreshTokenApi,
    onRedirect,
  }
}

describe('bootstrapAuth', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('valid access token: no-op (no refresh, no redirect, no setTokens)', async () => {
    const { deps, clearTokens, refreshTokenApi, setTokens, onRedirect } =
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

  it('no tokens on a protected path: clears, saves redirect, calls onRedirect', async () => {
    const { deps, clearTokens, refreshTokenApi, onRedirect } = makeDeps({
      pathname: '/projects',
      search: '?filter=x',
    })

    await bootstrapAuth(deps)

    expect(clearTokens).toHaveBeenCalledOnce()
    expect(refreshTokenApi).not.toHaveBeenCalled()
    expect(onRedirect).toHaveBeenCalledOnce()
    expect(sessionStorage.getItem('imbi_redirect_after_login')).toBe(
      '/projects?filter=x',
    )
  })

  it('no tokens on /login: clears but does NOT save redirect or call onRedirect', async () => {
    const { deps, clearTokens, onRedirect } = makeDeps({ pathname: '/login' })

    await bootstrapAuth(deps)

    expect(clearTokens).toHaveBeenCalledOnce()
    expect(onRedirect).not.toHaveBeenCalled()
    expect(sessionStorage.getItem('imbi_redirect_after_login')).toBeNull()
  })

  it('expired access + valid refresh, refresh succeeds: setTokens, no redirect', async () => {
    const { deps, setTokens, clearTokens, onRedirect, refreshTokenApi } =
      makeDeps({
        accessToken: 'old',
        refreshToken: 'rt',
      })
    refreshTokenApi.mockResolvedValue({
      access_token: 'new',
      refresh_token: 'rt-new',
      token_type: 'bearer',
      expires_in: 3600,
    })

    await bootstrapAuth(deps)

    expect(refreshTokenApi).toHaveBeenCalledWith('rt')
    expect(setTokens).toHaveBeenCalledWith('new', 'rt-new')
    expect(clearTokens).not.toHaveBeenCalled()
    expect(onRedirect).not.toHaveBeenCalled()
    expect(sessionStorage.getItem('imbi_redirect_after_login')).toBeNull()
  })

  it('expired access + valid refresh, refresh fails on protected path: clears, saves, redirects', async () => {
    const { deps, setTokens, clearTokens, onRedirect, refreshTokenApi } =
      makeDeps({
        accessToken: 'old',
        refreshToken: 'rt',
        pathname: '/projects',
      })
    refreshTokenApi.mockRejectedValue(new Error('boom'))

    await bootstrapAuth(deps)

    expect(refreshTokenApi).toHaveBeenCalledWith('rt')
    expect(setTokens).not.toHaveBeenCalled()
    expect(clearTokens).toHaveBeenCalledOnce()
    expect(onRedirect).toHaveBeenCalledOnce()
    expect(sessionStorage.getItem('imbi_redirect_after_login')).toBe(
      '/projects',
    )
  })

  it('expired access + valid refresh, refresh fails on /login: clears, no redirect, no save', async () => {
    const { deps, clearTokens, onRedirect, refreshTokenApi } = makeDeps({
      accessToken: 'old',
      refreshToken: 'rt',
      pathname: '/login',
    })
    refreshTokenApi.mockRejectedValue(new Error('boom'))

    await bootstrapAuth(deps)

    expect(clearTokens).toHaveBeenCalledOnce()
    expect(onRedirect).not.toHaveBeenCalled()
    expect(sessionStorage.getItem('imbi_redirect_after_login')).toBeNull()
  })

  it('expired access + no refresh token: clears, saves, redirects', async () => {
    const { deps, clearTokens, onRedirect, refreshTokenApi } = makeDeps({
      accessToken: 'old',
      refreshToken: null,
      pathname: '/dashboard',
    })

    await bootstrapAuth(deps)

    expect(refreshTokenApi).not.toHaveBeenCalled()
    expect(clearTokens).toHaveBeenCalledOnce()
    expect(onRedirect).toHaveBeenCalledOnce()
    expect(sessionStorage.getItem('imbi_redirect_after_login')).toBe(
      '/dashboard',
    )
  })

  it('resolves without throwing on any outcome', async () => {
    // The pre-refactor queryFn threw as control flow. bootstrapAuth must not.
    const { deps: a, refreshTokenApi: apiA } = makeDeps({
      accessToken: 'old',
      refreshToken: 'rt',
    })
    apiA.mockRejectedValue(new Error('boom'))
    await expect(bootstrapAuth(a)).resolves.toBeUndefined()

    const { deps: b } = makeDeps({ accessToken: 'old', refreshToken: null })
    await expect(bootstrapAuth(b)).resolves.toBeUndefined()
  })
})
