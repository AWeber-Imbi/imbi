import { ApiError } from '@/api/client'

/**
 * Extract a human-readable message from an error produced by ApiClient.
 * Handles ApiError instances, generic Error instances, string errors, and
 * anything else with the provided fallback.
 *
 * FastAPI's HTTPException can carry a non-string ``detail`` (e.g. the
 * ``identity_required`` 401 returns ``{error, plugin_id, start_url}``).
 * Callers expect a string here, so we coerce shaped objects rather than
 * returning them unchanged — otherwise React renders crash with
 * "Objects are not valid as a React child".
 */
export function extractApiErrorDetail(
  error: unknown,
  fallback = 'Unknown error',
): string {
  if (error instanceof ApiError) {
    const data = error.data as
      | undefined
      | {
          detail?: string | { [k: string]: unknown; error?: string }
          message?: string
        }
    const detail = data?.detail
    if (typeof detail === 'string' && detail) return detail
    if (detail && typeof detail === 'object') {
      if (typeof detail.error === 'string' && detail.error) return detail.error
      try {
        return JSON.stringify(detail)
      } catch {
        return error.message
      }
    }
    return data?.message || error.message
  }
  if (error instanceof Error) return error.message
  if (typeof error === 'string') return error
  return fallback
}
