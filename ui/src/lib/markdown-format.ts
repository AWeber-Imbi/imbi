/**
 * Pure markdown formatting for the toolbar in `ui/markdown-editor`. Each
 * action turns a textarea's value + selection into a single splice plus the
 * selection to restore afterwards, so the caller can apply it with
 * `execCommand('insertText')` and keep native undo. Behaviour follows
 * GitHub's comment toolbar: wraps and line prefixes toggle off when they are
 * already applied.
 */

/** Replace `value[replaceStart, replaceEnd)` with `text`, then select. */
export interface MarkdownEdit {
  replaceEnd: number
  replaceStart: number
  selectionEnd: number
  selectionStart: number
  text: string
}

export type MarkdownFormat =
  | 'bold'
  | 'code'
  | 'heading'
  | 'italic'
  | 'link'
  | 'orderedList'
  | 'quote'
  | 'unorderedList'

export interface TextSelection {
  selectionEnd: number
  selectionStart: number
  value: string
}

const URL_PATTERN = /^https?:\/\/\S+$/
const URL_PLACEHOLDER = 'url'

interface LinePrefix {
  /** Markers the new prefix replaces, e.g. `1. ` when switching to `- `. */
  existing?: RegExp
  /** The prefix for the `i`th non-blank line. */
  prefix: (i: number) => string
  /** Matches lines that already carry this prefix — all do → remove it. */
  toggle: RegExp
}

export function applyMarkdownFormat(
  format: MarkdownFormat,
  selection: TextSelection,
): MarkdownEdit {
  switch (format) {
    case 'bold':
      return wrap(selection, '**')
    case 'code':
      return code(selection)
    case 'heading':
      return prefixLines(selection, {
        existing: /^#{1,6} /,
        prefix: () => '### ',
        toggle: /^### /,
      })
    case 'italic':
      return wrap(selection, '_')
    case 'link':
      return link(selection)
    case 'orderedList':
      return prefixLines(selection, {
        existing: /^(?:[-*+]|\d+\.) /,
        prefix: (i) => `${i + 1}. `,
        toggle: /^\d+\. /,
      })
    case 'quote':
      return prefixLines(selection, { prefix: () => '> ', toggle: /^> / })
    case 'unorderedList':
      return prefixLines(selection, {
        existing: /^(?:[-*+]|\d+\.) /,
        prefix: () => '- ',
        toggle: /^- /,
      })
  }
}

/** Apply an edit to a value — for callers that can't use `execCommand`. */
export function spliceEdit(value: string, edit: MarkdownEdit): string {
  return (
    value.slice(0, edit.replaceStart) + edit.text + value.slice(edit.replaceEnd)
  )
}

function code(selection: TextSelection): MarkdownEdit {
  const { selectionEnd, selectionStart, value } = selection
  const selected = value.slice(selectionStart, selectionEnd)
  if (!selected.includes('\n')) return wrap(selection, '`')

  const fence = '```'
  if (
    selected.startsWith(`${fence}\n`) &&
    selected.endsWith(`\n${fence}`) &&
    selected.length >= fence.length * 2 + 2
  ) {
    const inner = selected.slice(fence.length + 1, -(fence.length + 1))
    return {
      replaceEnd: selectionEnd,
      replaceStart: selectionStart,
      selectionEnd: selectionStart + inner.length,
      selectionStart,
      text: inner,
    }
  }

  // A fence must sit on its own lines.
  const before =
    selectionStart > 0 && value[selectionStart - 1] !== '\n' ? '\n' : ''
  const after =
    selectionEnd < value.length && value[selectionEnd] !== '\n' ? '\n' : ''
  const opening = `${before}${fence}\n`
  return {
    replaceEnd: selectionEnd,
    replaceStart: selectionStart,
    selectionEnd: selectionStart + opening.length + selected.length,
    selectionStart: selectionStart + opening.length,
    text: `${opening}${selected}\n${fence}${after}`,
  }
}

