import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
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
  const queryClient = useQueryClient()
  const { accessToken, setAccessToken, clearTokens, getUsername, isTokenExpired } = useAuthStore()

  const { data: user, isLoading, error, refetch } = useQuery<User>({
    queryKey: ['currentUser', getUsername()],
    queryFn: async () => {
      const username = getUsername()
      if (!username) {
        throw new Error('No username found in token')
      }
      return getUserByUsername(username)
    },
    enabled: !!accessToken && !isTokenExpired(),
    retry: false,
    staleTime: Infinity,
  })

  useQuery({
    queryKey: ['authInit'],
    queryFn: async () => {
      if (!accessToken || isTokenExpired()) {
        try {
          const response = await refreshTokenApi()
          setAccessToken(response.access_token)
          await refetch()
        } catch (error) {
          console.error('[Auth] Token refresh failed during initialization:', error)
          clearTokens()
          navigate('/login', { replace: true })
          throw error
        }
      }
      return true
    },
    retry: false,
    staleTime: Infinity,
  })

  const loginMutation = useMutation({
    mutationFn: loginWithPassword,
    onSuccess: async (data) => {
      setAccessToken(data.access_token)

      await refetch()

      const returnTo = sessionStorage.getItem('returnTo') || '/dashboard'
      sessionStorage.removeItem('returnTo')
      navigate(returnTo, { replace: true })
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
    mutationFn: refreshTokenApi,
    onSuccess: async (data) => {
      setAccessToken(data.access_token)
      await refetch()
    },
    onError: () => {
      clearTokens()
      navigate('/login', { replace: true })
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
    isAuthenticated: !!user && !!accessToken && !error,
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
