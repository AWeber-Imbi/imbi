import { useMemo } from 'react'

import { useQuery } from '@tanstack/react-query'

import { getProjectsSlim, type ProjectListItem } from '@/api/endpoints'

/**
 * Fetch the slim projects list for an organization and expose it as a
 * Map keyed by project id alongside the query state.
 */
export function useProjectsSlimMap(orgSlug: string) {
  const { data, isError, isFetching, refetch } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => getProjectsSlim(orgSlug, signal),
    queryKey: ['projects-slim', orgSlug],
    staleTime: 120_000,
  })

  const projectsById = useMemo(() => {
    const m = new Map<string, ProjectListItem>()
    for (const p of data ?? []) m.set(p.id, p)
    return m
  }, [data])

  return { isError, isFetching, projectsById, refetch }
}
