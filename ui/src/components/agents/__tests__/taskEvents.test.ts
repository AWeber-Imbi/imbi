import { describe, expect, it } from 'vitest'

import {
  checksFrom,
  formatElapsed,
  groupTasks,
  phaseTimeline,
  requestsFrom,
  toolCalls,
} from '../taskEvents'
import { event, task } from './taskFixtures'

describe('groupTasks', () => {
  it('groups waiting tasks, paused too, oldest block first (O2)', () => {
    const groups = groupTasks([
      task({ short_id: 'T-6', status: 'queued' }),
      task({
        blocked_since: '2026-10-08T12:05:00Z',
        short_id: 'T-5',
        status: 'blocked',
      }),
      task({ short_id: 'T-4', status: 'paused' }),
      task({
        blocked_since: '2026-10-08T11:30:00Z',
        short_id: 'T-7',
        status: 'paused',
      }),
      task({
        blocked_since: '2026-10-08T11:00:00Z',
        short_id: 'T-3',
        status: 'blocked',
      }),
      task({ short_id: 'T-2', status: 'running' }),
      task({
        closed_at: '2026-10-08T10:00:00Z',
        short_id: 'T-1',
        status: 'closed',
      }),
      task({
        closed_at: '2026-10-08T13:00:00Z',
        short_id: 'T-0',
        status: 'closed',
      }),
    ])
    expect(
      groups.map((g) => [g.label, g.tasks.map((t) => t.short_id)]),
    ).toEqual([
      ['Human input required', ['T-3', 'T-7', 'T-5']],
      ['Running', ['T-4', 'T-2']],
      ['Queued', ['T-6']],
      ['Recently closed', ['T-0', 'T-1']],
    ])
  })

  it('leaves out empty groups', () => {
    expect(groupTasks([task()]).map((g) => g.id)).toEqual(['queued'])
  })
})

describe('requestsFrom', () => {
  const opened = (seq: number, id: string, extra = {}) =>
    event(seq, 'request.opened', {
      kind: 'feedback',
      options: ['yes', 'no'],
      request_id: id,
      title: `Ask ${id}`,
      ...extra,
    })

  it('folds opened, resolved, and expired requests', () => {
    const requests = requestsFrom(
      [
        opened(1, 'a'),
        opened(2, 'b'),
        opened(3, 'c', { expires_at: '2026-10-08T12:00:30Z' }),
        event(
          4,
          'request.resolved',
          {
            answer: 'yes',
            request_id: 'a',
            resolved_by: 'pat@example.com',
            status: 'answered',
          },
          { actor_kind: 'human' },
        ),
      ],
      Date.parse('2026-10-08T12:01:00Z'),
    )
    expect(
      requests.map((r) => [r.id, r.status, r.resolved_by, r.answer]),
    ).toEqual([
      ['a', 'answered', 'pat@example.com', 'yes'],
      ['b', 'open', null, null],
      ['c', 'expired', null, null],
    ])
    expect(requests[1].options).toEqual(['yes', 'no'])
  })
})

describe('toolCalls', () => {
  it('nests a call under the call_id of its parent, in seq order', () => {
    const rows = toolCalls([
      event(1, 'tool.called', { tool: 'read' }),
      event(2, 'tool.called', {
        parent_call_id: 'delegate',
        tool: 'sub.read',
      }),
      event(3, 'turn', { body: 'hi' }),
      event(4, 'tool.called', { call_id: 'delegate', tool: 'delegate' }),
      event(5, 'tool.called', {
        parent_call_id: event(1, 'x').event_id,
        tool: 'by-event-id',
      }),
      event(6, 'tool.called', { parent_call_id: 'gone', tool: 'orphan' }),
    ])
    expect(rows.map((r) => [r.event.payload.tool, r.depth])).toEqual([
      ['read', 0],
      ['delegate', 0],
      ['sub.read', 1],
      ['by-event-id', 0],
      ['orphan', 0],
    ])
  })
})

describe('phaseTimeline', () => {
  it('gives the time in each phase, the last up to the end', () => {
    const spans = phaseTimeline(
      [
        event(1, 'phase.changed', { phase: 'investigate' }),
        event(10, 'phase.changed', { phase: 'fix' }),
      ],
      Date.parse('2026-10-08T12:01:10Z'),
    )
    expect(spans.map((s) => [s.phase, formatElapsed(s.ms)])).toEqual([
      ['investigate', '9s'],
      ['fix', '1m'],
    ])
  })
})

describe('formatElapsed', () => {
  it('shows the two largest units', () => {
    expect(formatElapsed(552_000)).toBe('9m 12s')
    expect(formatElapsed(7_440_000)).toBe('2h 4m')
    expect(formatElapsed(266_400_000)).toBe('3d 2h')
    expect(formatElapsed(0)).toBe('0s')
  })
})

describe('checksFrom', () => {
  it('keeps the latest report of each check, in first-report order', () => {
    const checks = checksFrom([
      event(1, 'check.reported', { name: 'tests', verdict: 'fail' }),
      event(2, 'turn', { body: 'Fixing.' }),
      event(3, 'check.reported', { name: 'p95', verdict: 'pass' }),
      event(4, 'check.reported', { name: 'tests', verdict: 'pass' }),
    ])
    expect(checks.map((e) => [e.payload.name, e.seq])).toEqual([
      ['tests', 4],
      ['p95', 3],
    ])
  })
})
