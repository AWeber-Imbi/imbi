import { describe, expect, it } from 'vitest'

import {
  chainTerminals,
  splitChains,
  upstreamBySlug,
} from '../environment-chains'

const TWO_PIPELINES = [
  { name: 'Infra Testing', slug: 'infra-testing', sort_order: 1 },
  { name: 'Infra', slug: 'infra', sort_order: 2, terminal: true },
  { name: 'Testing', slug: 'testing', sort_order: 3 },
  { name: 'Staging', slug: 'staging', sort_order: 4 },
]

describe('splitChains', () => {
  it('keeps one pipeline as one sorted chain', () => {
    const chains = splitChains([
      { name: 'Staging', slug: 'staging', sort_order: 2 },
      { name: 'Testing', slug: 'testing', sort_order: 1 },
    ])
    expect(chains.map((c) => c.map((e) => e.slug))).toEqual([
      ['testing', 'staging'],
    ])
  })

  it('splits after a terminal environment', () => {
    const chains = splitChains(TWO_PIPELINES)
    expect(chains.map((c) => c.map((e) => e.slug))).toEqual([
      ['infra-testing', 'infra'],
      ['testing', 'staging'],
    ])
  })

  it('adds no empty chain after a terminal final env', () => {
    const chains = splitChains([
      { name: 'Testing', slug: 'testing', sort_order: 1 },
      { name: 'Production', slug: 'production', sort_order: 2, terminal: true },
    ])
    expect(chains).toHaveLength(1)
  })

  it('handles an empty list', () => {
    expect(splitChains([])).toEqual([])
  })
})

describe('chainTerminals', () => {
  it('returns the last env of each pipeline', () => {
    expect(chainTerminals(TWO_PIPELINES).map((e) => e.slug)).toEqual([
      'infra',
      'staging',
    ])
  })
})

describe('upstreamBySlug', () => {
  it('maps each env to its upstream within its own pipeline', () => {
    const upstreams = upstreamBySlug(TWO_PIPELINES)
    expect(upstreams.get('infra-testing')).toBeNull()
    expect(upstreams.get('infra')?.slug).toBe('infra-testing')
    // The env after a terminal one starts a new pipeline: no upstream,
    // and the terminal env is never anyone's upstream.
    expect(upstreams.get('testing')).toBeNull()
    expect(upstreams.get('staging')?.slug).toBe('testing')
  })
})
