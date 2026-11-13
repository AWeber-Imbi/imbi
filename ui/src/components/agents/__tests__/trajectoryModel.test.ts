import { describe, expect, it } from 'vitest'

import {
  buildTrajectory,
  foldKeys,
  type Folds,
  formatDuration,
  preview,
  recordForSeq,
  rowsOf,
  spansOf,
} from '../trajectoryModel'
import { event } from './taskFixtures'

const none = (): Folds => ({
  calls: new Set(),
  subcalls: new Set(),
  turns: new Set(),
})

const human = { actor_id: 'u@x', actor_kind: 'human' as const }

function log() {
  return [
    event(1, 'task.created', {
      description: 'Check the **release**',
      title: 'T',
    }),
    event(2, 'session.opened', { session_id: 's' }),
    event(3, 'secret.resolution', { action: 'created', reference: 'gh' }),
    event(5, 'usage.reported', { tokens_in: 2, tokens_out: 9 }),
    event(4, 'turn', { body: 'Looking at releases', kind: 'thinking' }),
    event(6, 'tool.called', {
      arguments: { command: 'ls' },
      call_id: 'c1',
      duration_ms: 500,
      result: 'a\nb',
      tool: 'Bash',
    }),
    event(7, 'tool.called', {
      arguments: { description: 'verify', subagent_type: 'review' },
      call_id: 'c2',
      duration_ms: 2000,
      is_error: true,
      result: 'blocked',
      tool: 'Agent',
    }),
    event(8, 'usage.reported', { tokens_in: 2, tokens_out: 30 }),
    event(9, 'turn', { body: 'All **done**.', kind: 'text' }),
    event(10, 'turn', { body: 'Also check prod', kind: 'text' }, human),
    event(11, 'usage.reported', { tokens_in: 2, tokens_out: 5 }),
    event(12, 'tool.called', {
      arguments: { pattern: 'x' },
      call_id: 'c3',
      duration_ms: 1000,
      result: '',
      tool: 'Grep',
    }),
    event(13, 'state.changed', { from: 'running', to: 'closed' }),
  ]
}

describe('buildTrajectory', () => {
  it('maps events to DSH kinds in log order', () => {
    const t = buildTrajectory(log(), false)
    expect(t.records.map((r) => r.kind)).toEqual([
      'user',
      'system',
      'system',
      'assistant',
      'tool',
      'tool',
      'assistant',
      'user',
      'assistant',
      'tool',
      'system',
    ])
    expect(t.records[0].text).toBe('Check the release')
    expect(t.records[2].text).toBe('Secret created: gh')
    expect(t.records[4].text).toBe('Bash ls')
    expect(t.records[5].error).toBe(true)
  })

  it('numbers requests across the task and steps within a turn', () => {
    const t = buildTrajectory(log(), false)
    expect(
      t.requests.map((r) => [r.number, r.turn, r.step, r.toolCalls]),
    ).toEqual([
      [1, 1, 1, 2],
      [2, 1, 2, 0],
      [3, 2, 1, 1],
    ])
    expect(t.turns.map((x) => [x.number, x.steps, x.toolCalls])).toEqual([
      [1, 2, 2],
      [2, 1, 1],
    ])
  })

  it('joins thinking and reply, and marks tool-only requests', () => {
    const t = buildTrajectory(log(), false)
    const [first, second, third] = t.records.filter(
      (r) => r.kind === 'assistant',
    )
    expect(first.text).toBe('Looking at releases')
    expect(second.text).toBe('All done.')
    expect(third.text).toBe('')
    expect(first.seqs).toEqual([5, 4])
  })

  it('times tools back from their result and the model up to its first call', () => {
    const t = buildTrajectory(log(), false)
    const at = (s: number) =>
      Date.parse(`2026-10-08T12:00:${String(s).padStart(2, '0')}Z`)
    const bash = t.records[4]
    expect([bash.startedAt, bash.endedAt]).toEqual([at(6) - 500, at(6)])
    const model = t.records[3]
    expect(model.startedAt).toBe(at(3))
    expect(model.endedAt).toBe(at(5))
  })

  it('opens a pending request for agent work with no usage yet', () => {
    const t = buildTrajectory(
      [
        event(1, 'task.created', { title: 'T' }),
        event(2, 'turn', { body: 'Thinking', kind: 'thinking' }),
      ],
      true,
    )
    expect(t.requests[0].status).toBe('pending')
    expect(t.records[1].endedAt).toBeNull()
  })

  it('makes subagent calls subtools of their parent call', () => {
    const t = buildTrajectory(
      [
        event(1, 'task.created', { title: 'T' }),
        event(2, 'usage.reported', {}),
        event(3, 'tool.called', {
          call_id: 's1',
          parent_call_id: 'c1',
          tool: 'Read',
        }),
        event(4, 'tool.called', { call_id: 'c1', tool: 'Agent' }),
      ],
      false,
    )
    expect(t.records.map((r) => r.kind)).toEqual([
      'user',
      'assistant',
      'tool',
      'subtool',
    ])
    expect(t.records[3].parent).toBe(t.records[2].id)
    expect(t.requests[0].subtoolCalls).toBe(1)
  })
})

