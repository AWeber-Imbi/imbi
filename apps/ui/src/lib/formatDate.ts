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
 * Format an ISO date string as a relative time (e.g. "2h ago", "3mo ago").
 * Returns '—' for null/undefined values.
 */
export function formatRelativeDate(dateString?: null | string): string {
  if (!dateString) return '—'
  try {
    const r = relTime(dateString)
    return r === 'now' ? 'just now' : `${r} ago`
  } catch {
    return '—'
  }
}

/**
 * Compact relative time for dense UI: "3m", "2h", "5d", "2w", "3mo", "1y".
 * Accepts an ISO string or millisecond timestamp.
 */
// fallow-ignore-next-line complexity
export function relTime(
  iso: number | string,
  now: number = Date.now(),
): string {
  const t = typeof iso === 'number' ? iso : Date.parse(iso)
  if (!Number.isFinite(t)) return 'now'
  const diff = Math.max(0, now - t)
  const m = Math.floor(diff / 60_000)
  if (m < 1) return 'now'
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h`
  const d = Math.floor(h / 24)
  if (d < 7) return `${d}d`
  if (d < 30) return `${Math.floor(d / 7)}w`
  if (d < 365) return `${Math.floor(d / 30)}mo`
  return `${Math.floor(d / 365)}y`
}
