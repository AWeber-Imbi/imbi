import { useQuery } from '@tanstack/react-query'

import {
  listPluginOpsLogTemplates,
  type OpsLogTemplate,
  type PluginOpsLogTemplates,
} from '@/api/endpoints'

export interface PluginOpsLogTemplateMap {
  get(
    pluginSlug: string,
    action: string | undefined,
  ): OpsLogTemplate | undefined
}

const EMPTY_MAP: PluginOpsLogTemplateMap = {
  get: () => undefined,
}

export function usePluginOpsLogTemplates(): {
  isLoading: boolean
  templates: PluginOpsLogTemplateMap
} {
  const { data, isLoading } = useQuery({
    gcTime: 60 * 60 * 1000,
    queryFn: ({ signal }) => listPluginOpsLogTemplates(signal),
    queryKey: ['pluginOpsLogTemplates'],
    // Templates are part of plugin manifest -- effectively static for
    // the session. Cache aggressively.
    staleTime: 5 * 60 * 1000,
  })
  return {
    isLoading,
    templates: data ? buildMap(data) : EMPTY_MAP,
  }
}

function buildMap(plugins: PluginOpsLogTemplates[]): PluginOpsLogTemplateMap {
  const bySlug = new Map<string, Record<string, OpsLogTemplate>>()
  for (const plugin of plugins) {
    // ``slug`` is typed as ``string`` in the API contract but the
    // backend currently allows empty strings (the field originates
    // from the plugin manifest, not a database key). Skip empty
    // slugs explicitly: callers cannot look them up via ``get``
    // anyway because that path is also guarded.
    if (!plugin.slug) continue
    bySlug.set(plugin.slug, plugin.templates ?? {})
  }
  return {
    // ``action`` is the discriminator the API encodes into the
    // description payload. Empty-string key acts as a manifest-side
    // fallback when no action is present.
    get(pluginSlug, action) {
      const templates = pluginSlug ? bySlug.get(pluginSlug) : undefined
      return templates?.[action ?? ''] ?? templates?.['']
    },
  }
}
