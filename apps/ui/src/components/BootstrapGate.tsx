import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { refreshToken as refreshTokenApi } from '@/api/endpoints'
import { useAuthStore } from '@/stores/authStore'
import { bootstrapAuth } from '@/hooks/authBootstrap'

interface BootstrapGateProps {
  children: React.ReactNode
  fallback: React.ReactNode
}

const PUBLIC_PATHS = new Set(['/login', '/auth/callback'])

export function BootstrapGate({ children, fallback }: BootstrapGateProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const [ready, setReady] = useState(false)

  useEffect(() => {
    const store = useAuthStore.getState()
    bootstrapAuth({
      accessToken: store.accessToken,
      refreshToken: store.refreshToken,
      isTokenExpired: store.isTokenExpired,
      setTokens: store.setTokens,
      clearTokens: store.clearTokens,
      refreshTokenApi,
      pathname: location.pathname,
      search: location.search,
      onRedirect: () => navigate('/login', { replace: true }),
    }).finally(() => setReady(true))
    // Bootstrap runs exactly once at app mount. The captured pathname/search
    // is the original URL we want to save as the post-login redirect target.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (PUBLIC_PATHS.has(location.pathname)) return <>{children}</>
  if (!ready) return <>{fallback}</>
  return <>{children}</>
}
