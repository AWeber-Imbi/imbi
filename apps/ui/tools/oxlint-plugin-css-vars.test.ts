import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import {
  extractVarRefs,
  findSuggestion,
  levenshtein,
  parseCssCustomProperties,
} from './oxlint-plugin-css-vars'

describe('parseCssCustomProperties', () => {
  const cssFile = resolve(import.meta.dirname, '../src/index.css')

  it('parses custom properties from index.css', () => {
    const props = parseCssCustomProperties(cssFile)
    expect(props).toBeInstanceOf(Set)
    expect(props.size).toBeGreaterThan(50)
  })

  it('includes theme variables', () => {
    const props = parseCssCustomProperties(cssFile)
    expect(props.has('--text-color-primary')).toBe(true)
    expect(props.has('--border-color-tertiary')).toBe(true)
    expect(props.has('--background-color-action')).toBe(true)
  })

  it('includes design system variables', () => {
    const props = parseCssCustomProperties(cssFile)
    expect(props.has('--ds-text-primary')).toBe(true)
    expect(props.has('--ds-bg-primary')).toBe(true)
    expect(props.has('--ds-border-primary')).toBe(true)
  })

  it('does not include old v3-style variable names', () => {
    const props = parseCssCustomProperties(cssFile)
    expect(props.has('--color-text-tertiary')).toBe(false)
    expect(props.has('--color-border-primary')).toBe(false)
    expect(props.has('--color-background-danger')).toBe(false)
  })
})

describe('extractVarRefs', () => {
  it('extracts var() references', () => {
    const refs = extractVarRefs('var(--text-color-primary)')
    expect(refs).toEqual([{ index: 0, name: '--text-color-primary' }])
  })

  it('extracts multiple var() references', () => {
    const refs = extractVarRefs(
      '2px solid var(--border-color-primary) var(--text-color-danger)',
    )
    expect(refs).toHaveLength(2)
    expect(refs[0].name).toBe('--border-color-primary')
    expect(refs[1].name).toBe('--text-color-danger')
  })

  it('extracts var() with fallback', () => {
    const refs = extractVarRefs('var(--assistant-height, 0px)')
    expect(refs).toEqual([{ index: 0, name: '--assistant-height' }])
  })

  it('extracts Tailwind shorthand references', () => {
    const refs = extractVarRefs('bg-(--text-color-tertiary)')
    expect(refs).toEqual([{ index: 3, name: '--text-color-tertiary' }])
  })

  it('does not double-count var() as shorthand', () => {
    const refs = extractVarRefs('var(--text-color-primary)')
    expect(refs).toHaveLength(1)
  })

  it('returns empty for strings without CSS vars', () => {
    expect(extractVarRefs('just a string')).toEqual([])
    expect(extractVarRefs('flex items-center')).toEqual([])
  })

  it('handles mixed var() and shorthand in class strings', () => {
    const refs = extractVarRefs(
      'bg-[var(--border-color-success)] from-(--text-color-tertiary)',
    )
    expect(refs).toHaveLength(2)
    expect(refs[0].name).toBe('--border-color-success')
    expect(refs[1].name).toBe('--text-color-tertiary')
  })

  it('handles whitespace inside var()', () => {
    const refs = extractVarRefs('var( --text-color-primary )')
    expect(refs).toHaveLength(1)
    expect(refs[0].name).toBe('--text-color-primary')
  })

  it('handles whitespace inside shorthand refs', () => {
    const refs = extractVarRefs('bg-( --text-color-primary )')
    expect(refs).toHaveLength(1)
    expect(refs[0].name).toBe('--text-color-primary')
  })
})

describe('levenshtein', () => {
  it('returns 0 for identical strings', () => {
    expect(levenshtein('abc', 'abc')).toBe(0)
  })

  it('counts single character changes', () => {
    expect(levenshtein('abc', 'abd')).toBe(1)
    expect(levenshtein('abc', 'abcd')).toBe(1)
    expect(levenshtein('abc', 'ab')).toBe(1)
  })

  it('handles empty strings', () => {
    expect(levenshtein('', 'abc')).toBe(3)
    expect(levenshtein('abc', '')).toBe(3)
  })
})

describe('findSuggestion', () => {
  const candidates = new Set([
    '--background-color-action',
    '--border-color-primary',
    '--ds-text-primary',
    '--text-color-primary',
    '--text-color-secondary',
    '--text-color-tertiary',
  ])

  it('finds close matches', () => {
    expect(findSuggestion('--text-color-primry', candidates)).toBe(
      '--text-color-primary',
    )
  })

  it('returns null when no match is close enough', () => {
    expect(findSuggestion('--completely-unrelated', candidates)).toBe(null)
  })

  it('finds the closest match among multiple candidates', () => {
    expect(findSuggestion('--text-color-tertary', candidates)).toBe(
      '--text-color-tertiary',
    )
  })
})
