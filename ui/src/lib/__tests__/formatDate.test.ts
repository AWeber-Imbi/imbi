import { describe, expect, it } from 'vitest'

import {
  absTime,
  formatByFormat,
  formatDate,
  formatDateTime,
  formatRelativeDate,
  parseServerTs,
  relTime,
  toDateOnlyIso,
} from '@/lib/formatDate'

// Fixed reference instant so relative-time math stays deterministic
// across CI clocks. Picked as a Wednesday afternoon so day-of-week
// rollovers (if anything starts depending on them) don't surprise us.
const NOW = Date.parse('2026-05-20T12:00:00Z')
const sec = 1_000
const min = 60 * sec
const hour = 60 * min
const day = 24 * hour

describe('formatDate', () => {
  it('formats a localized short date', () => {
    // Use a Z-suffixed instant and only assert structural pieces so
    // the test passes in any timezone CI runs under (toLocaleDateString
    // formats in the local zone).
    const out = formatDate('2026-03-17T12:00:00Z')
    expect(out).toMatch(/2026/)
    expect(out).toMatch(/Mar/)
    expect(out).not.toBe('—')
  })

  it('returns em-dash for null', () => {
    expect(formatDate(null)).toBe('—')
  })

  it('returns em-dash for undefined', () => {
    expect(formatDate(undefined)).toBe('—')
  })

  it('returns em-dash for empty string', () => {
    expect(formatDate('')).toBe('—')
  })
})

describe('relTime', () => {
  // --- m / h / d / w / mo / y unit transitions -----------------------

  it('returns "now" for under one minute', () => {
    expect(relTime(NOW - 30 * sec, NOW)).toBe('now')
  })

  it('returns minutes for 1m to 59m', () => {
    expect(relTime(NOW - 1 * min, NOW)).toBe('1m')
    expect(relTime(NOW - 59 * min, NOW)).toBe('59m')
  })

  it('returns hours for 1h to 23h', () => {
    expect(relTime(NOW - 60 * min, NOW)).toBe('1h')
    expect(relTime(NOW - 23 * hour, NOW)).toBe('23h')
  })

  it('returns days for 1d to 6d', () => {
    expect(relTime(NOW - 1 * day, NOW)).toBe('1d')
    expect(relTime(NOW - 6 * day, NOW)).toBe('6d')
  })

  it('returns weeks for 7d to 29d', () => {
    // This is the bug-regression slot. ``ProjectsView``'s broken
    // local copy previously fell through to "0mo ago" anywhere from
    // 14-15 days. Lock down every week of the range:
    expect(relTime(NOW - 7 * day, NOW)).toBe('1w')
    expect(relTime(NOW - 13 * day, NOW)).toBe('1w')
    expect(relTime(NOW - 14 * day, NOW)).toBe('2w')
    expect(relTime(NOW - 15 * day, NOW)).toBe('2w')
    expect(relTime(NOW - 20 * day, NOW)).toBe('2w')
    expect(relTime(NOW - 21 * day, NOW)).toBe('3w')
    expect(relTime(NOW - 29 * day, NOW)).toBe('4w')
  })

  it('returns months for 30d to 364d', () => {
    expect(relTime(NOW - 30 * day, NOW)).toBe('1mo')
    expect(relTime(NOW - 59 * day, NOW)).toBe('1mo')
    expect(relTime(NOW - 60 * day, NOW)).toBe('2mo')
    expect(relTime(NOW - 364 * day, NOW)).toBe('12mo')
  })

  it('returns years for 365d and beyond', () => {
    expect(relTime(NOW - 365 * day, NOW)).toBe('1y')
    expect(relTime(NOW - 700 * day, NOW)).toBe('1y')
    expect(relTime(NOW - 730 * day, NOW)).toBe('2y')
  })

  it('never returns "0mo"', () => {
    // Sweep every day from 14 to 29 — these used to round to "0mo"
    // in the buggy local copy. Now they must all render as a week
    // count, not months.
    for (let d = 14; d < 30; d++) {
      const out = relTime(NOW - d * day, NOW)
      expect(out).not.toBe('0mo')
      expect(out).toMatch(/^\dw$/)
    }
  })

  // --- input shapes -------------------------------------------------

  it('accepts a millisecond timestamp', () => {
    expect(relTime(NOW - 2 * hour, NOW)).toBe('2h')
  })

  it('accepts an ISO string', () => {
    const iso = new Date(NOW - 2 * hour).toISOString()
    expect(relTime(iso, NOW)).toBe('2h')
  })

  // --- defensive edge cases ----------------------------------------

  it('clamps future timestamps to "now"', () => {
    // Clock skew on either end shouldn't render as "-3m"; the
    // function clamps negative diffs to 0.
    expect(relTime(NOW + 5 * min, NOW)).toBe('now')
  })

  it('returns "now" for an unparseable input', () => {
    expect(relTime('not-a-date', NOW)).toBe('now')
  })

  it('defaults ``now`` to wall-clock when omitted', () => {
    // Just smoke-test the no-arg path; the value isn't asserted
    // exactly because Date.now() ticks during execution.
    const out = relTime(Date.now() - 10 * min)
    expect(out).toMatch(/^(now|\d+m)$/)
  })
})

