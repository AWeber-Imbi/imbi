import { useQuery } from '@tanstack/react-query'

import { listOperationsLog } from '@/api/endpoints'

// NOTE(org-scoping): The unscoped `/operations-log/` endpoint does not
// currently accept an `org_slug` filter (see imbi-api
// `endpoints/operations_log.py::list_operation_logs`). The query is keyed
// on `orgSlug` so cache and refetch are scoped per organization, but the
// request payload itself is not org-filtered. When imbi-api adds an
// org-scoped filter or endpoint, plumb `orgSlug` through here.
export function useRecentDeployments(orgSlug: string, limit = 50) {
  return useQuery({
    enabled: Boolean(orgSlug),
    queryFn: async ({ signal }) => {
      const page = await listOperationsLog(
        { filters: { entry_type: 'Deployed' }, limit },
        signal,
      )
      return page.entries
    },
    queryKey: ['recentDeployments', orgSlug, limit],
  })
}
