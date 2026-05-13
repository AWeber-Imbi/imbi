import { useEffect } from 'react'

import { useNavigate } from 'react-router-dom'

import { useQueryClient } from '@tanstack/react-query'

import { useAuth } from '@/hooks/useAuth'
import { useAuthStore } from '@/stores/authStore'

export function OAuthCallbackPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { accessToken, setTokens } = useAuthStore()
  const { error, user } = useAuth()

  useEffect(() => {
    // The API callback redirects with tokens in the URL fragment:
    //   /auth/callback#access_token=...&refresh_token=...&token_type=bearer
    // Errors come through as ?error=... on the search params instead.
    const search = new URLSearchParams(window.location.search)
    const errorParam = search.get('error')
    if (errorParam) {
      console.error('[OAuth] Authentication failed:', errorParam)
      navigate('/login?error=' + encodeURIComponent(errorParam), {
        replace: true,
      })
      return
    }

    const fragment = window.location.hash.startsWith('#')
      ? window.location.hash.slice(1)
      : ''
    const params = new URLSearchParams(fragment)
    const accessToken = params.get('access_token')
    const refreshToken = params.get('refresh_token')

    if (!accessToken || !refreshToken) {
      console.error('[OAuth] Missing tokens in callback URL')
      navigate('/login?error=no_token', { replace: true })
      return
    }

    setTokens(accessToken, refreshToken)
    queryClient.invalidateQueries({ queryKey: ['organizations'] })

    window.history.replaceState({}, '', '/auth/callback')
  }, [navigate, setTokens, queryClient])

  useEffect(() => {
    if (user) {
      // Check for redirect path from 401 or OAuth flow
      const returnTo =
        sessionStorage.getItem('imbi_redirect_after_login') || '/dashboard'
      sessionStorage.removeItem('imbi_redirect_after_login')
      console.log('[OAuth] Redirecting to:', returnTo)
      navigate(returnTo, { replace: true })
    }
  }, [user, navigate])

  useEffect(() => {
    if (error && accessToken) {
      console.error('[OAuth] Failed to fetch user after token set:', error)
      navigate('/login?error=user_fetch_failed', { replace: true })
    }
  }, [error, accessToken, navigate])

  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="text-center">
        <div className="mb-2 text-lg">Completing authentication...</div>
        <div className="text-muted-foreground text-sm">
          Please wait while we log you in.
        </div>
      </div>
    </div>
  )
}
