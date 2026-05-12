import { awsSsmRenderer } from './aws-ssm'
import type { PluginOpsLogRenderer } from './types'

// Maps `plugin_slug` from the ops log entry to its renderer. Unregistered
// slugs fall back to the generic key/value payload renderer; the entry still
// renders, just without plugin-specific polish.
const RENDERERS: Record<string, PluginOpsLogRenderer> = {
  'aws-ssm': awsSsmRenderer,
}

export function getPluginRenderer(
  pluginSlug: string | undefined,
): PluginOpsLogRenderer | undefined {
  if (!pluginSlug) return undefined
  return RENDERERS[pluginSlug]
}

export { GenericPluginPayload } from './generic'
export type { PluginOpsLogContext, PluginOpsLogRenderer } from './types'
