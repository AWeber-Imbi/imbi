import { ApiError } from '@/api/client'

/**
 * Run a fetcher and map an HTTP 404 to ``null`` instead of throwing.
 *
 * Used by queries where a missing resource is a normal empty state (e.g.
 * a project that has no analysis report yet) rather than a query error.
 * Any non-404 error is rethrown so React Query still surfaces it.
 */
export async function treatNotFoundAsNull<T>(
  fn: () => Promise<T>,
): Promise<null | T> {
  try {
    return await fn()
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      return null
    }
    throw err
  }
}
