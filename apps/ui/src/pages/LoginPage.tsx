import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@/hooks/useAuth'
import { getAuthProviders } from '@/api/endpoints'
import { OAuthButton } from '@/components/auth/OAuthButton'
import { LocalLoginForm } from '@/components/auth/LocalLoginForm'
import { AuthDivider } from '@/components/auth/AuthDivider'
import imbiLogo from '@/assets/logo.svg'

const REMEMBERED_EMAIL_KEY = 'imbi_remembered_email'

export function LoginPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { isAuthenticated, isLoading: authLoading, login, loginWithOAuth } = useAuth()
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
          : `Authentication failed: ${error}`
      )
    }
  }, [searchParams])

  useEffect(() => {
    if (isAuthenticated) {
      navigate('/dashboard', { replace: true })
    }
  }, [isAuthenticated, navigate])

  const handlePasswordLogin = async (credentials: { email: string; password: string }) => {
    try {
      setLoginError('')
      await login(credentials)
      // Remember email on successful login
      localStorage.setItem(REMEMBERED_EMAIL_KEY, credentials.email)
    } catch (error: any) {
      console.error('[Login] Password login failed:', error)
      setLoginError(
        error.response?.data?.message ||
        error.message ||
        'Login failed. Please check your credentials.'
      )
    }
  }

  const handleOAuthLogin = (providerId: string) => {
    setLoginError('')
    loginWithOAuth(providerId)
  }

  if (authLoading || providersLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-slate-50">
        <div className="text-lg">Loading...</div>
      </div>
    )
  }

  const providers = providersData?.providers || []
  const oauthProviders = providers.filter(p => p.type === 'oauth' && p.enabled)
  const localLoginEnabled = providers.some(p => p.type === 'password' && p.enabled)

  const showLocalLogin = localLoginEnabled || (oauthProviders.length === 0 && providers.length === 0)

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <div className="w-full max-w-md p-8 rounded-xl border bg-white border-gray-200">
        <div className="flex flex-col items-center mb-8">
          <img src={imbiLogo} alt="Imbi" className="w-16 h-16 mb-4" />
          <h1 className="text-2xl mb-2 text-gray-900">
            Imbi
          </h1>
        </div>

        {oauthProviders.length > 0 && (
          <div className="space-y-3 mb-6">
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
