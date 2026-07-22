import { describe, expect, it } from 'vitest'

import {
  cardsReducer,
  HISTORY_LIMIT,
  historyReducer,
} from '@/contexts/GraphQueryContext'
import type { GraphQueryCard, GraphQueryHistoryEntry } from '@/types'

function makeCard(overrides: Partial<GraphQueryCard> = {}): GraphQueryCard {
  return {
    collapsed: false,
    elapsedMs: 12,
    id: 'card-1',
    query: 'MATCH (n) RETURN n',
    result: { columns: [], edges: [], elapsed_ms: 12, nodes: [], rows: [] },
    startedAt: 1_700_000_000_000,
    status: 'success',
    tab: 'table',
    ...overrides,
  }
}

describe('cardsReducer', () => {
  it('prepends new cards', () => {
    const a = makeCard({ id: 'a' })
    const b = makeCard({ id: 'b' })
    const after = cardsReducer([a], { card: b, type: 'add' })
    expect(after.map((c) => c.id)).toEqual(['b', 'a'])
  })

  it('dismisses cards by id', () => {
    const a = makeCard({ id: 'a' })
    const b = makeCard({ id: 'b' })
    const after = cardsReducer([a, b], { id: 'a', type: 'dismiss' })
    expect(after.map((c) => c.id)).toEqual(['b'])
  })

  it('toggles collapsed flag', () => {
    const a = makeCard({ collapsed: false, id: 'a' })
    const once = cardsReducer([a], { id: 'a', type: 'toggleCollapsed' })
    expect(once[0].collapsed).toBe(true)
    const twice = cardsReducer(once, { id: 'a', type: 'toggleCollapsed' })
    expect(twice[0].collapsed).toBe(false)
  })

  it('updates the active tab for a card', () => {
    const a = makeCard({ id: 'a', tab: 'table' })
    const after = cardsReducer([a], { id: 'a', tab: 'graph', type: 'setTab' })
    expect(after[0].tab).toBe('graph')
  })

  it('leaves other cards alone when updating one', () => {
    const a = makeCard({ id: 'a', tab: 'table' })
    const b = makeCard({ id: 'b', tab: 'table' })
    const after = cardsReducer([a, b], { id: 'b', tab: 'raw', type: 'setTab' })
    expect(after[0].tab).toBe('table')
    expect(after[1].tab).toBe('raw')
  })
})

describe('historyReducer', () => {
  function entry(query: string, executedAt = 1): GraphQueryHistoryEntry {
    return { executedAt, query }
  }

  it('prepends new entries', () => {
    const after = historyReducer([entry('A')], {
      entry: entry('B', 2),
      type: 'add',
    })
    expect(after.map((e) => e.query)).toEqual(['B', 'A'])
  })

  it('dedupes consecutive duplicates', () => {
    let state: GraphQueryHistoryEntry[] = []
    state = historyReducer(state, { entry: entry('A', 1), type: 'add' })
    state = historyReducer(state, { entry: entry('A', 2), type: 'add' })
    state = historyReducer(state, { entry: entry('A', 3), type: 'add' })
    expect(state.map((e) => e.query)).toEqual(['A'])
  })

  it('does not dedupe non-consecutive duplicates', () => {
    let state: GraphQueryHistoryEntry[] = []
    state = historyReducer(state, { entry: entry('A', 1), type: 'add' })
    state = historyReducer(state, { entry: entry('B', 2), type: 'add' })
    state = historyReducer(state, { entry: entry('A', 3), type: 'add' })
    expect(state.map((e) => e.query)).toEqual(['A', 'B', 'A'])
  })

  it('ignores empty queries', () => {
    const after = historyReducer([], { entry: entry('   ', 1), type: 'add' })
    expect(after).toEqual([])
  })

  it('caps at HISTORY_LIMIT entries', () => {
    let state: GraphQueryHistoryEntry[] = []
    for (let i = 0; i < HISTORY_LIMIT + 25; i++) {
      state = historyReducer(state, {
        entry: entry(`Q${i}`, i),
        type: 'add',
      })
    }
    expect(state.length).toBe(HISTORY_LIMIT)
    // newest first
    expect(state[0].query).toBe(`Q${HISTORY_LIMIT + 24}`)
  })

  it('clears all entries', () => {
    const after = historyReducer([entry('A'), entry('B')], { type: 'clear' })
    expect(after).toEqual([])
  })

  it('initialises from a snapshot and truncates to the limit', () => {
    const seed = Array.from({ length: HISTORY_LIMIT + 5 }, (_, i) =>
      entry(`Q${i}`, i),
    )
    const after = historyReducer([], { entries: seed, type: 'init' })
    expect(after.length).toBe(HISTORY_LIMIT)
    expect(after[0].query).toBe('Q0')
  })
})