describe('formatRelativeDate', () => {
  it('appends " ago" to a non-now relTime result', () => {
    const iso = new Date(NOW - 2 * day).toISOString()
    // formatRelativeDate calls Date.now() internally — we can't
    // pin the "now" anchor, so assert on the shape + suffix only.
    expect(formatRelativeDate(iso)).toMatch(/^\d+(mo|m|h|d|w|y) ago$/)
  })

  it('uses "just now" instead of "now ago"', () => {
    const iso = new Date(Date.now()).toISOString()
    expect(formatRelativeDate(iso)).toBe('just now')
  })

  it('returns em-dash for null', () => {
    expect(formatRelativeDate(null)).toBe('—')
  })

  it('returns em-dash for undefined', () => {
    expect(formatRelativeDate(undefined)).toBe('—')
  })

  it('returns em-dash for empty string', () => {
    expect(formatRelativeDate('')).toBe('—')
  })
})

describe('absTime', () => {
  it('formats an ISO string as a localized date and time', () => {
    const out = absTime('2026-03-17T15:30:00Z')
    expect(out).toMatch(/2026/)
    expect(out).toMatch(/Mar/)
    expect(out).not.toBe('—')
  })

  it('accepts a millisecond timestamp', () => {
    const out = absTime(Date.parse('2026-03-17T15:30:00Z'))
    expect(out).toMatch(/2026/)
    expect(out).toMatch(/Mar/)
  })

  it('returns em-dash for an unparseable input', () => {
    expect(absTime('not-a-date')).toBe('—')
  })
})

