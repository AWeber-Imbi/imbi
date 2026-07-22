import { ApiError } from '@/api/client'
import type { GraphQueryError, GraphQueryErrorEnvelope } from '@/types'

/**
 * Translate an error thrown by the graph-query endpoint into the structured
 * {@link GraphQueryError} the workbench renders (message + optional SQLSTATE
 * code, line/column, and hint).
 *
 * The backend returns the actual PostgreSQL / Apache AGE error wrapped in
 * FastAPI's ``{ detail: { error: { ... } } }`` envelope. Earlier we only
 * looked for ``error`` at the top level, so every failure collapsed to a bare
 * ``HTTP 400``. Here we unwrap the ``detail`` layer first, then fall back to a
 * plain string detail (e.g. the 403 "Admin privileges required") and finally
 * the HTTP status line.
 */
export function extractGraphQueryError(err: unknown): GraphQueryError {
  if (err instanceof ApiError) {
    const detail = (err.data as undefined | { detail?: unknown })?.detail
    const envelope =
      unwrapErrorEnvelope(detail) ?? unwrapErrorEnvelope(err.data)
    if (envelope) {
      return envelope
    }
    if (typeof detail === 'string' && detail) {
      return { message: detail }
    }
    return { message: err.message || `HTTP ${err.status}` }
  }
  if (err instanceof Error) {
    return { message: err.message }
  }
  return { message: 'Unknown error' }
}

function unwrapErrorEnvelope(value: unknown): GraphQueryError | undefined {
  if (value && typeof value === 'object' && 'error' in value) {
    const { error } = value as GraphQueryErrorEnvelope
    if (
      error &&
      typeof error === 'object' &&
      typeof error.message === 'string'
    ) {
      return error
    }
  }
  return undefined
}
