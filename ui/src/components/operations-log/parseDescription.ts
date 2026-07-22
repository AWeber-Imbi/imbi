import type { OperationsLogRecord } from '@/types'

export type ParsedDescription =
  | {
      action?: string
      kind: 'plugin'
      payload: Record<string, unknown>
      raw: string
      summary?: string
    }
  | { kind: 'text'; text: string }

// When the API returns a non-empty `plugin_slug` on an ops-log entry, the
// `description` column carries a JSON-encoded payload owned by that plugin.
// Older / human-written entries leave `plugin_slug` empty and use the field
// as free text — keep treating those as text without trying to parse.
export function parseDescription(
  entry: OperationsLogRecord,
): ParsedDescription {
  const raw = entry.description ?? ''
  if (!entry.plugin_slug) return { kind: 'text', text: raw }
  const payload = tryParseObject(raw)
  if (!payload) return { kind: 'text', text: raw }
  const action = typeof payload.action === 'string' ? payload.action : undefined
  const summary =
    typeof payload.summary === 'string' ? payload.summary : undefined
  return { action, kind: 'plugin', payload, raw, summary }
}

function tryParseObject(raw: string): null | Record<string, unknown> {
  const trimmed = raw.trim()
  if (!trimmed.startsWith('{')) return null
  try {
    const parsed: unknown = JSON.parse(trimmed)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>
    }
  } catch {
    // fall through
  }
  return null
}
