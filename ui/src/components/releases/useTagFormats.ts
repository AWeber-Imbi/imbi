import { useQuery } from '@tanstack/react-query'

import { getTagFormats } from '@/api/endpoints'
import type { TagFormat } from '@/types'

/**
 * The tag formats the API validates a release/promote tag against (project
 * type first, then organization). ``formats`` is ``null`` until the lookup
 * settles so callers can hold submission rather than flash a wrong verdict;
 * a failed lookup falls back to ``[]`` (semver, the UI's no-policy default).
 */
export function useTagFormats(
  orgSlug: string,
  projectId: string,
): { formats: null | TagFormat[] } {
  const { data, isError } = useQuery({
    enabled: !!orgSlug && !!projectId,
    queryFn: ({ signal }) => getTagFormats(orgSlug, projectId, signal),
    queryKey: ['tagFormats', orgSlug, projectId],
    staleTime: 5 * 60 * 1000,
  })
  return { formats: data ?? (isError ? [] : null) }
}
