import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import {
  loginWithPassword,
  logoutAuth,
  refreshToken as refreshTokenApi,
  getUserByUsername
} from '@/api/endpoints'
import type { User, LoginRequest, UseAuthReturn } from '@/types'

export function useAuth(): UseAuthReturn {
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const { accessToken, refreshToken, setTokens, clearTokens, getUsername, isTokenExpired } = useAuthStore()

  const { data: user, isLoading, error, refetch } = useQuery<User>({
    queryKey: ['currentUser', getUsername()],
    queryFn: async () => {
      const username = getUsername()
      if (!username) {
        throw new Error('No username found in token')
      }
      try {
        return await getUserByUsername(username)
      } catch (error: any) {
        if (error.response?.status === 401 && error.response?.data?.detail?.includes('not found or inactive')) {
          clearTokens()
          throw new Error('Your account is not active. Please contact your administrator.')
        }
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
            navigate('/login', { replace: true })
          }
          throw error
        }
      }
      return true
    },
    enabled: location.pathname !== '/login',
    retry: false,
    staleTime: Infinity,
  })

  const loginMutation = useMutation({
    mutationFn: loginWithPassword,
    onSuccess: async (data) => {
      setTokens(data.access_token, data.refresh_token)

      try {
        await refetch()
        const returnTo = sessionStorage.getItem('returnTo') || '/dashboard'
        sessionStorage.removeItem('returnTo')
        navigate(returnTo, { replace: true })
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
      navigate('/login', { replace: true })
    },
    onError: (error) => {
      console.error('[Auth] Logout failed:', error)
      clearTokens()
      queryClient.clear()
      navigate('/login', { replace: true })
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
        navigate('/login', { replace: true })
      }
    }
  })

  const loginWithOAuth = (providerId: string) => {
    const currentPath = window.location.pathname
    if (currentPath !== '/login') {
      sessionStorage.setItem('returnTo', currentPath)
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
