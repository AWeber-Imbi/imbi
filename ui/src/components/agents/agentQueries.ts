import { useQuery } from '@tanstack/react-query'

import { ApiError } from '@/api/client'
import { listAgents, resolvePrompt } from '@/api/endpoints'
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
