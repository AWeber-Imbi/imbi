import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@/hooks/useAuth'
import { getAuthProviders } from '@/api/endpoints'
import { OAuthButton } from '@/components/auth/OAuthButton'
import { LocalLoginForm } from '@/components/auth/LocalLoginForm'
import { AuthDivider } from '@/components/auth/AuthDivider'
import { useTheme } from '@/contexts/ThemeContext'
import logoLight from '@/assets/logo-light.svg'
import logoDark from '@/assets/logo-dark.svg'

const REMEMBERED_EMAIL_KEY = 'imbi_remembered_email'

export function LoginPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { isDarkMode } = useTheme()
  const {
    isAuthenticated,
    isLoading: authLoading,
    login,
    loginWithOAuth,
  } = useAuth()
  const [loginError, setLoginError] = useState<string>('')
  const [rememberedEmail, setRememberedEmail] = useState<string>('')

  const { data: providersData, isLoading: providersLoading } = useQuery({
    queryKey: ['authProviders'],
    queryFn: getAuthProviders,
    staleTime: 10 * 60 * 1000,
    retry: false,
  })

  // Load remembered email on mount
  useEffect(() => {
    const saved = localStorage.getItem(REMEMBERED_EMAIL_KEY)
    if (saved) {
      setRememberedEmail(saved)
    }
  }, [])

  useEffect(() => {
    const error = searchParams.get('error')
    if (error) {
      setLoginError(
        error === 'no_token'
          ? 'Authentication failed: No token received'
          : `Authentication failed: ${error}`,
      )
    }
  }, [searchParams])

  useEffect(() => {
    if (isAuthenticated) {
      // Check if there's a stored redirect path from a 401
      const redirectPath = sessionStorage.getItem('imbi_redirect_after_login')

      if (redirectPath) {
        // Clear the stored path
        sessionStorage.removeItem('imbi_redirect_after_login')
        console.log('[Login] Redirecting to stored path:', redirectPath)
        navigate(redirectPath, { replace: true })
      } else {
        // Default to dashboard
        navigate('/dashboard', { replace: true })
      }
    }
  }, [isAuthenticated, navigate])

  const handlePasswordLogin = async (credentials: {
    email: string
    password: string
  }) => {
    try {
      setLoginError('')
      await login(credentials)
      // Remember email on successful login
      localStorage.setItem(REMEMBERED_EMAIL_KEY, credentials.email)
    } catch (error: unknown) {
      console.error('[Login] Password login failed:', error)
      const axiosErr = error as {
        response?: { data?: { message?: string } }
        message?: string
      }
      setLoginError(
        axiosErr.response?.data?.message ||
          axiosErr.message ||
          'Login failed. Please check your credentials.',
      )
    }
  }

  const handleOAuthLogin = (providerId: string) => {
    setLoginError('')
    loginWithOAuth(providerId)
  }

  if (authLoading || providersLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-tertiary">
        <div className="text-lg">Loading...</div>
      </div>
    )
  }

  const providers = providersData?.providers || []
  const oauthProviders = providers.filter(
    (p) => p.type === 'oauth' && p.enabled,
  )
  const localLoginEnabled = providers.some(
    (p) => p.type === 'password' && p.enabled,
  )

  const showLocalLogin =
    localLoginEnabled || (oauthProviders.length === 0 && providers.length === 0)

  return (
    <div className="flex min-h-screen items-center justify-center bg-tertiary">
      <div className="w-full max-w-md rounded-xl border border-tertiary bg-primary p-8">
        <div className="mb-8 flex flex-col items-center">
          <img
            src={isDarkMode ? logoDark : logoLight}
            alt="Imbi"
            className="mb-4 h-16 w-16"
          />
          <h1 className="mb-2 text-2xl text-primary">Imbi</h1>
        </div>

        {oauthProviders.length > 0 && (
          <div className="mb-6 space-y-3">
            {oauthProviders.map((provider) => (
              <OAuthButton
                key={provider.id}
                provider={provider}
                onClick={() => handleOAuthLogin(provider.id)}
                disabled={authLoading}
              />
            ))}
          </div>
        )}

        {oauthProviders.length > 0 && showLocalLogin && <AuthDivider />}

        {showLocalLogin && (
          <LocalLoginForm
            onSubmit={handlePasswordLogin}
            isLoading={authLoading}
            error={loginError}
            initialEmail={rememberedEmail}
          />
        )}

        <div className="mt-6 text-center text-sm text-gray-600">
          Need help? Contact your system administrator
        </div>
      </div>
    </div>
  )
}
