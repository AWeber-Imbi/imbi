import type { TokenResponse } from '@/types'

export interface BootstrapDeps {
  accessToken: null | string
  clearTokens: () => void
  isTokenExpired: () => boolean
  onRedirect: () => void
  pathname: string
  refreshTokenApi: () => Promise<TokenResponse>
  search: string
  setTokens: (access: string) => void
}

// Resolves on every outcome; callers wait for the returned promise, then
// render. The refresh token lives in an HttpOnly cookie (C2), so we always
// attempt a refresh and let the API decide whether the session is still
// valid. BootstrapGate guarantees this runs at most once (see its dedupe
// guard), so the API's refresh-token rotation/reuse detection is never
// tripped by a duplicate bootstrap.
export async function bootstrapAuth(deps: BootstrapDeps): Promise<void> {
  if (deps.accessToken && !deps.isTokenExpired()) return

  try {
    const response = await deps.refreshTokenApi()
    deps.setTokens(response.access_token)
  } catch (error) {
    console.error('[Auth] Token refresh failed during initialization:', error)
    deps.clearTokens()
    triggerRedirect(deps)
  }
}

function triggerRedirect(deps: BootstrapDeps): void {
  if (deps.pathname === '/login') return
  sessionStorage.setItem(
    'imbi_redirect_after_login',
    deps.pathname + deps.search,
  )
  deps.onRedirect()
}
