import { useLocation, useNavigate } from 'react-router-dom'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError, apiUrl } from '@/api/client'
import {
  getCurrentUser,
  loginWithPassword,
  logoutAuth,
  refreshToken as refreshTokenApi,
} from '@/api/endpoints'
import { useAuthStore } from '@/stores/authStore'
import type { LoginRequest, UseAuthReturn, UserResponse } from '@/types'

// Session bootstrap (refresh-if-expired / redirect-if-no-refresh-token) lives
// in <BootstrapGate> at the app root, not in this hook. useAuth is purely
// ambient state over the Zustand store + the currentUser query + the
// login/logout/refresh mutations.
export function useAuth(): UseAuthReturn {
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  // Subscribe per-field instead of destructuring the whole store: a token
  // tick would otherwise re-render every consumer of useAuth, which sits at
  // the app root and would cascade through the whole tree.
  const accessToken = useAuthStore((s) => s.accessToken)
  const clearTokens = useAuthStore((s) => s.clearTokens)
  const setTokens = useAuthStore((s) => s.setTokens)
  const getUsername = useAuthStore((s) => s.getUsername)
  const isTokenExpired = useAuthStore((s) => s.isTokenExpired)

  const {
    data: user,
    error,
    isLoading,
    refetch,
  } = useQuery<UserResponse>({
    enabled: !!accessToken && !isTokenExpired(),
    queryFn: async ({ signal }) => {
      try {
        // /users/me resolves the caller from the bearer token; no username
        // needed. getUsername() is still used in the queryKey below so the
        // cache is keyed per-user and clearTokens() invalidates it.
        return await getCurrentUser(signal)
      } catch (error) {
        console.error('[Auth] Error fetching user:', error)
        if (error instanceof ApiError && error.status === 401) {
          const data = error.data as undefined | { detail?: string }
          if (data?.detail?.includes('not found or inactive')) {
            clearTokens()
            throw new Error(
              'Your account is not active. Please contact your administrator.',
            )
          }
        }
        throw error
      }
    },
    queryKey: ['currentUser', getUsername()],
    retry: false,
    staleTime: 5 * 60 * 1000,
  })

  const loginMutation = useMutation({
    mutationFn: loginWithPassword,
    onError: (error) => {
      console.error('[Auth] Login failed:', error)
    },
    onSuccess: async (data) => {
      setTokens(data.access_token)
      queryClient.invalidateQueries({ queryKey: ['organizations'] })

      try {
        await refetch()
        // This redirect is now handled in LoginPage
        // to be consistent with OAuth flow
      } catch (error: unknown) {
        console.error('[Auth] Failed to fetch user after login:', error)
        // Re-throw to show error on login page
        throw error
      }
    },
  })

  const logoutMutation = useMutation({
    mutationFn: logoutAuth,
    onError: (error) => {
      console.error('[Auth] Logout failed:', error)
      clearTokens()
      queryClient.clear()

      // Use window.location to ensure navigation happens even if React state is clearing
      window.location.href = '/login'
    },
    onSuccess: () => {
      clearTokens()
      queryClient.clear()
      // Note: We intentionally keep the remembered email in localStorage
      // so users don't have to re-type it on next login

      // Use window.location to ensure navigation happens even if React state is clearing
      window.location.href = '/login'
    },
  })

  const refreshTokenMutation = useMutation({
    mutationFn: () => refreshTokenApi(),
    onError: () => {
      clearTokens()
      if (location.pathname !== '/login') {
        // Save current path before redirecting to login
        const currentPath = location.pathname + location.search
        sessionStorage.setItem('imbi_redirect_after_login', currentPath)
        navigate('/login', { replace: true })
      }
    },
    onSuccess: async (data) => {
      setTokens(data.access_token)
      await refetch()
    },
  })

  const loginWithOAuth = (providerId: string) => {
    const currentPath = window.location.pathname + window.location.search
    if (currentPath !== '/login') {
      sessionStorage.setItem('imbi_redirect_after_login', currentPath)
    }
    // Tell the API to redirect back to the SPA's OAuth callback page,
    // which knows how to parse the token fragment.
    const callback = `${window.location.origin}/auth/callback`
    const url = `${apiUrl(`/auth/oauth/${providerId}`)}?redirect_uri=${encodeURIComponent(callback)}`
    window.location.href = url
  }

  return {
    error: loginMutation.error ?? error ?? null,
    isAuthenticated: !!user && !!accessToken,
    isLoading: isLoading || loginMutation.isPending,
    login: async (credentials: LoginRequest) => {
      await loginMutation.mutateAsync(credentials)
    },
    loginWithOAuth,
    logout: async () => {
      await logoutMutation.mutateAsync()
    },
    refreshToken: async () => {
      await refreshTokenMutation.mutateAsync()
    },
    user: user ?? null,
  }
}
