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

  it('carries the range endpoints, base being the later env', () => {
    // Testing runs the newer code, so it is the head of the range even
    // though it sorts first; staging's commit is the base.
    const pairs = computeDriftPairs(ENVS, {
      staging: { committish: 'bbb' },
      testing: { committish: 'aaa' },
    })
    expect(pairs[0].baseSha).toBe('bbb')
    expect(pairs[0].headSha).toBe('aaa')
  })

  it('leaves the endpoints null when a side has no commit', () => {
    const pairs = computeDriftPairs(ENVS, {
      staging: { tag: '3.5.4' },
      testing: { tag: '3.5.5' },
    })
    expect(pairs[0].baseSha).toBeNull()
    expect(pairs[0].headSha).toBeNull()
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

  it('derives no pair across a terminal boundary (#285)', () => {
    // Two independent pipelines in one list: the infra chain ends at
    // its terminal env, testing starts a new one. Differing commits on
    // either side of the seam must not register as a drift pair.
    const pairs = computeDriftPairs(
      [
        { name: 'Infra Testing', slug: 'infra-testing', sort_order: 1 },
        { name: 'Infra', slug: 'infra', sort_order: 2, terminal: true },
        { name: 'Testing', slug: 'testing', sort_order: 3 },
        { name: 'Staging', slug: 'staging', sort_order: 4 },
      ],
      {
        infra: { committish: 'ccc' },
        'infra-testing': { committish: 'ddd' },
        staging: { committish: 'aaa' },
        testing: { committish: 'bbb' },
      },
    )
    expect(pairs.map((p) => `${p.from}->${p.to}`)).toEqual([
      'Infra Testing->Infra',
      'Testing->Staging',
    ])
    expect(pairs.every((p) => p.drifted)).toBe(true)
  })
})