describe('rowsOf', () => {
  it('folds a turn to its first row and a summary', () => {
    const t = buildTrajectory(log(), false)
    const folds = none()
    folds.turns.add(1)
    const rows = rowsOf(t, folds, '')
    expect(rows[0]).toMatchObject({ kind: 'record' })
    expect(rows[1]).toMatchObject({
      kind: 'summary',
      text: '2 steps · 2 tool calls',
    })
    expect(rows[2]).toMatchObject({ kind: 'record' })
    expect(rows).toHaveLength(2 + 4)
  })

  it('folds the calls of an assistant into one summary row', () => {
    const t = buildTrajectory(log(), false)
    const folds = none()
    folds.calls.add(t.records[3].id)
    const rows = rowsOf(t, folds, '')
    expect(rows[4]).toMatchObject({
      kind: 'summary',
      text: '2 tool calls · Bash, Subagent',
    })
    expect(rows).toHaveLength(t.records.length - 1)
  })

  it('searches every record and ignores folds', () => {
    const t = buildTrajectory(log(), false)
    const folds = none()
    folds.turns.add(1)
    const rows = rowsOf(t, folds, 'BLOCKED')
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ record: { kind: 'tool' } })
  })
})

describe('foldKeys', () => {
  it('lists the turns, assistants and tools a button folds', () => {
    const t = buildTrajectory(log(), false)
    expect(foldKeys(t, 'turns')).toEqual([1, 2])
    expect(foldKeys(t, 'calls')).toEqual([t.records[3].id, t.records[8].id])
    expect(foldKeys(t, 'subcalls')).toEqual([])
  })
})

describe('spansOf', () => {
  it('gives each record one unit in sequence mode', () => {
    const t = buildTrajectory(log(), false)
    const { domain, spans } = spansOf(t.records, 'sequence')
    expect(domain).toBe(t.records.length)
    expect(spans.map((s) => s.lane)).toEqual([0, 0, 0, 1, 2, 2, 1, 0, 1, 2, 0])
  })

  it('cuts idle gaps out of duration mode', () => {
    const t = buildTrajectory(
      [
        event(1, 'task.created', { title: 'T' }),
        event(2, 'usage.reported', {}),
        event(3, 'tool.called', {
          call_id: 'a',
          duration_ms: 1000,
          tool: 'Bash',
        }),
        event(40, 'tool.called', {
          call_id: 'b',
          duration_ms: 1000,
          tool: 'Bash',
        }),
      ],
      false,
    )
    const { domain, spans } = spansOf(t.records, 'duration')
    expect(domain).toBe(3000)
    const b = spans.at(-1)!
    expect([b.start, b.end]).toEqual([2000, 3000])
  })
})

describe('helpers', () => {
  it('formats durations like DSH', () => {
    expect(formatDuration(412)).toBe('412 ms')
    expect(formatDuration(1250)).toBe('1.25 s')
    expect(formatDuration(12_400)).toBe('12.4 s')
  })

  it('previews Markdown on one line', () => {
    expect(preview('# Title\n\n[link](http://x) and `code`')).toBe(
      'Title link and code',
    )
    expect(preview('x'.repeat(600))).toHaveLength(513)
  })

  it('finds the record of a seq, or the one before it', () => {
    const t = buildTrajectory(log(), false)
    expect(recordForSeq(t.records, 4)?.kind).toBe('assistant')
    expect(recordForSeq(t.records, 99)?.kind).toBe('system')
  })
})
