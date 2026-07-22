// Plugin-specific renderers used to live here as hand-written React
// components keyed by ``plugin_slug``. They have been replaced by
// plugin-supplied templates fetched from the API (see
// ``usePluginOpsLogTemplates`` + ``renderOpsLogTemplate``); the generic
// key/value payload view stays here as the details-panel fallback for
// entries the plugin has not customized.
export { GenericPluginPayload } from './generic'
export type { PluginOpsLogContext } from './types'
