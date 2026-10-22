import { useEffect, useState } from 'react'

import { useNavigate, useSearchParams } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'

import { getAuthProviders, isMfaRequiredError } from '@/api/endpoints'
import logoDark from '@/assets/logo-dark.svg'
import logoLight from '@/assets/logo-light.svg'
import { AuthDivider } from '@/components/auth/AuthDivider'
import { LocalLoginForm } from '@/components/auth/LocalLoginForm'
import { MfaCodeForm } from '@/components/auth/MfaCodeForm'
import { OAuthButton } from '@/components/auth/OAuthButton'
import { useTheme } from '@/contexts/ThemeContext'
import { useAuth } from '@/hooks/useAuth'
import { usePageTitle } from '@/hooks/usePageTitle'
import { extractApiErrorDetail } from '@/lib/apiError'
import {
  performPostLoginRedirect,
  resolvePostLoginTarget,
} from '@/lib/postLoginRedirect'
import { queryKeys } from '@/lib/queryKeys'
import type { LoginRequest } from '@/types'

const REMEMBERED_EMAIL_KEY = 'imbi_remembered_email'

export function LoginPage() {
  usePageTitle('Login')
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
  // Set when the API asks for an MFA code; the login is sent again with it.
  const [mfaCredentials, setMfaCredentials] = useState<LoginRequest | null>(
    null,
  )

  const { data: providersData, isLoading: providersLoading } = useQuery({
    queryFn: ({ signal }) => getAuthProviders(signal),
    queryKey: queryKeys.publicAuthProviders(),
    retry: false,
    staleTime: 10 * 60 * 1000,
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
      // Prefer an OAuth `return_to` (MCP login bounces here with it), then a
      // path stored on a prior 401. Absolute same-origin URLs (the API
      // /authorize endpoint) trigger a full-page load so the access cookie is
      // sent; relative paths stay in-SPA.
      const target = resolvePostLoginTarget(
        searchParams.get('return_to'),
        sessionStorage.getItem('imbi_redirect_after_login'),
      )
      sessionStorage.removeItem('imbi_redirect_after_login')
      performPostLoginRedirect(target, navigate)
    }
  }, [isAuthenticated, navigate, searchParams])

  const handlePasswordLogin = async (credentials: LoginRequest) => {
    try {
      setLoginError('')
      await login(credentials)
      // Remember email on successful login
      localStorage.setItem(REMEMBERED_EMAIL_KEY, credentials.email)
    } catch (error: unknown) {
      if (isMfaRequiredError(error)) {
        setMfaCredentials(credentials)
        return
      }
      console.error('[Login] Password login failed:', error)
      setLoginError(
        extractApiErrorDetail(
          error,
          'Login failed. Please check your credentials.',
        ),
      )
    }
  }

  const handleOAuthLogin = (providerId: string) => {
    setLoginError('')
    loginWithOAuth(providerId)
  }

  if (authLoading || providersLoading) {
    return (
      <div className="bg-tertiary flex min-h-screen items-center justify-center">
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
  const showOAuth = oauthProviders.length > 0 && !mfaCredentials

  return (
    <div className="bg-tertiary flex min-h-screen items-center justify-center">
      <div className="border-tertiary bg-primary w-full max-w-md rounded-xl border p-8">
        <div className="mb-8 flex flex-col items-center">
          <img
            alt="Imbi"
            className="mb-4 size-16"
            src={isDarkMode ? logoDark : logoLight}
          />
          <h1 className="text-primary mb-2 text-2xl">Imbi</h1>
        </div>

        {showOAuth && (
          <div className="mb-6 space-y-3">
            {oauthProviders.map((provider) => (
              <OAuthButton
                disabled={authLoading}
                key={provider.id}
                onClick={() => handleOAuthLogin(provider.id)}
                provider={provider}
              />
            ))}
          </div>
        )}

        {showOAuth && showLocalLogin && <AuthDivider />}

        {mfaCredentials && (
          <MfaCodeForm
            error={loginError}
            isLoading={authLoading}
            onCancel={() => {
              setMfaCredentials(null)
              setLoginError('')
            }}
            onSubmit={(mfa_code) =>
              handlePasswordLogin({ ...mfaCredentials, mfa_code })
            }
          />
        )}

        {showLocalLogin && !mfaCredentials && (
          <LocalLoginForm
            error={loginError}
            initialEmail={rememberedEmail}
            isLoading={authLoading}
            onSubmit={handlePasswordLogin}
          />
        )}

        <div className="mt-6 text-center text-sm text-gray-600">
          Need help? Contact your system administrator
        </div>
      </div>
    </div>
  )
}
