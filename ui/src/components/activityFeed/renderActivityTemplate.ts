import { renderOpsLogTemplate } from '@/components/operations-log/renderOpsLogTemplate'
import type { PluginOpsLogTemplateMap } from '@/hooks/usePluginOpsLogTemplates'
import type { OperationsLogEntry } from '@/types'

interface ParsedPayload {
  action?: string
  payload: Record<string, unknown>
  pluginSlug?: string
}

// JSON descriptions look like {"plugin_slug":"aws-ssm","action":"set",...}.
// Anything else (free-form text, malformed JSON) returns null so the
// caller can fall back to the legacy hand-built sentence.
export function parseActivityDescription(
  description: null | string | undefined,
): null | ParsedPayload {
  const raw = (description ?? '').trim()
  if (!raw.startsWith('{')) return null
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return null
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return null
  }
  const payload = parsed as Record<string, unknown>
  const pluginSlug =
    typeof payload.plugin_slug === 'string' ? payload.plugin_slug : undefined
  if (!pluginSlug) return null
  return {
    action: typeof payload.action === 'string' ? payload.action : undefined,
    payload,
    pluginSlug,
  }
}

// Returns the rendered label string when ``opsEntry`` carries a JSON
// description AND the plugin ships a matching template; otherwise
// returns ``null`` so the row falls back to the legacy sentence.
export function renderActivityTemplate(
  opsEntry: OperationsLogEntry,
  templates: PluginOpsLogTemplateMap,
): null | string {
  const parsed = parseActivityDescription(opsEntry.description)
  if (!parsed?.pluginSlug) return null
  const template = templates.get(parsed.pluginSlug, parsed.action)
  if (!template) return null
  return renderOpsLogTemplate(template.label, {
    display: {
      environment: opsEntry.environment ?? undefined,
      performer: opsEntry.performed_by ?? opsEntry.recorded_by,
      project: opsEntry.project_name ?? undefined,
    },
    entry: {
      description: opsEntry.description,
      environment_slug: opsEntry.environment ?? '',
      project_slug: opsEntry.project_name ?? '',
      version: opsEntry.version ?? null,
    },
    payload: parsed.payload,
  })
}
