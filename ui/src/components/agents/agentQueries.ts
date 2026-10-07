import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '@/api/client'
import {
  getAgentToolCatalog,
  listAgents,
  listEnvironments,
  resolvePrompt,
} from '@/api/endpoints'
import { useHasPermission } from '@/hooks/useHasPermission'
import { queryKeys } from '@/lib/queryKeys'
import type { PromptVersion } from '@/types'

/** The agents of an org. Disabled when the user may not read agents. */
export function useAgentList(orgSlug: string | undefined) {
  const canRead = useHasPermission('agent:read')
  return useQuery({
    enabled: !!orgSlug && canRead,
    queryFn: ({ signal }) => listAgents(orgSlug!, signal),
    queryKey: queryKeys.agents(orgSlug ?? ''),
  })
}

/**
 * The tools that an agent can use. The server keeps the catalog for five
 * minutes; `refresh` lists it again and replaces the cached data.
 */
export function useAgentToolCatalog(orgSlug: string) {
  const queryClient = useQueryClient()
  const queryKey = queryKeys.agentToolCatalog(orgSlug)
  const query = useQuery({
    queryFn: ({ signal }) => getAgentToolCatalog(orgSlug, false, signal),
    queryKey,
    staleTime: 60_000,
  })
  const refresh = useMutation({
    mutationFn: () => getAgentToolCatalog(orgSlug, true),
    onSuccess: (catalog) => queryClient.setQueryData(queryKey, catalog),
  })
  return { query, refresh }
}

/** The environments of an org, in their sort order. */
export function useOrgEnvironments(orgSlug: string) {
  return useQuery({
    queryFn: ({ signal }) => listEnvironments(orgSlug, signal),
    queryKey: queryKeys.environments(orgSlug),
    select: (environments) =>
      [...environments].sort(
        (a, b) =>
          (a.sort_order ?? 0) - (b.sort_order ?? 0) ||
          a.name.localeCompare(b.name),
      ),
  })
}

/**
 * The prompt version that `ref` resolves to. The data is null when the
 * prompt or its label does not exist (a 404); other errors stay errors.
 */
export function usePromptResolution(ref: null | string | undefined) {
  return useQuery<null | PromptVersion>({
    enabled: !!ref,
    queryFn: async ({ signal }) => {
      try {
        const resolution = await resolvePrompt(ref!, signal)
        return resolution.version
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null
        throw error
      }
    },
    queryKey: queryKeys.promptResolution(ref ?? ''),
  })
}
