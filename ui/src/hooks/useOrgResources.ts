import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { listEnvironments, listProjectTypes, listTeams } from '@/api/endpoints'
import { queryKeys } from '@/lib/queryKeys'
import type { Environment, ProjectType, Team } from '@/types'

// Org-scoped reference data changes slowly (admin edits). Pick one
// staleTime so 8+ consumers don't refetch independently when one of
// them visits its page. 10 minutes mirrors the existing
// ProjectActivityLog environments query that was already using this
// window.
const ORG_RESOURCE_STALE_TIME = 10 * 60 * 1000

interface ResourceHookOptions {
  /** Extra gate ANDed with `!!orgSlug`. Use for dialog-open or tab gating. */
  enabled?: boolean
}

/** Canonical hook for the org-scoped Environments list. See useTeams. */
export function useEnvironments(
  orgSlug: string,
  { enabled = true }: ResourceHookOptions = {},
): UseQueryResult<Environment[], Error> {
  return useQuery({
    enabled: !!orgSlug && enabled,
    queryFn: ({ signal }) => listEnvironments(orgSlug, signal),
    queryKey: queryKeys.environments(orgSlug),
    staleTime: ORG_RESOURCE_STALE_TIME,
  })
}

/** Canonical hook for the org-scoped Project Types list. See useTeams. */
export function useProjectTypes(
  orgSlug: string,
  { enabled = true }: ResourceHookOptions = {},
): UseQueryResult<ProjectType[], Error> {
  return useQuery({
    enabled: !!orgSlug && enabled,
    queryFn: ({ signal }) => listProjectTypes(orgSlug, signal),
    queryKey: queryKeys.projectTypes(orgSlug),
    staleTime: ORG_RESOURCE_STALE_TIME,
  })
}

/**
 * Canonical hook for the org-scoped Teams list. Wraps useQuery with the
 * shared key, fetcher, and staleTime so every site reads from the same
 * cache.
 */
export function useTeams(
  orgSlug: string,
  { enabled = true }: ResourceHookOptions = {},
): UseQueryResult<Team[], Error> {
  return useQuery({
    enabled: !!orgSlug && enabled,
    queryFn: ({ signal }) => listTeams(orgSlug, signal),
    queryKey: queryKeys.teams(orgSlug),
    staleTime: ORG_RESOURCE_STALE_TIME,
  })
}
