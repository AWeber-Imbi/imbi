import { useMemo } from 'react'

import { useQuery } from '@tanstack/react-query'

import { listIntegrations, listPluginPackages } from '@/api/endpoints'
import {
  identityIntegrations,
  pluginIsIdentity,
} from '@/components/plugin-packages'
import { queryKeys } from '@/lib/queryKeys'
import type { Integration, PluginPackage } from '@/types'

// One connectable provider: an identity-enabled integration paired with the
// plugin package backing it. Keyed by integration, not plugin — a plugin can
// have several integrations (one per host) and each connects separately. The
// integration's own `name` is what tells two integrations of one plugin apart,
// so it's the display label on both surfaces.
export interface ConnectableIdentity {
  integration: Integration
  plugin: PluginPackage
}

// Shared data for the personal identity-connection surfaces (dashboard
// tiles + Settings > Connections): the installed plugins and the
// identity-enabled integrations in the selected org — i.e. providers the
// actor can actually connect to. Global login providers are org-less
// (absent here) and unconfigured plugins have no integration, so both are
// excluded.
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

  const connectable = useMemo(() => {
    const pluginsBySlug = new Map<string, PluginPackage>()
    for (const plugin of pluginsQuery.data ?? []) {
      if (plugin.enabled && pluginIsIdentity(plugin)) {
        pluginsBySlug.set(plugin.slug, plugin)
      }
    }
    const out: ConnectableIdentity[] = []
    for (const integration of identityIntegrations(
      integrationsQuery.data ?? [],
    )) {
      const plugin = pluginsBySlug.get(integration.plugin)
      if (plugin) out.push({ integration, plugin })
    }
    return out
  }, [integrationsQuery.data, pluginsQuery.data])

  return { connectable, integrationsQuery, pluginsQuery }
}
