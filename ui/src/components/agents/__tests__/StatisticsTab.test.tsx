import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { AgentTask } from '@/types'

import { StatisticsTab } from '../StatisticsTab'
import { taskStatistics } from '../statsModel'
import type { Trajectory, TrajectoryRecord } from '../trajectoryModel'
import { event, task } from './taskFixtures'

function record(
  over: Partial<TrajectoryRecord> & Pick<TrajectoryRecord, 'id' | 'kind'>,
): TrajectoryRecord {
  return {
    body: { reply: '', thinking: '' },
    endedAt: null,
    error: false,
    events: [],
    parent: null,
    request: null,
    seqs: [],
    startedAt: null,
    step: null,
    text: '',
    tool: null,
    turn: 1,
    ...over,
  }
}

function request(
  number: number,
  startedAt: number,
  endedAt: number,
  usage: Record<string, unknown>,
) {
  return {
    assistant: `a${number}`,
    endedAt,
    number,
    startedAt,
    status: 'completed' as const,
    step: number,
    subtoolCalls: 0,
    toolCalls: 0,
    turn: 1,
    usage: event(number, 'usage.reported', usage),
  }
}

const TRAJECTORY: Trajectory = {
  records: [
    record({ id: 'u', kind: 'user', text: 'Fix the build' }),
    record({
      body: { reply: 'Looking.', thinking: '' },
      id: 'a1',
      kind: 'assistant',
    }),
    record({
      endedAt: 3000,
      id: 't1',
      kind: 'tool',
      request: 1,
      startedAt: 2000,
      tool: {
        args: '',
        arguments: {},
        callId: null,
        name: 'Bash',
        result: '',
        resultValue: null,
        tool: 'Bash',
      },
    }),
    record({
      body: { reply: 'Done.', thinking: '' },
      id: 'a2',
      kind: 'assistant',
    }),
  ],
  requests: [
    request(1, 0, 2000, {
      cache_read_tokens: 0,
      cache_write_tokens: 900,
      tokens_in: 100,
      tokens_out: 40,
    }),
    request(2, 3000, 4000, {
      cache_read_tokens: 900,
      cache_write_tokens: 200,
      tokens_in: 100,
      tokens_out: 60,
    }),
  ],
  turns: [{ first: 'u', number: 1, steps: 2, toolCalls: 1 }],
}

describe('taskStatistics', () => {
  const t = task({ origin: { kind: 'human' } }) as unknown as AgentTask

  it('builds steps with context, cache hit, times and tools', () => {
    const { turns } = taskStatistics(t, TRAJECTORY, 'latest')
    const [one, two] = turns[0].steps
    expect(one.context).toBe(1000)
    expect(one.did).toBe('Bash')
    expect(one.toolMs).toBe(1000)
    expect(one.totalMs).toBe(3000)
    expect(two.context).toBe(1200)
    expect(two.contextDelta).toBe(200)
    expect(two.cacheHit).toBeCloseTo(0.75)
    expect(two.did).toBe('Done.')
    expect(turns[0].trigger).toEqual({ badge: false, text: 'Fix the build' })
  })

  it('switches the turn context between latest and cumulative', () => {
    expect(taskStatistics(t, TRAJECTORY, 'latest').turns[0].context).toBe(1200)
    expect(taskStatistics(t, TRAJECTORY, 'cumulative').turns[0].context).toBe(
      2200,
    )
  })

  it('totals model and tool time for the task', () => {
    const { totals } = taskStatistics(t, TRAJECTORY, 'latest')
    expect(totals.steps).toBe(2)
    expect(totals.output).toBe(100)
    expect(totals.totalMs).toBe(4000)
  })

  it('shows an automation trigger as its source', () => {
    const hook = task({ origin: { kind: 'webhook' } }) as unknown as AgentTask
    expect(taskStatistics(hook, TRAJECTORY, 'latest').turns[0].trigger).toEqual(
      { badge: true, text: 'Webhook' },
    )
  })
})

describe('StatisticsTab', () => {
  it('says when there are no model requests', () => {
    const t = task({ status: 'closed' }) as unknown as AgentTask
    render(
      <div className="flex h-150 flex-col">
        <StatisticsTab events={[]} task={t} />
      </div>,
    )
    expect(screen.getByText('No model requests yet.')).toBeInTheDocument()
  })
})
