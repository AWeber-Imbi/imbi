import type { TokenResponse } from '@/types'

export interface BootstrapDeps {
  accessToken: string | null
  refreshToken: string | null
  isTokenExpired: () => boolean
  setTokens: (access: string, refresh: string) => void
  clearTokens: () => void
  refreshTokenApi: (rt: string) => Promise<TokenResponse>
  pathname: string
  search: string
  onRedirect: () => void
}

// Direct port of the previous `['authInit']` queryFn, minus the throws (which
// were only used as dead signalling). Resolves on every outcome; callers wait
// for the returned promise, then render.
export async function bootstrapAuth(deps: BootstrapDeps): Promise<void> {
  if (deps.accessToken && !deps.isTokenExpired()) return

  if (!deps.refreshToken) {
    deps.clearTokens()
    triggerRedirect(deps)
    return
  }

  try {
    const response = await deps.refreshTokenApi(deps.refreshToken)
    deps.setTokens(response.access_token, response.refresh_token)
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