// The API is not consistent about offsets: ClickHouse-backed endpoints have
// serialized naive UTC timestamps, and `str(datetime)` adds a space
// separator. These assert on epoch milliseconds rather than rendered text so
// they hold in whatever zone CI runs under.
describe('parseServerTs', () => {
  const EXPECTED = Date.UTC(2026, 6, 29, 12, 0, 0)

  it('reads a naive timestamp as UTC, not local', () => {
    expect(parseServerTs('2026-07-29T12:00:00').getTime()).toBe(EXPECTED)
  })

  it('reads the space-separated form Python str() emits', () => {
    expect(parseServerTs('2026-07-29 12:00:00').getTime()).toBe(EXPECTED)
  })

  it('reads naive fractional seconds as UTC', () => {
    expect(parseServerTs('2026-07-29T12:00:00.500').getTime()).toBe(
      EXPECTED + 500,
    )
  })

  it('reads six-digit fractional seconds as UTC', () => {
    expect(parseServerTs('2026-07-29 12:00:00.500000').getTime()).toBe(
      EXPECTED + 500,
    )
  })

  it('honours an explicit Z', () => {
    expect(parseServerTs('2026-07-29T12:00:00Z').getTime()).toBe(EXPECTED)
  })

  it('honours an explicit +00:00 offset', () => {
    expect(parseServerTs('2026-07-29T12:00:00+00:00').getTime()).toBe(EXPECTED)
  })

  it('honours a non-UTC offset', () => {
    expect(parseServerTs('2026-07-29T08:00:00-04:00').getTime()).toBe(EXPECTED)
  })

  it('honours a colon-less offset', () => {
    expect(parseServerTs('2026-07-29T08:00:00-0400').getTime()).toBe(EXPECTED)
  })

  it('passes a millisecond timestamp straight through', () => {
    expect(parseServerTs(EXPECTED).getTime()).toBe(EXPECTED)
  })

  // A date-only value names a calendar day, so it must anchor to local
  // midnight — parsing it as UTC midnight renders the previous day for any
  // viewer west of Greenwich.
  it('anchors a date-only value at local midnight', () => {
    const d = parseServerTs('2026-07-29')
    expect(d.getFullYear()).toBe(2026)
    expect(d.getMonth()).toBe(6)
    expect(d.getDate()).toBe(29)
    expect(d.getHours()).toBe(0)
  })

  it('yields an invalid date for unparseable input', () => {
    expect(Number.isNaN(parseServerTs('not-a-date').getTime())).toBe(true)
  })
})

describe('toDateOnlyIso', () => {
  it('uses local calendar fields, not UTC ones', () => {
    expect(toDateOnlyIso(new Date(2026, 6, 29, 23, 30))).toBe('2026-07-29')
  })

  it('zero-pads month and day', () => {
    expect(toDateOnlyIso(new Date(2026, 0, 5))).toBe('2026-01-05')
  })

  // The round trip is what the InlineDate editor does: display a stored
  // date-only value, then write back whatever day the picker returns.
  it('round-trips a date-only value unchanged', () => {
    expect(toDateOnlyIso(parseServerTs('2026-07-29'))).toBe('2026-07-29')
  })
})

describe('formatDate with a date-only value', () => {
  it('renders the day it names rather than shifting a day', () => {
    expect(formatDate('2026-07-29')).toBe(
      new Date(2026, 6, 29).toLocaleDateString(undefined, {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
      }),
    )
  })

  it('returns the fallback for unparseable input', () => {
    expect(formatDate('not-a-date')).toBe('—')
  })
})

describe('formatDateTime', () => {
  it('treats a naive timestamp as UTC', () => {
    expect(formatDateTime('2026-07-29T12:00:00')).toBe(
      formatDateTime('2026-07-29T12:00:00Z'),
    )
  })

  it('returns the fallback for unparseable input', () => {
    expect(formatDateTime('not-a-date')).toBe('—')
  })
})

describe('formatByFormat', () => {
  it('renders a date-only field with no clock time', () => {
    expect(formatByFormat('2026-07-29', 'date')).toBe(formatDate('2026-07-29'))
  })

  it('renders a date-time field with a clock time', () => {
    expect(formatByFormat('2026-07-29T12:00:00Z', 'date-time')).toBe(
      formatDateTime('2026-07-29T12:00:00Z'),
    )
  })

  it('defaults to date-time when the format is unknown', () => {
    expect(formatByFormat('2026-07-29T12:00:00Z')).toBe(
      formatDateTime('2026-07-29T12:00:00Z'),
    )
  })
})

describe('relTime with server timestamps', () => {
  it('treats a naive timestamp as UTC', () => {
    const now = Date.UTC(2026, 6, 29, 14, 0, 0)
    expect(relTime('2026-07-29T12:00:00', now)).toBe('2h')
  })

  it('agrees with the Z-suffixed form', () => {
    const now = Date.UTC(2026, 6, 29, 14, 0, 0)
    expect(relTime('2026-07-29 12:00:00', now)).toBe(
      relTime('2026-07-29T12:00:00Z', now),
    )
  })
})
