import { describe, expect, it } from 'vitest'

import { computeDriftPairs } from '../deployment-drift'

const ENVS = [
  { name: 'Testing', slug: 'testing', sort_order: 1 },
  { name: 'Staging', slug: 'staging', sort_order: 2 },
]

describe('computeDriftPairs', () => {
  it('reports drift when adjacent envs run different commits', () => {
    const pairs = computeDriftPairs(ENVS, {
      staging: { committish: 'bbb', tag: '3.5.4' },
      testing: { committish: 'aaa', tag: '3.5.5' },
    })
    expect(pairs).toHaveLength(1)
    expect(pairs[0].drifted).toBe(true)
    expect(pairs[0].from).toBe('Testing')
    expect(pairs[0].to).toBe('Staging')
  })

  it('ignores a tag-only difference on the same commit', () => {
    const pairs = computeDriftPairs(ENVS, {
      staging: { committish: 'aaa', tag: null },
      testing: { committish: 'aaa', tag: '3.5.5' },
    })
    expect(pairs[0].drifted).toBe(false)
  })

  it('falls back to tags when a SHA is missing', () => {
    const pairs = computeDriftPairs(ENVS, {
      staging: { tag: '3.5.4' },
      testing: { tag: '3.5.5' },
    })
    expect(pairs[0].drifted).toBe(true)
  })

  it('orders envs by sort_order, not object key order', () => {
    const pairs = computeDriftPairs(
      [
        { name: 'Staging', slug: 'staging', sort_order: 2 },
        { name: 'Testing', slug: 'testing', sort_order: 1 },
      ],
      {},
    )
    expect(pairs[0].from).toBe('Testing')
  })
})
