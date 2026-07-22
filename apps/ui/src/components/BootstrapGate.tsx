import { useEffect, useRef, useState } from 'react'

import { useLocation, useNavigate } from 'react-router-dom'

import { refreshToken as refreshTokenApi } from '@/api/endpoints'
import { bootstrapAuth } from '@/hooks/authBootstrap'
import { useAuthStore } from '@/stores/authStore'

interface BootstrapGateProps {
  children: React.ReactNode
  fallback: React.ReactNode
}

const PUBLIC_PATHS = new Set(['/auth/callback', '/login'])

export function BootstrapGate({ children, fallback }: BootstrapGateProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const [ready, setReady] = useState(false)
  // React StrictMode double-invokes effects in development. Bootstrap must
  // fire only once: it calls /auth/token/refresh, the API rotates the refresh
  // token on first use and treats the second (concurrent) call as token reuse,
  // revoking the whole token family and logging the user straight back out.
  // The ref persists across StrictMode's re-invocation but is per-instance, so
  // it does not leak between tests the way module state would.
  const didBootstrap = useRef(false)

  useEffect(() => {
    if (didBootstrap.current) return
    didBootstrap.current = true
    const store = useAuthStore.getState()
    bootstrapAuth({
      accessToken: store.accessToken,
      clearTokens: store.clearTokens,
      isTokenExpired: store.isTokenExpired,
      onRedirect: () => navigate('/login', { replace: true }),
      pathname: location.pathname,
      refreshTokenApi,
      search: location.search,
      setTokens: store.setTokens,
    }).finally(() => setReady(true))
    // Bootstrap runs exactly once at app mount. The captured pathname/search
    // is the original URL we want to save as the post-login redirect target.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (PUBLIC_PATHS.has(location.pathname)) return <>{children}</>
  if (!ready) return <>{fallback}</>
  return <>{children}</>
}
