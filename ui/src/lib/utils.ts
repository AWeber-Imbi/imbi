import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

import type { BlueprintFilter, Environment } from '@/types'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Extract dynamic (blueprint) fields from a node object by filtering
 * out known base fields.
 */
export function extractDynamicFields(
  obj: Record<string, unknown>,
  baseFields: Set<string>,
): Record<string, unknown> {
  const result: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(obj)) {
    if (!baseFields.has(key)) {
      result[key] = value
    }
  }
  return result
}

/**
 * Move the localStorage keys that ADR 0028 renamed. Call once at startup,
 * before a page reads them. A browser that last ran a UI older than ADR
 * 0028 still has the old keys.
 */
export function migrateLegacyStorage(): void {
  migrateStorageKey(
    'imbi:agent-task:conversation-mode',
    'imbi:ticket:conversation-mode',
  )
  // The react-resizable-panels key: the group id, then the panel ids.
  migrateStorageKey(
    'react-resizable-panels:imbi:agent-tasks:split:list:detail',
    'react-resizable-panels:imbi:tickets:split:list:detail',
  )
}

/**
 * Move a localStorage value from an old key to a new key, once. A value
 * already at the new key wins. Storage can be blocked; then nothing moves.
 */
export function migrateStorageKey(from: string, to: string): void {
  try {
    const old = window.localStorage.getItem(from)
    if (old === null) return
    if (window.localStorage.getItem(to) === null)
      window.localStorage.setItem(to, old)
    window.localStorage.removeItem(from)
  } catch {
    // Blocked or full storage: the reader starts from the default.
  }
}

/** The fields of a blueprint filter, in the order that they show. */
export const BLUEPRINT_FILTER_KEYS = [
  'project_type',
  'environment',
  'ticket_type',
  'priority',
  'label',
] as const satisfies readonly (keyof BlueprintFilter)[]

/**
 * Parse a blueprint's filter field (string or object) into a typed
 * BlueprintFilter, returning null on missing/invalid input.
 */
export function parseFilterFromBlueprint(
  filter: BlueprintFilter | null | string | undefined,
): BlueprintFilter | null {
  if (!filter) return null
  try {
    const parsed: BlueprintFilter =
      typeof filter === 'string' ? JSON.parse(filter) : filter
    if (BLUEPRINT_FILTER_KEYS.some((k) => (parsed[k]?.length ?? 0) > 0)) {
      return parsed
    }
  } catch {
    // ignore parse errors
  }
  return null
}

/** Parse JSON that must hold a plain object, e.g. a provider config. */
export function parseObject(
  label: string,
  value: string,
): Record<string, unknown> {
  let parsed: unknown
  try {
    parsed = JSON.parse(value)
  } catch {
    throw new Error(`${label} is not valid JSON`)
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(`${label} must be a JSON object`)
  }
  return parsed as Record<string, unknown>
}

/**
 * Parse an arbitrary value as an http(s) URL. Returns the canonical URL
 * string if valid, else null. Guards against javascript:/data:/etc schemes
 * in user-supplied link values.
 */
export function sanitizeHttpUrl(raw: unknown): null | string {
  // Reuse sanitizeUri for input validation, parsing, canonicalization, and
  // unsafe-scheme filtering, then narrow to the HTTP-only contract so the two
  // helpers cannot drift.
  const sanitized = sanitizeUri(raw)
  if (sanitized === null) return null
  const { protocol } = new URL(sanitized)
  return protocol === 'http:' || protocol === 'https:' ? sanitized : null
}

// Schemes that are unsafe to expose as a clickable link ``href``.
const UNSAFE_URI_SCHEMES = new Set(['data:', 'javascript:', 'vbscript:'])

/**
 * Parse an arbitrary value as a URL of any scheme (http, postgresql, ssh,
 * mailto, …). Returns the canonical URL string if valid, else null. Blocks
 * the XSS-dangerous javascript:/data:/vbscript: schemes.
 */
export function sanitizeUri(raw: unknown): null | string {
  if (typeof raw !== 'string' || raw === '') return null
  try {
    const parsed = new URL(raw)
    if (!UNSAFE_URI_SCHEMES.has(parsed.protocol)) {
      return parsed.toString()
    }
  } catch {
    // not a valid URL
  }
  return null
}

/**
 * Generate a URL-safe slug from a display name.
 */
export function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9\s-_]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-+|-+$/g, '')
}

/**
 * Return a new array of environments sorted by sort_order (ascending,
 * nullish treated as 0) and falling back to name.localeCompare for ties.
 */
export function sortEnvironments(environments: Environment[]): Environment[] {
  if (!Array.isArray(environments)) return []
  return [...environments].sort((a, b) => {
    const orderDiff = (a.sort_order ?? 0) - (b.sort_order ?? 0)
    return orderDiff !== 0 ? orderDiff : a.name.localeCompare(b.name)
  })
}
