import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { useAuth } from '@/hooks/useAuth'

export function OAuthCallbackPage() {
  const navigate = useNavigate()
  const { setAccessToken } = useAuthStore()
  const { user } = useAuth()

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

    window.history.replaceState({}, '', '/auth/callback')
  }, [navigate, setAccessToken])

  useEffect(() => {
    if (user) {
      const returnTo = sessionStorage.getItem('returnTo') || '/dashboard'
      sessionStorage.removeItem('returnTo')
      navigate(returnTo, { replace: true })
    }
  }, [user, navigate])

  return (
    <div className="flex items-center justify-center min-h-screen">
      <div className="text-center">
        <div className="text-lg mb-2">Completing authentication...</div>
        <div className="text-sm text-muted-foreground">
          Please wait while we log you in.
        </div>
      </div>
    </div>
  )
}
