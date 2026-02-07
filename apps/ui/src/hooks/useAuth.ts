import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import {
  loginWithPassword,
  logoutAuth,
  refreshToken as refreshTokenApi,
  getUserByUsername
} from '@/api/endpoints'
import type { UserResponse, LoginRequest, UseAuthReturn } from '@/types'

export function useAuth(): UseAuthReturn {
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const { accessToken, refreshToken, setTokens, clearTokens, getUsername, isTokenExpired } = useAuthStore()

  const { data: user, isLoading, error, refetch } = useQuery<UserResponse>({
    queryKey: ['currentUser', getUsername()],
    queryFn: async () => {
      const username = getUsername()
      if (!username) {
        throw new Error('No username found in token')
      }
      try {
        return await getUserByUsername(username)
      } catch (error: any) {
        console.error('[Auth] Error fetching user:', error)
        // Check if it's a "user not found or inactive" error
        if (error.response?.status === 401 && error.response?.data?.detail?.includes('not found or inactive')) {
          console.log('[Auth] User not found or inactive, clearing tokens')
          clearTokens()
          throw new Error('Your account is not active. Please contact your administrator.')
        }
        // For other 401 errors, let the API client handle the redirect
        // Don't interfere with the redirect flow
        throw error
      }
    },
    enabled: !!accessToken && !isTokenExpired(),
    retry: false,
    staleTime: Infinity,
  })

  useQuery({
    queryKey: ['authInit'],
    queryFn: async () => {
      if (!accessToken || isTokenExpired()) {
        if (!refreshToken) {
          clearTokens()
          if (location.pathname !== '/login') {
            // Save current path before redirecting to login
            const currentPath = location.pathname + location.search
            sessionStorage.setItem('imbi_redirect_after_login', currentPath)
            navigate('/login', { replace: true })
          }
          throw new Error('No refresh token available')
        }
        try {
          const response = await refreshTokenApi(refreshToken)
          setTokens(response.access_token, response.refresh_token)
          await refetch()
        } catch (error) {
          console.error('[Auth] Token refresh failed during initialization:', error)
          clearTokens()
          if (location.pathname !== '/login') {
            // Save current path before redirecting to login
            const currentPath = location.pathname + location.search
            sessionStorage.setItem('imbi_redirect_after_login', currentPath)
            navigate('/login', { replace: true })
          }
          throw error
        }
      }
      return true
    },
    enabled: true,
    retry: false,
    staleTime: Infinity,
  })

  const loginMutation = useMutation({
    mutationFn: loginWithPassword,
    onSuccess: async (data) => {
      setTokens(data.access_token, data.refresh_token)

      try {
        await refetch()
        // This redirect is now handled in LoginPage
        // to be consistent with OAuth flow
      } catch (error: any) {
        console.error('[Auth] Failed to fetch user after login:', error)
        // Re-throw to show error on login page
        throw error
      }
    },
    onError: (error) => {
      console.error('[Auth] Login failed:', error)
    }
  })

  const logoutMutation = useMutation({
    mutationFn: logoutAuth,
    onSuccess: () => {
      clearTokens()
      queryClient.clear()
      // Note: We intentionally keep the remembered email in localStorage
      // so users don't have to re-type it on next login

      // Use window.location to ensure navigation happens even if React state is clearing
      window.location.href = '/login'
    },
    onError: (error) => {
      console.error('[Auth] Logout failed:', error)
      clearTokens()
      queryClient.clear()

      // Use window.location to ensure navigation happens even if React state is clearing
      window.location.href = '/login'
    }
  })

  const refreshTokenMutation = useMutation({
    mutationFn: async () => {
      if (!refreshToken) {
        throw new Error('No refresh token available')
      }
      return refreshTokenApi(refreshToken)
    },
    onSuccess: async (data) => {
      setTokens(data.access_token, data.refresh_token)
      await refetch()
    },
    onError: () => {
      clearTokens()
      if (location.pathname !== '/login') {
        // Save current path before redirecting to login
        const currentPath = location.pathname + location.search
        sessionStorage.setItem('imbi_redirect_after_login', currentPath)
        navigate('/login', { replace: true })
      }
    }
  })

  const loginWithOAuth = (providerId: string) => {
    const currentPath = window.location.pathname + window.location.search
    if (currentPath !== '/login') {
      sessionStorage.setItem('imbi_redirect_after_login', currentPath)
    }
    window.location.href = `/auth/oauth/${providerId}`
  }

  return {
    user: user ?? null,
    isAuthenticated: !!user && !!accessToken,
    isLoading: isLoading || loginMutation.isPending,
    error: loginMutation.error ?? error ?? null,
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
  }
}
