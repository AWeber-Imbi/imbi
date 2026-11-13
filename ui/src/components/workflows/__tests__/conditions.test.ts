import { describe, expect, it } from 'vitest'

import { conditionWarnings, mismatch, referenceTypes } from '../conditions'
import type { ReferenceGroup } from '../references'

const GROUPS: ReferenceGroup[] = [
  {
    key: 'triage',
    mayNotRun: false,
    references: [
      { path: 'triage.result.count', type: 'integer' },
      { path: 'triage.result.risk', type: 'string | null' },
      { path: 'triage.result.tags', type: 'array<string | null>' },
      { path: 'triage.result', type: 'object | null' },
      { path: 'triage.payload', type: 'any' },
    ],
    title: 'Triage',
  },
  {
    key: 'trigger',
    mayNotRun: false,
    references: [{ path: 'trigger.count', type: 'number' }],
    title: 'Trigger',
  },
]

describe('mismatch', () => {
  it('names what a side needs when no type fits', () => {
    expect(mismatch('greater_than', 'a', ['string'])).toBe('a number')
    expect(mismatch('contains', 'a', ['integer'])).toBe('text or a list')
    expect(mismatch('matches', 'a', ['number'])).toBe('text')
    expect(mismatch('contains', 'b', ['object'])).toBe('a single value')
  })

  it('accepts a fitting or unknown type', () => {
    expect(mismatch('greater_than', 'a', ['integer'])).toBeNull()
    expect(mismatch('contains', 'a', ['array'])).toBeNull()
    expect(mismatch('equals', 'a', ['string', 'array'])).toBeNull()
    expect(mismatch('is_empty', 'a', ['object'])).toBeNull()
    expect(mismatch('greater_than', 'a', [])).toBeNull()
  })
})

describe('referenceTypes', () => {
  it('reads the type of a value that is one reference', () => {
    expect(referenceTypes('{{ triage.result.count }}', GROUPS)).toEqual([
      'integer',
    ])
    expect(referenceTypes('{{triage.result.risk}}', GROUPS)).toEqual(['string'])
    expect(referenceTypes('{{ triage.result.tags }}', GROUPS)).toEqual([
      'array',
    ])
  })

  it('knows no type for text, the trigger, or an untyped value', () => {
    for (const value of [
      'n{{ triage.result.count }}',
      '{{ trigger.count }}',
      '{{ triage.payload }}',
      '{{ triage.result.nope }}',
      5,
      undefined,
    ]) {
      expect(referenceTypes(value, GROUPS)).toEqual([])
    }
  })
})

describe('conditionWarnings', () => {
  it('explains a reference that the operator cannot use', () => {
    expect(
      conditionWarnings(
        { a: '{{ triage.result.risk }}', b: '3', operator: 'greater_than' },
        GROUPS,
      ),
    ).toEqual([
      '{{ triage.result.risk }} is string, but "is greater than" needs a number.',
    ])
    expect(
      conditionWarnings(
        { a: 'x', b: '{{ triage.result }}', operator: 'contains' },
        GROUPS,
      ),
    ).toEqual([
      '{{ triage.result }} is object, but "contains" needs a single value.',
    ])
  })

  it('ignores b of an empty check', () => {
    expect(
      conditionWarnings(
        {
          a: '{{ triage.result }}',
          b: '{{ triage.result }}',
          operator: 'is_empty',
        },
        GROUPS,
      ),
    ).toEqual([])
  })
})
