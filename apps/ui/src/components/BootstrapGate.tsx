import { useEffect, useState } from 'react'

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

  useEffect(() => {
    const store = useAuthStore.getState()
    bootstrapAuth({
      accessToken: store.accessToken,
      clearTokens: store.clearTokens,
      isTokenExpired: store.isTokenExpired,
      onRedirect: () => navigate('/login', { replace: true }),
      pathname: location.pathname,
      refreshToken: store.refreshToken,
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
