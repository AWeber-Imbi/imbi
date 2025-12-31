import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getCurrentUser } from '@/api/endpoints'
import type { User } from '@/types'

export function useAuth() {
  const queryClient = useQueryClient()

  const { data: user, isLoading, error } = useQuery<User>({
    queryKey: ['currentUser'],
    queryFn: getCurrentUser,
    retry: false,
    // Don't refetch automatically - user session is managed server-side
    staleTime: Infinity,
  })

  const logout = async () => {
    // Clear the query cache
    queryClient.clear()
    // Redirect to logout endpoint (backend will clear session and redirect)
    window.location.href = '/ui/logout'
  }

  return {
    user,
    isAuthenticated: !!user && !error,
    isLoading,
    logout,
  }
}