function link(selection: TextSelection): MarkdownEdit {
  const { value } = selection
  const { end, start } = trimmed(selection)
  const selected = value.slice(start, end)

  // A selected URL becomes the target; the caret waits for the link text.
  if (URL_PATTERN.test(selected)) {
    return {
      replaceEnd: end,
      replaceStart: start,
      selectionEnd: start + 1,
      selectionStart: start + 1,
      text: `[](${selected})`,
    }
  }

  // Otherwise select the placeholder URL so typing replaces it. With nothing
  // selected there's no text yet, so the caret goes inside the brackets.
  const text = `[${selected}](${URL_PLACEHOLDER})`
  if (!selected) {
    return {
      replaceEnd: end,
      replaceStart: start,
      selectionEnd: start + 1,
      selectionStart: start + 1,
      text,
    }
  }
  const urlStart = start + selected.length + 3
  return {
    replaceEnd: end,
    replaceStart: start,
    selectionEnd: urlStart + URL_PLACEHOLDER.length,
    selectionStart: urlStart,
    text,
  }
}

function prefixLines(
  { selectionEnd, selectionStart, value }: TextSelection,
  { existing, prefix, toggle }: LinePrefix,
): MarkdownEdit {
  // Expand to whole lines. A selection ending just after a newline (e.g. a
  // triple-click) doesn't take in the following line.
  const lineStart = value.lastIndexOf('\n', selectionStart - 1) + 1
  const end =
    selectionEnd > selectionStart && value[selectionEnd - 1] === '\n'
      ? selectionEnd - 1
      : selectionEnd
  const newline = value.indexOf('\n', end)
  const lineEnd = newline === -1 ? value.length : newline

  const lines = value.slice(lineStart, lineEnd).split('\n')
  // Blank lines inside a multi-line selection are left alone, so a list
  // doesn't grow empty items; a lone blank line (just the caret) is prefixed.
  const touched = (line: string) => lines.length === 1 || line.trim() !== ''
  const remove = lines.filter(touched).every((line) => toggle.test(line))

  let n = 0
  const next = lines.map((line) => {
    if (!touched(line)) return line
    if (remove) return line.replace(toggle, '')
    const bare = existing ? line.replace(existing, '') : line
    return prefix(n++) + bare
  })
  const text = next.join('\n')

  if (selectionStart === selectionEnd && lines.length === 1) {
    const caret = Math.max(
      lineStart,
      selectionStart + (next[0].length - lines[0].length),
    )
    return {
      replaceEnd: lineEnd,
      replaceStart: lineStart,
      selectionEnd: caret,
      selectionStart: caret,
      text,
    }
  }
  return {
    replaceEnd: lineEnd,
    replaceStart: lineStart,
    selectionEnd: lineStart + text.length,
    selectionStart: lineStart,
    text,
  }
}

/**
 * Shrink the selection past surrounding whitespace, so double-clicking a word
 * (which selects its trailing space on some platforms) wraps just the word.
 */
function trimmed({ selectionEnd, selectionStart, value }: TextSelection): {
  end: number
  start: number
} {
  let start = selectionStart
  let end = selectionEnd
  while (start < end && /\s/.test(value[start])) start++
  while (end > start && /\s/.test(value[end - 1])) end--
  return { end, start }
}

function wrap(selection: TextSelection, marker: string): MarkdownEdit {
  const { value } = selection
  const { end, start } = trimmed(selection)
  const selected = value.slice(start, end)
  const m = marker.length

  // The selection itself carries the markers: unwrap inside it.
  if (
    selected.length >= m * 2 &&
    selected.startsWith(marker) &&
    selected.endsWith(marker)
  ) {
    const inner = selected.slice(m, -m)
    return {
      replaceEnd: end,
      replaceStart: start,
      selectionEnd: start + inner.length,
      selectionStart: start,
      text: inner,
    }
  }

  // The markers sit just outside the selection: remove them.
  if (
    value.slice(start - m, start) === marker &&
    value.slice(end, end + m) === marker
  ) {
    return {
      replaceEnd: end + m,
      replaceStart: start - m,
      selectionEnd: end - m,
      selectionStart: start - m,
      text: selected,
    }
  }

  return {
    replaceEnd: end,
    replaceStart: start,
    selectionEnd: start + m + selected.length,
    selectionStart: start + m,
    text: `${marker}${selected}${marker}`,
  }
}
