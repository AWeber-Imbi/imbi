import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

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
