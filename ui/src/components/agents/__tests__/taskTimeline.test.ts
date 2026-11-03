import { describe, expect, it } from 'vitest'

import {
  countTimeline,
  DEFAULT_FILTERS,
  filterTimeline,
  joinParts,
  timeline,
  type TimelineEntry,
} from '../taskTimeline'
import { event } from './taskFixtures'

const call = (seq: number, tool: string, extra = {}, overrides = {}) =>
  event(seq, 'tool.called', { call_id: `c${seq}`, tool, ...extra }, overrides)
const sub = { actor_kind: 'subagent' as const }

/** `[label, depth]` rows of a timeline, depth first. */
function rows(entries: TimelineEntry[], depth = 0): [string, number][] {
  return entries.flatMap((entry) => [
    [
      entry.event
        ? String(
            entry.event.payload.tool ??
              entry.event.payload.body ??
              entry.event.type,
          )
        : entry.id,
      depth,
    ] as [string, number],
    ...rows(entry.children, depth + 1),
  ])
}

describe('timeline', () => {
  it('shows turns, calls, and state changes in seq order', () => {
    const entries = timeline([
      event(1, 'task.created'),
      event(2, 'session.opened'),
      event(3, 'state.changed', { from: 'queued', to: 'running' }),
      event(4, 'turn', { body: 'Reading.', kind: 'text' }),
      call(5, 'Bash'),
      event(6, 'phase.changed', { phase: 'fix' }),
    ])
    expect(rows(entries)).toEqual([
      ['state.changed', 0],
      ['Reading.', 0],
      ['Bash', 0],
      ['phase.changed', 0],
    ])
  })

  it('nests subagent events under the call that started them', () => {
    // The harness writes the Task call when it ends, after its children.
    const entries = timeline([
      event(1, 'turn', { body: 'Delegating.' }),
      event(2, 'turn', { body: 'Searching.', parent_call_id: 'c5' }, sub),
      call(3, 'Grep', { parent_call_id: 'c5' }, sub),
      call(4, 'Read'),
      call(5, 'Task'),
    ])
    expect(rows(entries)).toEqual([
      ['Delegating.', 0],
      ['Task', 0],
      ['Searching.', 1],
      ['Grep', 1],
      ['Read', 0],
    ])
  })

  it('groups the events of a subagent that is still running', () => {
    const entries = timeline([
      event(1, 'turn', { body: 'Searching.', parent_call_id: 'c9' }, sub),
      call(2, 'Grep', { parent_call_id: 'c9' }, sub),
    ])
    expect(rows(entries)).toEqual([
      ['pending:c9', 0],
      ['Searching.', 1],
      ['Grep', 1],
    ])
    expect(entries[0].event).toBeNull()
  })

  it('nests a subagent of a subagent', () => {
    const entries = timeline([
      call(1, 'Grep', { parent_call_id: 'c2' }, sub),
      call(2, 'Task', { parent_call_id: 'c3' }, sub),
      call(3, 'Task'),
    ])
    expect(rows(entries)).toEqual([
      ['Task', 0],
      ['Task', 1],
      ['Grep', 2],
    ])
  })
})

describe('joinParts', () => {
  it('joins the parts of a split result into its first event', () => {
    const joined = joinParts([
      call(1, 'Read', { call_id: 'big', part: 1, parts: 3, result: 'a' }),
      event(2, 'tool.called', {
        call_id: 'big',
        part: 2,
        parts: 3,
        result: 'b',
      }),
      event(3, 'turn', { body: 'between' }),
      event(4, 'tool.called', {
        call_id: 'big',
        part: 3,
        parts: 3,
        result: 'c',
      }),
    ])
    expect(joined.map((e) => [e.seq, e.payload])).toEqual([
      [1, { call_id: 'big', result: 'abc', tool: 'Read' }],
      [3, { body: 'between' }],
    ])
  })

  it('joins a split turn body and keeps the parts that arrived', () => {
    const joined = joinParts([
      event(1, 'turn', { body: 'Hello ', call_id: 't', part: 1, parts: 3 }),
      event(2, 'turn', { body: 'world', call_id: 't', part: 2, parts: 3 }),
    ])
    expect(joined).toHaveLength(1)
    expect(joined[0].payload.body).toBe('Hello world')
  })
})

describe('filterTimeline', () => {
  const entries = timeline([
    event(1, 'turn', { body: 'Plan.', kind: 'text' }),
    event(2, 'turn', { body: 'Hmm.', kind: 'thinking' }),
    call(3, 'Grep', { is_error: true, parent_call_id: 'c4' }, sub),
    call(4, 'Task'),
    call(5, 'Bash', { policy: { decision: 'deny' } }),
    call(6, 'Read', { arguments: { file_path: 'src/feeds.py' } }),
    event(7, 'phase.changed', { phase: 'fix' }),
  ])

  it('counts each filter', () => {
    expect(countTimeline(entries)).toEqual({
      errors: 2,
      messages: 1,
      subagents: 1,
      system: 1,
      thinking: 1,
      tools: 3,
    })
  })

  it('hides a category', () => {
    const shown = filterTimeline(entries, {
      ...DEFAULT_FILTERS,
      thinking: false,
      tools: false,
    })
    expect(rows(shown)).toEqual([
      ['Plan.', 0],
      ['phase.changed', 0],
    ])
  })

  it('keeps errors, and the call whose subagent failed', () => {
    const shown = filterTimeline(entries, {
      ...DEFAULT_FILTERS,
      errorsOnly: true,
    })
    expect(rows(shown)).toEqual([
      ['Task', 0],
      ['Grep', 1],
      ['Bash', 0],
    ])
  })

  it('drops children when subagents are off', () => {
    const shown = filterTimeline(entries, {
      ...DEFAULT_FILTERS,
      subagents: false,
    })
    expect(
      shown.find((e) => e.event?.payload.tool === 'Task')?.children,
    ).toEqual([])
  })

  it('searches payloads, children included', () => {
    expect(
      rows(filterTimeline(entries, { ...DEFAULT_FILTERS, query: 'FEEDS' })),
    ).toEqual([['Read', 0]])
    expect(
      rows(filterTimeline(entries, { ...DEFAULT_FILTERS, query: 'grep' })),
    ).toEqual([
      ['Task', 0],
      ['Grep', 1],
    ])
  })
})
