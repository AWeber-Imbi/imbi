// Pins the observable behavior of useAuth before the refactor described in
// docs/auth-refactor.md. All 16 cases must pass against the current
// implementation; after the refactor, the same suite must pass unchanged.
//
// The suite covers the five "hidden behaviors" the doc calls out:
//   HB-1 — no flash of /login while an expired token is being refreshed
//   HB-2 — sessionStorage.imbi_redirect_after_login write semantics
//   HB-3 — bootstrap fires at most once across multiple useAuth() consumers
//   HB-4 — currentUser auto-fires once the store flips isTokenExpired → false
//   HB-5 — 401 with detail "not found or inactive" → translated error
import { type ReactNode, useEffect } from 'react'

import { MemoryRouter, useLocation } from 'react-router-dom'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../api/client'
import * as endpoints from '../../api/endpoints'
import { BootstrapGate } from '../../components/BootstrapGate'
import { useAuthStore } from '../../stores/authStore'
import { useAuth } from '../useAuth'

vi.mock('@/api/endpoints', () => ({
  getUserByUsername: vi.fn(),
  loginWithPassword: vi.fn(),
  logoutAuth: vi.fn(),
  refreshToken: vi.fn(),
}))

function makeJwt({
  exp = Math.floor(Date.now() / 1000) + 3600,
  sub = 'user@example.com',
}: { exp?: number; sub?: string } = {}) {
  const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
  const payload = btoa(JSON.stringify({ exp, iat: 1600000000, sub }))
  return `${header}.${payload}.signature`
}

const validUser = {
  display_name: 'Test User',
  email: 'user@example.com',
  email_address: 'user@example.com',
  is_active: true,
  is_admin: false,
  user_type: 'standard',
  username: 'user@example.com',
}

let latestLocation: { pathname: string; search: string } = {
  pathname: '/',
  search: '',
}

function LocationProbe() {
  const loc = useLocation()
  useEffect(() => {
    latestLocation = { pathname: loc.pathname, search: loc.search }
  }, [loc.pathname, loc.search])
  return null
}

function setExpiredAccess({
  refreshToken = 'rt',
}: {
  refreshToken?: null | string
} = {}) {
  const token = makeJwt({ exp: Math.floor(Date.now() / 1000) - 3600 })
  useAuthStore.setState({
    accessToken: token,
    refreshToken,
    tokenExpiry: Date.now() - 1000,
  })
  return token
}

function setupEnv(initialPath: string) {
  const qc = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { gcTime: 0, retry: false },
    },
  })
  // Match App.tsx: session bootstrap happens inside BootstrapGate, not inside
  // useAuth. Wrapping the hook under the gate keeps the 16-case suite honest
  // as an integration test across the gate + hook.
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialPath]}>
        <LocationProbe />
        <BootstrapGate fallback={null}>{children}</BootstrapGate>
      </MemoryRouter>
    </QueryClientProvider>
  )
  return { qc, Wrapper }
}

function setValidAccess() {
  const exp = Math.floor(Date.now() / 1000) + 3600
  const token = makeJwt({ exp })
  useAuthStore.setState({
    accessToken: token,
    refreshToken: 'rt',
    tokenExpiry: exp * 1000,
  })
  return token
}

// window.location stub: logout writes `window.location.href = '/login'`. We
// replace window.location with a plain object so the assignment is observable
// and does not emit jsdom "Not implemented: navigation" warnings.
let locationHref = 'http://localhost/'
beforeEach(() => {
  locationHref = 'http://localhost/'
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: {
      assign: vi.fn((v: string) => {
        locationHref = v
      }),
      get href() {
        return locationHref
      },
      set href(v: string) {
        locationHref = v
      },
      origin: 'http://localhost',
      get pathname() {
        try {
          return new URL(locationHref, 'http://localhost').pathname
        } catch {
          return '/'
        }
      },
      replace: vi.fn((v: string) => {
        locationHref = v
      }),
      get search() {
        try {
          return new URL(locationHref, 'http://localhost').search
        } catch {
          return ''
        }
      },
    },
  })
})

