/**
 * Format an ISO date string as a localized short date.
 * Returns '—' for null/undefined values.
 */
export function formatDate(dateString?: null | string): string {
  if (!dateString) return '—'
  try {
    return new Date(dateString).toLocaleDateString(undefined, {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return '—'
  }
}

/**
 * Format an ISO date string as a relative time (e.g. "2 hours ago").
 * Returns '—' for null/undefined values.
 */
export function formatRelativeDate(dateString?: null | string): string {
  if (!dateString) return '—'
  try {
    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) return 'just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    if (diffDays < 30) return `${diffDays}d ago`
    return formatDate(dateString)
  } catch {
    return '—'
  }
}
