import { describe, expect, it } from 'vitest'

import { turns } from '../conversationTurns'
import { timeline } from '../taskTimeline'
import { findEntry, trajectory } from '../taskTrajectory'
import { event } from './taskFixtures'

const human = (seq: number) =>
  event(seq, 'turn', { body: 'Go.' }, { actor_id: 'dev', actor_kind: 'human' })
const bash = (seq: number, extra: Record<string, unknown> = {}) =>
  event(seq, 'tool.called', {
    arguments: { command: 'ls' },
    call_id: `c${seq}`,
    result: 'ok',
    tool: 'Bash',
    ...extra,
  })
const at = (e: ReturnType<typeof event>) => Date.parse(e.at)

function build(log: ReturnType<typeof event>[], now: null | number = null) {
  const entries = timeline(log)
  return trajectory(entries, turns(entries, { live: now !== null }), now)
}

describe('trajectory', () => {
  it('starts a call its duration before its event', () => {
    const call = bash(3, { duration_ms: 1500 })
    const t = build([human(1), call])!
    expect(t.spans).toHaveLength(1)
    expect(t.spans[0]).toMatchObject({
      end: at(call),
      error: false,
      lane: 0,
      start: at(call) - 1500,
    })
    expect(t.start).toBe(at(human(1)))
    expect(t.end).toBe(at(call))
  })

  it('puts subagent calls on the second lane and marks failures', () => {
    const t = build([
      human(1),
      bash(2, { is_error: true, parent_call_id: 'task-1' }),
      event(4, 'tool.called', {
        arguments: { subagent_type: 'search' },
        call_id: 'task-1',
        duration_ms: 3000,
        result: 'done',
        tool: 'Task',
      }),
    ])!
    expect(t.spans.map((s) => [s.lane, s.error])).toEqual([
      [0, false],
      [1, true],
    ])
  })

  it('gives a running subagent a start and no end', () => {
    const child = bash(3, { duration_ms: 500, parent_call_id: 'task-1' })
    const now = at(child) + 10_000
    const t = build([human(1), child], now)!
    const pending = t.spans.find((s) => s.entry.event === null)!
    expect(pending).toMatchObject({
      end: null,
      lane: 0,
      start: at(child) - 500,
    })
    expect(t.end).toBe(now)
  })

  it('marks where each turn starts', () => {
    const t = build([
      human(1),
      bash(2),
      event(3, 'turn', { body: 'Done.' }),
      human(5),
      bash(6),
    ])!
    expect(t.marks).toEqual([
      { at: at(human(1)), label: 'T1' },
      { at: at(human(5)), label: 'T2' },
    ])
  })

  it('has nothing to draw without calls', () => {
    expect(build([human(1), event(2, 'turn', { body: 'Hi.' })])).toBeNull()
  })
})

describe('findEntry', () => {
  it('finds a subagent step by its seq', () => {
    const entries = timeline([
      bash(2, { parent_call_id: 'task-1' }),
      event(3, 'tool.called', { call_id: 'task-1', tool: 'Task' }),
    ])
    expect(findEntry(entries, 2)?.event?.seq).toBe(2)
    expect(findEntry(entries, 9)).toBeNull()
  })
})
