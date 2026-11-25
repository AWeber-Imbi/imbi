import { useQuery } from '@tanstack/react-query'

import { listOperationsLog } from '@/api/endpoints'

export function useRecentDeployments(orgSlug: string, limit = 50) {
  return useQuery({
    enabled: Boolean(orgSlug),
    queryFn: async ({ signal }) => {
      const page = await listOperationsLog(
        orgSlug,
        { filters: { entry_type: 'Deployed' }, limit },
        signal,
      )
      return page.entries
    },
    queryKey: ['recentDeployments', orgSlug, limit],
  })
}
