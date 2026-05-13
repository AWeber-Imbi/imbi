import type { OpsLogTemplate } from '@/api/endpoints'
import type { OperationsLogRecord } from '@/types'

// Placeholder names are limited to a single word: no dots, no path
// traversal. Plugins that need to expose nested data must flatten it
// into the payload before sending. The regex deliberately matches the
// resolver: see ``resolve`` below.
const PLACEHOLDER_RE = /\{\{\s*(\w+)\s*\}\}/g

export interface OpsLogTemplateContext {
  // Display-resolved values the row already computes locally (so the
  // template can refer to ``environment`` and get a human label rather
  // than the slug). All optional -- missing keys fall through to the
  // payload, then to the entry, then to an empty string.
  display?: {
    environment?: string
    performer?: string
    project?: string
  }
  entry: OperationsLogRecord | OpsLogTemplateEntry
  payload: Record<string, unknown>
}

// Only fields the renderer actually reads off ``entry`` -- callers
// don't need to materialize a full ``OperationsLogRecord`` just to
// substitute these placeholders.
export interface OpsLogTemplateEntry {
  description?: string
  environment_slug?: string
  project_slug?: string
  version?: null | string
}

export function renderOpsLogLabel(
  template: OpsLogTemplate,
  ctx: OpsLogTemplateContext,
): string {
  return renderOpsLogTemplate(template.label, ctx)
}

// Mustache-style substitution. Resolution order for ``{{name}}``:
//
//   1. payload[name]          (e.g. "from_environment", "key")
//   2. display[name]          (resolved environment/project/performer)
//   3. entry[name]            (e.g. "version", "environment_slug")
//   4. ""                      (missing values render as the empty string,
//                               leaving sentence structure intact)
//
// We deliberately keep the renderer dumb: no conditionals, no loops, no
// HTML output. Plugins that want richer formatting fall back to the
// generic key/value panel for the details view.
export function renderOpsLogTemplate(
  template: string,
  ctx: OpsLogTemplateContext,
): string {
  return template.replace(PLACEHOLDER_RE, (_, name: string) => {
    const value = resolve(name, ctx)
    return value === undefined || value === null ? '' : String(value)
  })
}

function resolve(name: string, ctx: OpsLogTemplateContext): unknown {
  if (name in ctx.payload) return ctx.payload[name]
  const display = ctx.display ?? {}
  if (name in display) return display[name as keyof typeof display]
  const entry = ctx.entry as unknown as Record<string, unknown>
  return entry[name] ?? ''
}
