import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { AgentTask } from '@/types'

import { StatisticsTab } from '../StatisticsTab'
import { taskStatistics } from '../statsModel'
import {
  buildTrajectory,
  type Trajectory,
  type TrajectoryRecord,
} from '../trajectoryModel'
import { event, task } from './taskFixtures'

const LOG = [
  event(1, 'task.created', { description: 'Check', title: 'T' }),
  event(2, 'usage.reported', {
    cache_read_tokens: 0,
    cache_write_tokens: 900,
    tokens_in: 100,
    tokens_out: 100,
  }),
  event(5, 'tool.called', {
    arguments: { command: 'ls' },
    call_id: 'c1',
    duration_ms: 2000,
    result: 'ok',
    tool: 'Bash',
  }),
  event(6, 'usage.reported', {
    cache_read_tokens: 900,
    cache_write_tokens: 200,
    tokens_in: 100,
    tokens_out: 10,
  }),
  event(7, 'turn', { body: 'All done' }),
]

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
      endedAt: 2000,
      id: 'a1',
      kind: 'assistant',
      request: 1,
      startedAt: 0,
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
      endedAt: 4000,
      id: 'a2',
      kind: 'assistant',
      request: 2,
      startedAt: 3000,
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
  subrequests: [],
  turns: [{ first: 'u', number: 1, steps: 2, toolCalls: 1 }],
}

/**
 * The main agent (prompts of 1000 then 1100) runs a subagent whose two
 * model requests have prompts of 60 and 80.
 */
function subagentLog(withIds: boolean) {
  const id = (message_id: string) => (withIds ? { message_id } : {})
  const usage = (tokens_in: number, message_id: string) =>
    ({ tokens_in, tokens_out: 5, ...id(message_id) }) as Record<string, unknown>
  return [
    event(1, 'task.created', { description: 'Review', title: 'T' }),
    event(2, 'usage.reported', usage(1000, 'm1')),
    event(3, 'usage.reported', usage(60, 's1')),
    event(4, 'turn', { body: 'Asking', kind: 'text', ...id('m1') }),
    event(5, 'tool.called', {
      call_id: 'r1',
      parent_call_id: 'c1',
      tool: 'Read',
      ...id('s1'),
    }),
    event(6, 'usage.reported', usage(80, 's2')),
    event(7, 'turn', {
      body: 'Fine',
      kind: 'text',
      parent_call_id: 'c1',
      ...id('s2'),
    }),
    event(8, 'tool.called', { call_id: 'c1', tool: 'Agent', ...id('m1') }),
    event(9, 'usage.reported', usage(1100, 'm2')),
    event(10, 'turn', { body: 'Done', kind: 'text', ...id('m2') }),
  ]
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

  it('measures model time from the model, not its tool calls', () => {
    const trajectory = buildTrajectory(LOG, false)
    const { totals, turns } = taskStatistics(t, trajectory, 'latest')
    expect(turns[0].steps.map((s) => s.modelMs)).toEqual([1000, 1000])
    expect(turns[0].steps[0].toolMs).toBe(2000)
    expect(totals.modelMs).toBe(2000)
    expect(totals.toolMs).toBe(2000)
    expect(turns[0].steps[0].outputPerSecond).toBe(100)
  })

  it('leaves a request with no measured prompt out of the context', () => {
    const trajectory = buildTrajectory(
      [...LOG, event(8, 'usage.reported', { tokens_in: null, tokens_out: 5 })],
      false,
    )
    const { turns } = taskStatistics(t, trajectory, 'latest')
    const last = turns[0].steps[turns[0].steps.length - 1]
    expect(last.context).toBeNull()
    expect(last.contextDelta).toBeNull()
    expect(turns[0].context).toBe(1200)
  })

  it('takes the cache share on the same basis as the context', () => {
    expect(
      taskStatistics(t, TRAJECTORY, 'latest').turns[0].cacheHit,
    ).toBeCloseTo(0.75)
    expect(
      taskStatistics(t, TRAJECTORY, 'cumulative').turns[0].cacheHit,
    ).toBeCloseTo(900 / 2200)
  })

  it('shows an automation trigger as its source', () => {
    const hook = task({ origin: { kind: 'webhook' } }) as unknown as AgentTask
    expect(taskStatistics(hook, TRAJECTORY, 'latest').turns[0].trigger).toEqual(
      { badge: true, text: 'Webhook' },
    )
  })

  it('keeps subagent requests out of the steps and the context', () => {
    const trajectory = buildTrajectory(subagentLog(true), false)
    const { totals, turns } = taskStatistics(t, trajectory, 'latest')
    const steps = turns[0].steps
    expect(steps.map((s) => [s.context, s.contextDelta])).toEqual([
      [1000, null],
      [1100, 100],
    ])
    expect(steps[0].did).toBe('Subagent · 2 subagent requests')
    expect(turns[0].context).toBe(1100)
    expect(totals.steps).toBe(2)
    expect(totals.subrequests).toBe(2)
  })

  it('counts usage without a message id as steps, as before', () => {
    const trajectory = buildTrajectory(subagentLog(false), false)
    const { totals, turns } = taskStatistics(t, trajectory, 'latest')
    expect(turns[0].steps.map((s) => s.context)).toEqual([1000, 60, 80, 1100])
    expect(totals.steps).toBe(4)
    expect(totals.subrequests).toBe(0)
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
    expect(screen.getByText('No activity yet')).toBeInTheDocument()
    expect(screen.getByText('No model requests yet.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Clear search' })).toBeNull()
  })

  it('says when nothing matches and clears the search', async () => {
    const user = userEvent.setup()
    const t = task({ status: 'closed' }) as unknown as AgentTask
    render(
      <div className="flex h-150 flex-col">
        <StatisticsTab events={LOG} task={t} />
      </div>,
    )
    const search = screen.getByRole('searchbox', { name: 'Search statistics' })
    await user.type(search, 'zzqx-no-match')
    expect(screen.queryByRole('table')).toBeNull()
    expect(screen.getByText('No matches')).toBeInTheDocument()
    expect(
      screen.getByText('Nothing in this view matches “zzqx-no-match”.'),
    ).toBeInTheDocument()
    const empty = screen
      .getByText('No matches')
      .closest('[data-slot="empty"]') as HTMLElement
    expect(empty).toHaveAttribute('data-search-skip')
    await user.click(
      within(empty).getByRole('button', { name: 'Clear search' }),
    )
    expect(search).toHaveValue('')
    expect(screen.getByRole('table')).toBeInTheDocument()
  })

  it('opens the only turn once its events load', () => {
    const t = task({ status: 'closed' }) as unknown as AgentTask
    const view = render(
      <div className="flex h-150 flex-col">
        <StatisticsTab events={[]} task={t} />
      </div>,
    )
    view.rerender(
      <div className="flex h-150 flex-col">
        <StatisticsTab events={LOG} task={t} />
      </div>,
    )
    expect(screen.getByText('All done')).toBeInTheDocument()
  })
})
