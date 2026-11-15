import { matches } from './taskSearch'
import { type Family, label, OUTPUT_LINES } from './toolCalls'

export type ToolPart = 'input' | 'output'

/** Whether lines are cut at {@link OUTPUT_LINES}. */
export function cutAt(lines: string[], all: boolean, query: string): boolean {
  return (
    !all &&
    lines.length > OUTPUT_LINES &&
    !searchHit(lines.slice(OUTPUT_LINES), query)
  )
}

export function cutText(lines: string[]): string {
  return lines.slice(0, OUTPUT_LINES).join('\n')
}

export function diffPath(args: Record<string, unknown>): string {
  return String(args.file_path ?? args.notebook_path ?? '')
}

/** The rows of a diff: old text above new text, edit by edit. */
export function diffRows(args: Record<string, unknown>) {
  const edits: { new_string?: unknown; old_string?: unknown }[] = Array.isArray(
    args.edits,
  )
    ? (args.edits as { new_string?: unknown; old_string?: unknown }[])
    : [
        {
          new_string: args.new_string ?? args.content ?? args.new_source,
          old_string: args.old_string,
        },
      ]
  const lines = (v: unknown) => (typeof v === 'string' ? v.split('\n') : [])
  const rows: { className: string; key: string; text: string }[] = []
  edits.forEach((edit, i) => {
    if (i > 0)
      rows.push({ className: 'text-tertiary', key: `s${i}`, text: '⋯' })
    lines(edit.old_string).forEach((l, j) =>
      rows.push({
        className: 'bg-danger text-danger',
        key: `o${i}-${j}`,
        text: `- ${l}`,
      }),
    )
    lines(edit.new_string).forEach((l, j) =>
      rows.push({
        className: 'bg-success text-success',
        key: `n${i}-${j}`,
        text: `+ ${l}`,
      }),
    )
  })
  return rows
}

/**
 * The text `ToolReadable` shows for these props while `query` is the
 * task search, for the browser's find.
 */
export function readableText({
  args,
  argsText,
  error,
  family,
  isWhole,
  query,
  result,
}: {
  args: Record<string, unknown>
  argsText: null | string
  error: boolean
  family: Family
  isWhole: (part: ToolPart) => boolean
  query: string
  result: string
}): string[] {
  const part = (text: string, name: ToolPart) => {
    const lines = text.split('\n')
    return cutAt(lines, isWhole(name), query) ? cutText(lines) : text
  }
  const output = result ? [part(result, 'output')] : []
  if (argsText != null) return [part(argsText, 'input'), ...output]
  if (family === 'shell')
    return [
      part(
        `$ ${String(args.command ?? '')}${result ? `\n${result}` : ''}`,
        'output',
      ),
    ]
  if (family === 'edit' && !error)
    return [
      diffPath(args),
      part(
        diffRows(args)
          .map((row) => row.text)
          .join('\n'),
        'input',
      ),
    ]
  return [
    Object.entries(args)
      .map(([k, v]) => `${k} ${label(v)}`)
      .join('\n'),
    ...output,
  ]
}

function searchHit(lines: string[], query: string): boolean {
  return (
    query.trim() !== '' && lines.length > 0 && matches(lines.join('\n'), query)
  )
}
