import { describe, expect, it } from 'vitest'

import type { MarkdownFormat } from '../markdown-format'
import { applyMarkdownFormat, spliceEdit } from '../markdown-format'

/**
 * Apply `format` to `marked`, where `[` and `]` mark the selection (a lone
 * `|` is a caret), and return the result in the same notation.
 */
function apply(format: MarkdownFormat, marked: string): string {
  let selectionStart: number
  let selectionEnd: number
  let value: string
  if (marked.includes('|')) {
    selectionStart = selectionEnd = marked.indexOf('|')
    value = marked.replace('|', '')
  } else {
    selectionStart = marked.indexOf('[')
    selectionEnd = marked.indexOf(']') - 1
    value = marked.replace('[', '').replace(']', '')
  }
  const edit = applyMarkdownFormat(format, {
    selectionEnd,
    selectionStart,
    value,
  })
  const out = spliceEdit(value, edit)
  if (edit.selectionStart === edit.selectionEnd) {
    return `${out.slice(0, edit.selectionStart)}|${out.slice(edit.selectionStart)}`
  }
  return (
    `${out.slice(0, edit.selectionStart)}[` +
    `${out.slice(edit.selectionStart, edit.selectionEnd)}]` +
    out.slice(edit.selectionEnd)
  )
}

describe('wraps', () => {
  it('wraps the selection in bold', () => {
    expect(apply('bold', 'a [word] b')).toBe('a **[word]** b')
  })

  it('inserts empty markers around the caret', () => {
    expect(apply('bold', 'a | b')).toBe('a **|** b')
    expect(apply('italic', '|')).toBe('_|_')
  })

  it('unwraps markers just outside the selection', () => {
    expect(apply('bold', 'a **[word]** b')).toBe('a [word] b')
    expect(apply('bold', 'a **|** b')).toBe('a | b')
  })

  it('unwraps markers inside the selection', () => {
    expect(apply('italic', 'a [_word_] b')).toBe('a [word] b')
  })

  it('leaves surrounding whitespace outside the markers', () => {
    expect(apply('bold', 'a[ word ]b')).toBe('a **[word]** b')
  })

  it('uses inline code for a single-line selection', () => {
    expect(apply('code', 'run [npm test] now')).toBe('run `[npm test]` now')
  })
})

describe('code blocks', () => {
  it('fences a multi-line selection', () => {
    expect(apply('code', '[a\nb]')).toBe('```\n[a\nb]\n```')
  })

  it('puts the fences on their own lines', () => {
    expect(apply('code', 'x [a\nb] y')).toBe('x \n```\n[a\nb]\n```\n y')
  })

  it('removes a selected fence', () => {
    expect(apply('code', '[```\na\nb\n```]')).toBe('[a\nb]')
  })
})

describe('link', () => {
  it('links the selection and selects the placeholder URL', () => {
    expect(apply('link', 'see [docs] here')).toBe('see [docs]([url]) here')
  })

  it('puts the caret in the brackets with nothing selected', () => {
    expect(apply('link', 'see |')).toBe('see [|](url)')
  })

  it('uses a selected URL as the target', () => {
    expect(apply('link', '[https://example.com]')).toBe(
      '[|](https://example.com)',
    )
  })
})

describe('line prefixes', () => {
  it('prefixes the caret line and keeps the caret in place', () => {
    expect(apply('heading', 'one\ntw|o')).toBe('one\n### tw|o')
    expect(apply('quote', '|')).toBe('> |')
  })

  it('prefixes every line of the selection', () => {
    expect(apply('quote', 'x[a\nb]')).toBe('[> xa\n> b]')
  })

  it('removes the prefix when every line has it', () => {
    expect(apply('quote', '[> a\n> b]')).toBe('[a\nb]')
    expect(apply('heading', '### ti|tle')).toBe('ti|tle')
  })

  it('replaces a different heading level', () => {
    expect(apply('heading', '## ti|tle')).toBe('### ti|tle')
  })

  it('numbers ordered list items, skipping blank lines', () => {
    expect(apply('orderedList', '[a\n\nb\nc]')).toBe('[1. a\n\n2. b\n3. c]')
  })

  it('switches between list kinds', () => {
    expect(apply('unorderedList', '[1. a\n2. b]')).toBe('[- a\n- b]')
    expect(apply('orderedList', '[- a\n- b]')).toBe('[1. a\n2. b]')
  })

  it('removes list markers when every line has them', () => {
    expect(apply('unorderedList', '[- a\n- b]')).toBe('[a\nb]')
    expect(apply('orderedList', '[1. a\n2. b]')).toBe('[a\nb]')
  })

  it('ignores the line after a trailing newline', () => {
    expect(apply('quote', '[a\n]b')).toBe('[> a]\nb')
  })
})
