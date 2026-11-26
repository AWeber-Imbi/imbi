import { useQuery } from '@tanstack/react-query'

import { listAgents } from '@/api/endpoints'
import { useOptionalOrganization } from '@/contexts/OrganizationContext'
import { queryKeys } from '@/lib/queryKeys'
import type { Agent } from '@/types'

const EMPTY = new Map<string, Agent>()
// One map per agents list, shared by every observer of the query.
const maps = new WeakMap<Agent[], Map<string, Agent>>()

/**
 * The agents of the selected organization, by the slug of the service
 * account each one acts as. A change an agent makes records that slug as
 * its principal. Shares the agents list cache. A user without
 * `agent:read` gets one 403 and an empty map.
 */
export function useServiceAccountAgents(enabled = true): Map<string, Agent> {
  const orgSlug = useOptionalOrganization()?.selectedOrganization?.slug
  const { data } = useQuery({
    enabled: enabled && !!orgSlug,
    queryFn: ({ signal }) => listAgents(orgSlug!, signal),
    queryKey: queryKeys.agents(orgSlug ?? ''),
    retry: false,
    retryOnMount: false,
    select: byServiceAccount,
    staleTime: 5 * 60_000,
  })
  return data ?? EMPTY
}

function byServiceAccount(agents: Agent[]): Map<string, Agent> {
  let map = maps.get(agents)
  if (!map) {
    map = new Map(
      agents.flatMap((a) =>
        a.service_account_slug ? [[a.service_account_slug, a] as const] : [],
      ),
    )
    maps.set(agents, map)
  }
  return map
}
