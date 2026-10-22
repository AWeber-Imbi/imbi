import { describe, expect, it } from 'vitest'

import { formatFrontmatterValue, splitFrontmatter } from '../frontmatter'

describe('splitFrontmatter', () => {
  it('splits a YAML header from the body', () => {
    const { body, meta } = splitFrontmatter(
      '---\ntype: PRD\ndate: 2026-10-22\nservice: [a, b]\n---\n# Title\n',
    )
    expect(meta).toEqual({
      date: '2026-10-22',
      service: ['a', 'b'],
      type: 'PRD',
    })
    expect(body).toBe('# Title\n')
  })

  it('leaves markdown without a header unchanged', () => {
    expect(splitFrontmatter('# Title\n---\nx: y\n---\n')).toEqual({
      body: '# Title\n---\nx: y\n---\n',
      meta: null,
    })
  })

  it('leaves a non-mapping or invalid header unchanged', () => {
    for (const md of ['---\njust prose\n---\nbody', '---\na: [\n---\nbody']) {
      expect(splitFrontmatter(md)).toEqual({ body: md, meta: null })
    }
  })
})

describe('formatFrontmatterValue', () => {
  it('formats lists, nulls and objects', () => {
    expect(formatFrontmatterValue(['a', 'b'])).toBe('a, b')
    expect(formatFrontmatterValue(null)).toBe('')
    expect(formatFrontmatterValue({ a: 1 })).toBe('{"a":1}')
  })
})
