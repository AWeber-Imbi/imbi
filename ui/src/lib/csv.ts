/**
 * Client-side CSV export.
 *
 * Every report builds its rows in the browser already, so the export is
 * a pure client concern — no round trip, and what downloads is exactly
 * what the filters left on screen.
 */

/**
 * Build a CSV from `header` + `rows` and hand it to the browser as a
 * download named `filename`.
 *
 * The anchor is attached to the document before it is clicked and the
 * object URL is revoked on a later tick: Firefox ignores a synthetic
 * click on a detached anchor, and revoking in the same tick can abort
 * a download the browser has only just started.
 */
export function downloadCsv(
  filename: string,
  header: string[],
  rows: unknown[][],
): void {
  const blob = new Blob([toCsv(header, rows)], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.download = filename
  a.href = url
  a.style.display = 'none'
  document.body.append(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

/** Render a header row plus data rows as CSV text. */
export function toCsv(header: string[], rows: unknown[][]): string {
  return [
    header.map(quote).join(','),
    ...rows.map((row) => row.map(quote).join(',')),
  ].join('\n')
}

/** Quote one field, doubling any embedded quotes per RFC 4180. */
function quote(value: unknown): string {
  return `"${String(value ?? '').replace(/"/g, '""')}"`
}
