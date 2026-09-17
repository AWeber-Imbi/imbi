import { useQuery } from '@tanstack/react-query'

import { getTagFormats } from '@/api/endpoints'
import type { TagFormat } from '@/types'

/**
 * The tag formats the API validates a release/promote tag against (project
 * type first, then organization). ``formats`` is ``null`` until the lookup
 * settles, and stays ``null`` after a failed lookup: the server is the
 * authority, so no verdict beats a wrong one. ``retry`` re-runs the lookup.
 */
export function useTagFormats(
  orgSlug: string,
  projectId: string,
): { formats: null | TagFormat[]; isError: boolean; retry: () => void } {
  const { data, isError, refetch } = useQuery({
    enabled: !!orgSlug && !!projectId,
    queryFn: ({ signal }) => getTagFormats(orgSlug, projectId, signal),
    queryKey: ['tagFormats', orgSlug, projectId],
    staleTime: 5 * 60 * 1000,
  })
  return {
    formats: data ?? null,
    isError,
    retry: () => {
      void refetch()
    },
  }
}
