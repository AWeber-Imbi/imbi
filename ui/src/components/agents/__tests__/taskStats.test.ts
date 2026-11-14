import { describe, expect, it } from 'vitest'

import { taskActivity, taskUsage } from '../taskStats'
import {
  buildTrajectory,
  type Trajectory,
  type TrajectoryRecord,
} from '../trajectoryModel'
import { event } from './taskFixtures'

function record(
  kind: TrajectoryRecord['kind'],
  startedAt: number,
  endedAt: number,
  error = false,
): TrajectoryRecord {
  return {
    body: { reply: '', thinking: '' },
    endedAt,
    error,
    events: [],
    id: `${kind}-${startedAt}`,
    kind,
    parent: null,
    request: null,
    seqs: [],
    startedAt,
    step: null,
    text: '',
    tool: null,
    turn: 1,
  }
}

describe('taskUsage', () => {
  it('adds up token buckets, cost and cache hit by model', () => {
    const u = taskUsage([
      event(1, 'usage.reported', {
        cache_read_tokens: 600,
        cache_write_tokens: 100,
        cost: '0.10',
        model_id: 'sonnet',
        tokens_in: 300,
        tokens_out: 50,
      }),
      event(2, 'usage.reported', {
        cost: '0.02',
        model_id: 'haiku',
        tokens_in: 100,
        tokens_out: 10,
      }),
    ])
    expect(u.input).toBe(400)
    expect(u.cacheRead).toBe(600)
    expect(u.output).toBe(60)
    expect(u.total).toBe(1160)
    expect(u.cacheHit).toBeCloseTo(600 / 1100)
    expect(u.cost).toBeCloseTo(0.12)
    expect(u.models.map((m) => m.model)).toEqual(['sonnet', 'haiku'])
  })

  it('leaves cost unknown when no report is priced', () => {
    const u = taskUsage([
      event(1, 'usage.reported', { model_id: 'x', tokens_in: 5 }),
    ])
    expect(u.cost).toBeNull()
  })
})

describe('taskActivity', () => {
  it('times model requests and tool calls', () => {
    const trajectory = {
      records: [
        record('assistant', 0, 2000),
        record('tool', 2000, 3000),
        record('tool', 3000, 3500, true),
        record('subtool', 3100, 3200),
      ],
      requests: [
        {
          assistant: '',
          endedAt: 2000,
          number: 1,
          startedAt: 0,
          status: 'completed',
          step: 1,
          subtoolCalls: 0,
          toolCalls: 2,
          turn: 1,
          usage: null,
        },
      ],
      subrequests: [],
      turns: [{ first: '', number: 1, steps: 1, toolCalls: 2 }],
    } satisfies Trajectory
    const a = taskActivity(trajectory, 100)
    expect(a.modelMs).toBe(2000)
    expect(a.toolMs).toBe(1500)
    expect(a.toolCalls).toBe(2)
    expect(a.failedCalls).toBe(1)
    expect(a.wallMs).toBe(3500)
    expect(a.outputPerSecond).toBe(50)
  })

  it('leaves tool time out of model time', () => {
    const trajectory = buildTrajectory(
      [
        event(1, 'task.created', { title: 'T' }),
        event(2, 'usage.reported', { tokens_in: 1, tokens_out: 100 }),
        event(5, 'tool.called', {
          arguments: { command: 'ls' },
          call_id: 'c1',
          duration_ms: 2000,
          result: 'ok',
          tool: 'Bash',
        }),
        event(6, 'usage.reported', { tokens_in: 1, tokens_out: 100 }),
        event(7, 'turn', { body: 'done' }),
      ],
      false,
    )
    const a = taskActivity(trajectory, 200)
    expect(a.modelMs).toBe(2000)
    expect(a.toolMs).toBe(2000)
    expect(a.outputPerSecond).toBe(100)
  })

  it('counts the model requests of subagents', () => {
    const trajectory = buildTrajectory(
      [
        event(1, 'task.created', { title: 'T' }),
        event(2, 'usage.reported', { message_id: 'm1', tokens_in: 1 }),
        event(3, 'usage.reported', { message_id: 's1', tokens_in: 1 }),
        event(4, 'tool.called', {
          call_id: 'r1',
          message_id: 's1',
          parent_call_id: 'c1',
          tool: 'Read',
        }),
        event(5, 'tool.called', {
          call_id: 'c1',
          message_id: 'm1',
          tool: 'Agent',
        }),
      ],
      false,
    )
    expect(trajectory.requests).toHaveLength(1)
    expect(taskActivity(trajectory, 0).requests).toBe(2)
  })
})
