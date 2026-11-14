import { describe, expect, it } from 'vitest'

import { highlightable, matches, matchRanges } from '../taskSearch'

describe('matchRanges', () => {
  it('finds every match, case-insensitively', () => {
    expect(matchRanges('Foo foo FOO', 'foo')).toEqual([
      [0, 3],
      [4, 7],
      [8, 11],
    ])
  })

  it('keeps offsets inside the text when lowercasing lengthens it', () => {
    const text = 'İİ foo'
    expect(matchRanges(text, 'foo')).toEqual([[3, 6]])
    for (const [, end] of matchRanges(text, 'i')) {
      expect(end).toBeLessThanOrEqual(text.length)
    }
  })

  it('matches nothing for an empty query', () => {
    expect(matchRanges('abc', '')).toEqual([])
    expect(matches('abc', ' ')).toBe(true)
  })
})

describe('highlightable', () => {
  it('leaves out text inside a skipped element', () => {
    const root = document.createElement('div')
    root.innerHTML =
      '<p>zz in a turn</p><div data-search-skip><p>zz in the empty state</p></div>'
    expect(highlightable(root).map((n) => n.textContent)).toEqual([
      'zz in a turn',
    ])
  })
})
