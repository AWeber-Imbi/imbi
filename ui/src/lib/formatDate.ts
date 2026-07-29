interface DateFormatOptions {
  /** String returned when the input is null/undefined or unparseable. */
  fallback?: string
  /** Month rendering. Defaults to short ("Jan"). */
  month?: 'long' | 'short'
}

/** A bare calendar date with no time component: "2026-07-29". */
const DATE_ONLY_RE = /^\d{4}-\d{2}-\d{2}$/

/** A trailing UTC designator or numeric offset: "Z", "+00:00", "-0500". */
const HAS_OFFSET_RE = /(Z|[+-]\d{2}:?\d{2})$/i

/**
 * Full absolute timestamp for tooltip reveals: "Jan 15, 2025, 3:45 PM".
 * Accepts an ISO string or millisecond timestamp.
 */
export function absTime(iso: number | string): string {
  try {
    const d = parseServerTs(iso)
    if (!Number.isFinite(d.getTime())) return '—'
    return d.toLocaleString(undefined, {
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return '—'
  }
}

/**
 * Format a value by its schema format: `date` renders as a calendar date
 * with no time, `date-time` as a localized date + time. Keeps date-only
 * fields from being shifted a day by timezone conversion.
 */
export function formatByFormat(
  value?: null | string,
  format?: null | string,
): string {
  return format === 'date' ? formatDate(value) : formatDateTime(value)
}

/**
 * Format an ISO date string as a localized short date.
 * Returns the configured fallback (default '—') for null/undefined/invalid.
 */
export function formatDate(
  dateString?: null | string,
  { fallback = '—', month = 'short' }: DateFormatOptions = {},
): string {
  if (!dateString) return fallback
  try {
    const d = parseServerTs(dateString)
    if (!Number.isFinite(d.getTime())) return fallback
    return d.toLocaleDateString(undefined, {
      day: 'numeric',
      month,
      year: 'numeric',
    })
  } catch {
    return fallback
  }
}

/**
 * Format an ISO date string as a localized date + time.
 * Returns the configured fallback (default '—') for null/undefined/invalid.
 * Use for "last login", "created at" rows where a wall-clock time matters.
 */
export function formatDateTime(
  dateString?: null | string,
  { fallback = '—', month = 'short' }: DateFormatOptions = {},
): string {
  if (!dateString) return fallback
  try {
    const d = parseServerTs(dateString)
    if (!Number.isFinite(d.getTime())) return fallback
    return d.toLocaleString(undefined, {
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      month,
      year: 'numeric',
    })
  } catch {
    return fallback
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
 * Parse a timestamp as the API means it, not as `new Date()` guesses.
 *
 * ClickHouse DateTime64 columns hold UTC but some endpoints serialize
 * them without an offset — "2026-07-29T12:00:00", or the space-separated
 * "2026-07-29 12:00:00" that Python's `str(datetime)` emits. `new Date()`
 * reads a bare timestamp as *local*, shifting it by the viewer's UTC
 * offset, so a missing offset is treated as UTC here.
 *
 * Date-only values are the opposite case: they name a calendar day, not
 * an instant, so they parse to local midnight. Reading "2026-07-29" as
 * UTC midnight would render it as the 28th anywhere west of Greenwich.
 */
export function parseServerTs(value: number | string): Date {
  if (typeof value === 'number') return new Date(value)
  const raw = value.trim()
  // A date-time form with no offset is spec-mandated to parse as local,
  // which is exactly what a calendar day should mean.
  if (DATE_ONLY_RE.test(raw)) return new Date(`${raw}T00:00:00`)
  const iso = raw.replace(' ', 'T')
  return new Date(HAS_OFFSET_RE.test(iso) ? iso : `${iso}Z`)
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
  const t = parseServerTs(iso).getTime()
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

/**
 * Render a `Date` as a "YYYY-MM-DD" calendar date using its *local*
 * fields. Use for date-only API values; `toISOString().slice(0, 10)`
 * would shift the day for any non-UTC viewer.
 */
export function toDateOnlyIso(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}
