import { ApiError } from '@/api/client'

/**
 * Extract a human-readable message from an error produced by ApiClient.
 * Handles ApiError instances, generic Error instances, string errors, and
 * anything else with the provided fallback.
 */
export function extractApiErrorDetail(
  error: unknown,
  fallback = 'Unknown error',
): string {
  if (error instanceof ApiError) {
    const data = error.data as undefined | { detail?: string; message?: string }
    return data?.detail || data?.message || error.message
  }
  if (error instanceof Error) return error.message
  if (typeof error === 'string') return error
  return fallback
}
