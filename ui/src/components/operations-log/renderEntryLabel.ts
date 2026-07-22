import type { PluginOpsLogTemplateMap } from '@/hooks/usePluginOpsLogTemplates'
import type { Environment, OperationsLogRecord, Project } from '@/types'

import { cleanDescription } from './opsLogHelpers'
import { parseDescription } from './parseDescription'
import { renderOpsLogLabel } from './renderOpsLogTemplate'

export interface RenderEntryLabelContext {
  environment?: Environment
  performerDisplayName?: string
  project?: Project
  templates: PluginOpsLogTemplateMap
}

// fallow-ignore-next-line complexity
export function renderEntryLabel(
  entry: OperationsLogRecord,
  ctx: RenderEntryLabelContext,
): string {
  const parsed = parseDescription(entry)
  if (parsed.kind !== 'plugin') {
    return cleanDescription(entry.description, entry.version)
  }
  const template = ctx.templates.get(entry.plugin_slug ?? '', parsed.action)
  if (!template) {
    return (
      parsed.summary ??
      `${entry.plugin_slug ?? ''}${parsed.action ? ` · ${parsed.action}` : ''}`
    )
  }
  const performer = entry.performed_by ?? entry.recorded_by
  return renderOpsLogLabel(template, {
    display: {
      environment: ctx.environment?.name ?? entry.environment_slug,
      performer: ctx.performerDisplayName ?? performer,
      project: ctx.project?.name ?? entry.project_slug,
    },
    entry,
    payload: parsed.payload,
  })
}
