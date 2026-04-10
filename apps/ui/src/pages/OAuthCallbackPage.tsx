import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useAuthStore } from '@/stores/authStore'
import { useAuth } from '@/hooks/useAuth'

export function OAuthCallbackPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { accessToken, setAccessToken } = useAuthStore()
  const { user, error } = useAuth()

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const token = params.get('token')
    const error = params.get('error')

    if (error) {
      console.error('[OAuth] Authentication failed:', error)
      navigate('/login?error=' + encodeURIComponent(error), { replace: true })
      return
    }

    if (!token) {
      console.error('[OAuth] No token in callback URL')
      navigate('/login?error=no_token', { replace: true })
      return
    }

    setAccessToken(token)
    queryClient.invalidateQueries({ queryKey: ['organizations'] })

    window.history.replaceState({}, '', '/auth/callback')
  }, [navigate, setAccessToken, queryClient])

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
        <div className="text-sm text-muted-foreground">
          Please wait while we log you in.
        </div>
      </div>
    </div>
  )
}
