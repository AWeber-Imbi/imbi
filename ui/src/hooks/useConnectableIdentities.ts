import { useQuery } from '@tanstack/react-query'

import { listIntegrations, listPluginPackages } from '@/api/endpoints'
import { identityIntegrationPluginSlugs } from '@/components/plugin-packages'
import { queryKeys } from '@/lib/queryKeys'
import type { PluginPackage } from '@/types'

// Shared data for the personal identity-connection surfaces (dashboard
// tiles + Settings > Connections): the installed plugins and the set of
// plugin slugs that have a configured, identity-enabled integration in the
// selected org — i.e. providers the actor can actually connect to. Global
// login providers are org-less (absent here) and unconfigured plugins have
// no integration, so both are excluded.
export function useConnectableIdentities(orgSlug: string) {
  const pluginsQuery = useQuery<PluginPackage[]>({
    queryFn: ({ signal }) => listPluginPackages(signal),
    queryKey: queryKeys.pluginPackages(),
    staleTime: 60 * 1000,
  })
  const integrationsQuery = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listIntegrations(orgSlug, signal),
    queryKey: orgSlug ? queryKeys.integrations(orgSlug) : ['integrations'],
    staleTime: 60 * 1000,
  })
  const connectableSlugs = identityIntegrationPluginSlugs(
    integrationsQuery.data ?? [],
  )
  return { connectableSlugs, integrationsQuery, pluginsQuery }
}