describe('useAuth', () => {
  beforeEach(() => {
    useAuthStore.getState().clearTokens()
    sessionStorage.clear()
    vi.clearAllMocks()
    latestLocation = { pathname: '/', search: '' }
  })

  afterEach(() => {
    useAuthStore.getState().clearTokens()
  })

  // ── Bootstrap matrix ────────────────────────────────────────────────

  it('no tokens on /login: no redirect, no API calls', async () => {
    const { Wrapper } = setupEnv('/login')
    const { result } = renderHook(() => useAuth(), { wrapper: Wrapper })

    // Let React Query drain its microtask queue.
    await act(async () => {
      await Promise.resolve()
    })

    expect(endpoints.refreshToken).not.toHaveBeenCalled()
    expect(endpoints.getUserByUsername).not.toHaveBeenCalled()
    expect(sessionStorage.getItem('imbi_redirect_after_login')).toBeNull()
    expect(latestLocation.pathname).toBe('/login')
    expect(result.current.isAuthenticated).toBe(false)
  })

  it('no tokens on a protected path: redirects to /login, saves path, no API calls', async () => {
    const { Wrapper } = setupEnv('/projects')
    renderHook(() => useAuth(), { wrapper: Wrapper })

    await waitFor(() => expect(latestLocation.pathname).toBe('/login'))
    expect(sessionStorage.getItem('imbi_redirect_after_login')).toBe(
      '/projects',
    )
    expect(endpoints.refreshToken).not.toHaveBeenCalled()
    expect(endpoints.getUserByUsername).not.toHaveBeenCalled()
  })

  it('valid access token: fetches currentUser once, does not refresh', async () => {
    setValidAccess()
    vi.mocked(endpoints.getUserByUsername).mockResolvedValue(validUser as never)

    const { Wrapper } = setupEnv('/dashboard')
    const { result } = renderHook(() => useAuth(), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isAuthenticated).toBe(true))
    expect(endpoints.getUserByUsername).toHaveBeenCalledTimes(1)
    expect(endpoints.getUserByUsername).toHaveBeenCalledWith(
      'user@example.com',
      expect.any(AbortSignal),
    )
    expect(endpoints.refreshToken).not.toHaveBeenCalled()
    expect(latestLocation.pathname).toBe('/dashboard')
  })

  it('HB-1: expired access + valid refresh succeeds: refreshes, fetches user, never lands on /login', async () => {
    setExpiredAccess()
    const newToken = makeJwt({ exp: Math.floor(Date.now() / 1000) + 3600 })
    vi.mocked(endpoints.refreshToken).mockResolvedValue({
      access_token: newToken,
      expires_in: 3600,
      refresh_token: 'rt-new',
      token_type: 'bearer',
    } as never)
    vi.mocked(endpoints.getUserByUsername).mockResolvedValue(validUser as never)

    const { Wrapper } = setupEnv('/dashboard')
    const { result } = renderHook(() => useAuth(), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isAuthenticated).toBe(true))
    expect(endpoints.refreshToken).toHaveBeenCalledTimes(1)
    expect(endpoints.refreshToken).toHaveBeenCalledWith('rt')
    expect(endpoints.getUserByUsername).toHaveBeenCalled()
    expect(latestLocation.pathname).toBe('/dashboard')
    expect(useAuthStore.getState().accessToken).toBe(newToken)
    expect(useAuthStore.getState().refreshToken).toBe('rt-new')
  })

  it('expired access + valid refresh fails: clears tokens, redirects with saved path (including search)', async () => {
    setExpiredAccess()
    vi.mocked(endpoints.refreshToken).mockRejectedValue(new Error('nope'))

    const { Wrapper } = setupEnv('/projects?filter=x')
    renderHook(() => useAuth(), { wrapper: Wrapper })

    await waitFor(() => expect(latestLocation.pathname).toBe('/login'))
    expect(useAuthStore.getState().accessToken).toBeNull()
    expect(sessionStorage.getItem('imbi_redirect_after_login')).toBe(
      '/projects?filter=x',
    )
    expect(endpoints.getUserByUsername).not.toHaveBeenCalled()
  })

  it('expired access + no refresh token: redirects, saves path, no refresh API call', async () => {
    setExpiredAccess({ refreshToken: null })

    const { Wrapper } = setupEnv('/projects')
    renderHook(() => useAuth(), { wrapper: Wrapper })

    await waitFor(() => expect(latestLocation.pathname).toBe('/login'))
    expect(endpoints.refreshToken).not.toHaveBeenCalled()
    expect(sessionStorage.getItem('imbi_redirect_after_login')).toBe(
      '/projects',
    )
  })

  // ── De-duplication ──────────────────────────────────────────────────

  it('HB-3: two useAuth consumers in one render pass trigger refreshToken exactly once', async () => {
    setExpiredAccess()
    const newToken = makeJwt({ exp: Math.floor(Date.now() / 1000) + 3600 })
    vi.mocked(endpoints.refreshToken).mockResolvedValue({
      access_token: newToken,
      expires_in: 3600,
      refresh_token: 'rt-new',
      token_type: 'bearer',
    } as never)
    vi.mocked(endpoints.getUserByUsername).mockResolvedValue(validUser as never)

    const { Wrapper } = setupEnv('/dashboard')
    function Consumer() {
      useAuth()
      return null
    }

    render(
      <Wrapper>
        <Consumer />
        <Consumer />
      </Wrapper>,
    )

    await waitFor(() => expect(endpoints.refreshToken).toHaveBeenCalledTimes(1))
  })

  // ── currentUser 401 specifics ───────────────────────────────────────

  it('HB-5: 401 with "not found or inactive" detail clears tokens', async () => {
    // The currentUser queryFn catches this specific 401, calls clearTokens(),
    // and throws a translated error. The translated error is not stably
    // observable via `useAuth().error` because `clearTokens()` changes the
    // currentUser query key (`getUsername()` flips to null) and the new
    // subscription lands in a fresh empty state before the error render
    // commits. The observable contract is: clearTokens() runs. A future
    // refactor MUST keep at minimum this clearTokens side effect; lifting the
    // translated error to a stable signal is a bonus but not required.
    setValidAccess()
    vi.mocked(endpoints.getUserByUsername).mockRejectedValue(
      new ApiError(401, 'Unauthorized', {
        detail: 'user not found or inactive',
      }),
    )

    const { Wrapper } = setupEnv('/dashboard')
    renderHook(() => useAuth(), { wrapper: Wrapper })

    await waitFor(() => expect(useAuthStore.getState().accessToken).toBeNull())
    expect(endpoints.getUserByUsername).toHaveBeenCalledTimes(1)
  })

  it('currentUser 401 with any other detail: surfaces error as-is, does not clear tokens', async () => {
    const token = setValidAccess()
    const apiErr = new ApiError(401, 'Unauthorized', {
      detail: 'some generic auth failure',
    })
    vi.mocked(endpoints.getUserByUsername).mockRejectedValue(apiErr)

    const { Wrapper } = setupEnv('/dashboard')
    const { result } = renderHook(() => useAuth(), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.error).toBe(apiErr))
    expect(useAuthStore.getState().accessToken).toBe(token)
  })

  // ── Login / logout / refresh mutations ──────────────────────────────

  it('login success: setTokens, invalidates organizations, resolves to a populated user', async () => {
    const token = makeJwt({ exp: Math.floor(Date.now() / 1000) + 3600 })
    vi.mocked(endpoints.loginWithPassword).mockResolvedValue({
      access_token: token,
      expires_in: 3600,
      refresh_token: 'rt-new',
      token_type: 'bearer',
    } as never)
    vi.mocked(endpoints.getUserByUsername).mockResolvedValue(validUser as never)

    const { qc, Wrapper } = setupEnv('/login')
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')
    const { result } = renderHook(() => useAuth(), { wrapper: Wrapper })

    await act(async () => {
      await result.current.login({ email: 'u@example.com', password: 'pw' })
    })

    // React Query v5 passes a 2nd context arg to mutationFn, so just assert
    // the first argument (the LoginRequest).
    expect(endpoints.loginWithPassword).toHaveBeenCalledTimes(1)
    expect(vi.mocked(endpoints.loginWithPassword).mock.calls[0][0]).toEqual({
      email: 'u@example.com',
      password: 'pw',
    })
    expect(useAuthStore.getState().accessToken).toBe(token)
    expect(useAuthStore.getState().refreshToken).toBe('rt-new')
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['organizations'],
    })
    await waitFor(() => expect(result.current.user).not.toBeNull())
  })

  it('login failure: error exposed via hook return, user stays null', async () => {
    const err = new Error('invalid credentials')
    vi.mocked(endpoints.loginWithPassword).mockRejectedValue(err)

    const { Wrapper } = setupEnv('/login')
    const { result } = renderHook(() => useAuth(), { wrapper: Wrapper })

    await act(async () => {
      await expect(
        result.current.login({ email: 'u@example.com', password: 'bad' }),
      ).rejects.toThrow()
    })

    await waitFor(() => expect(result.current.error).toBeTruthy())
    expect(result.current.user).toBeNull()
  })

  it('logout success: clearTokens, queryClient.clear, window.location.href = /login', async () => {
    setValidAccess()
    vi.mocked(endpoints.getUserByUsername).mockResolvedValue(validUser as never)
    vi.mocked(endpoints.logoutAuth).mockResolvedValue(undefined as never)

    const { qc, Wrapper } = setupEnv('/dashboard')
    const clearSpy = vi.spyOn(qc, 'clear')
    const { result } = renderHook(() => useAuth(), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isAuthenticated).toBe(true))

    await act(async () => {
      await result.current.logout()
    })

    expect(useAuthStore.getState().accessToken).toBeNull()
    expect(clearSpy).toHaveBeenCalled()
    expect(window.location.href).toBe('/login')
  })

  it('logout failure: same cleanup as success (onError path)', async () => {
    setValidAccess()
    vi.mocked(endpoints.getUserByUsername).mockResolvedValue(validUser as never)
    vi.mocked(endpoints.logoutAuth).mockRejectedValue(new Error('server down'))

    const { qc, Wrapper } = setupEnv('/dashboard')
    const clearSpy = vi.spyOn(qc, 'clear')
    const { result } = renderHook(() => useAuth(), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isAuthenticated).toBe(true))

    await act(async () => {
      await expect(result.current.logout()).rejects.toThrow()
    })

    expect(useAuthStore.getState().accessToken).toBeNull()
    expect(clearSpy).toHaveBeenCalled()
    expect(window.location.href).toBe('/login')
  })

  it('refreshToken mutation success: setTokens and user re-populates', async () => {
    setValidAccess()
    vi.mocked(endpoints.getUserByUsername).mockResolvedValue(validUser as never)
    const newToken = makeJwt({ exp: Math.floor(Date.now() / 1000) + 7200 })
    vi.mocked(endpoints.refreshToken).mockResolvedValue({
      access_token: newToken,
      expires_in: 7200,
      refresh_token: 'rt-new',
      token_type: 'bearer',
    } as never)

    const { Wrapper } = setupEnv('/dashboard')
    const { result } = renderHook(() => useAuth(), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isAuthenticated).toBe(true))

    await act(async () => {
      await result.current.refreshToken()
    })

    expect(endpoints.refreshToken).toHaveBeenCalledWith('rt')
    expect(useAuthStore.getState().accessToken).toBe(newToken)
    expect(useAuthStore.getState().refreshToken).toBe('rt-new')
  })

  it('refreshToken mutation failure on a protected route: clears tokens, redirects with saved path', async () => {
    setValidAccess()
    vi.mocked(endpoints.getUserByUsername).mockResolvedValue(validUser as never)
    vi.mocked(endpoints.refreshToken).mockRejectedValue(new Error('boom'))

    const { Wrapper } = setupEnv('/projects')
    const { result } = renderHook(() => useAuth(), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isAuthenticated).toBe(true))

    await act(async () => {
      await expect(result.current.refreshToken()).rejects.toThrow()
    })

    await waitFor(() => expect(latestLocation.pathname).toBe('/login'))
    expect(useAuthStore.getState().accessToken).toBeNull()
    expect(sessionStorage.getItem('imbi_redirect_after_login')).toBe(
      '/projects',
    )
  })

  // ── Redirect-key invariant (HB-2) ───────────────────────────────────

  it('HB-2: does not write imbi_redirect_after_login when already on /login', async () => {
    setExpiredAccess({ refreshToken: null })

    const { Wrapper } = setupEnv('/login')
    renderHook(() => useAuth(), { wrapper: Wrapper })

    // Let the bootstrap queryFn run to completion.
    await act(async () => {
      await Promise.resolve()
    })

    expect(sessionStorage.getItem('imbi_redirect_after_login')).toBeNull()
    expect(latestLocation.pathname).toBe('/login')
    expect(endpoints.refreshToken).not.toHaveBeenCalled()
  })
})
