import { describe, expect, it } from 'vitest'

import { clusterConsecutive, sectionByDay } from '../grouping'

interface Item {
  actor: string
  t: number
}

const HOUR = 60 * 60 * 1000
const opts = {
  keyOf: (i: Item) => i.actor,
  timeOf: (i: Item) => i.t,
  windowMs: HOUR,
}

// Build timestamps from LOCAL date components so bucketing (which uses local
// calendar days) is independent of the test runner's timezone.
function local(y: number, mo: number, d: number, h = 0, mi = 0): number {
  return new Date(y, mo - 1, d, h, mi).getTime()
}

describe('clusterConsecutive', () => {
  it('groups adjacent same-key items within the window', () => {
    const items: Item[] = [
      { actor: 'bot', t: local(2026, 7, 17, 10, 0) },
      { actor: 'bot', t: local(2026, 7, 17, 9, 50) },
      { actor: 'bot', t: local(2026, 7, 17, 9, 40) },
    ]
    const clusters = clusterConsecutive(items, opts)
    expect(clusters).toHaveLength(1)
    expect(clusters[0].items).toHaveLength(3)
    expect(clusters[0].newest).toBe(local(2026, 7, 17, 10, 0))
    expect(clusters[0].oldest).toBe(local(2026, 7, 17, 9, 40))
  })

  it('splits when the actor changes', () => {
    const items: Item[] = [
      { actor: 'a', t: local(2026, 7, 17, 10, 0) },
      { actor: 'b', t: local(2026, 7, 17, 9, 55) },
      { actor: 'a', t: local(2026, 7, 17, 9, 50) },
    ]
    const clusters = clusterConsecutive(items, opts)
    expect(clusters).toHaveLength(3)
    expect(clusters.map((c) => c.items.length)).toEqual([1, 1, 1])
  })

  it('splits same-actor items separated by more than the window', () => {
    const items: Item[] = [
      { actor: 'a', t: local(2026, 7, 17, 10, 0) },
      { actor: 'a', t: local(2026, 7, 17, 8, 0) },
    ]
    const clusters = clusterConsecutive(items, opts)
    expect(clusters).toHaveLength(2)
  })

  it('keeps distinct keys across separate clusters (unique React keys)', () => {
    const items: Item[] = [
      { actor: 'a', t: local(2026, 7, 17, 10, 0) },
      { actor: 'b', t: local(2026, 7, 17, 9, 0) },
      { actor: 'a', t: local(2026, 7, 17, 8, 0) },
    ]
    const keys = clusterConsecutive(items, opts).map((c) => c.key)
    expect(new Set(keys).size).toBe(keys.length)
  })

  it('returns an empty list for no items', () => {
    expect(clusterConsecutive([], opts)).toEqual([])
  })
})

describe('sectionByDay', () => {
  const now = local(2026, 7, 17, 12, 0)

  it('buckets by local day and labels Today/Yesterday', () => {
    const items: Item[] = [
      { actor: 'a', t: local(2026, 7, 17, 10, 0) },
      { actor: 'a', t: local(2026, 7, 16, 10, 0) },
    ]
    const sections = sectionByDay(items, { ...opts, now })
    expect(sections).toHaveLength(2)
    expect(sections[0].label).toBe('Today')
    expect(sections[1].label).toBe('Yesterday')
  })

  it('does not cluster across a day boundary even within the window', () => {
    const items: Item[] = [
      { actor: 'a', t: local(2026, 7, 17, 0, 10) },
      { actor: 'a', t: local(2026, 7, 16, 23, 50) },
    ]
    const sections = sectionByDay(items, { ...opts, now })
    // 20 min apart but different days -> two sections, each a single cluster.
    expect(sections).toHaveLength(2)
    expect(sections[0].clusters).toHaveLength(1)
    expect(sections[1].clusters).toHaveLength(1)
  })
})
