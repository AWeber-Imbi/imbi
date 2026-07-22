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
    if (
      (parsed.project_type?.length ?? 0) > 0 ||
      (parsed.environment?.length ?? 0) > 0
    ) {
      return parsed
    }
  } catch {
    // ignore parse errors
  }
  return null
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
