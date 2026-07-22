import { useMemo } from 'react'

import { useQuery } from '@tanstack/react-query'

import { listAdminUsers } from '@/api/endpoints'

export function useUserDisplayNames() {
  const {
    data: users = [],
    isError,
    refetch,
  } = useQuery({
    queryFn: ({ signal }) => listAdminUsers({ is_active: true }, signal),
    queryKey: ['admin-users', 'active'],
    staleTime: 5 * 60_000,
  })

  const displayNames = useMemo(() => {
    const m = new Map<string, string>()
    for (const u of users) {
      if (u.email && u.display_name) m.set(u.email, u.display_name)
    }
    return m
  }, [users])

  return { displayNames, isError, refetch, users }
}
