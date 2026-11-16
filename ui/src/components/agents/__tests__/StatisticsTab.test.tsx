import {
  act,
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { AgentTask } from '@/types'

import { StatisticsTab } from '../StatisticsTab'
import { taskStatistics } from '../statsModel'
import {
  buildTrajectory,
  type Trajectory,
  type TrajectoryRecord,
} from '../trajectoryModel'
import { event, task } from './taskFixtures'
import {
  captureHighlights,
  findStub,
  layout,
  scrollPane,
  tableHeight,
} from './virtualLayout'

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

const TWO_TURNS = [
  ...LOG,
  event(
    8,
    'turn',
    { body: 'now test it' },
    { actor_id: 'dev', actor_kind: 'human' },
  ),
  event(9, 'usage.reported', { tokens_in: 1300, tokens_out: 20 }),
  event(10, 'turn', { body: 'Tested' }),
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

  it('times the task total on the clock when tools run in parallel', () => {
    const parallel: Trajectory = {
      ...TRAJECTORY,
      records: [...TRAJECTORY.records, { ...TRAJECTORY.records[2], id: 't2' }],
    }
    const { totals, turns } = taskStatistics(t, parallel, 'latest')
    expect(totals.toolMs).toBe(2000)
    expect(turns[0].totalMs).toBe(4000)
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

  it('counts subagent tokens in the task total, not its context', () => {
    const trajectory = buildTrajectory(subagentLog(true), false)
    const { totals } = taskStatistics(t, trajectory, 'latest')
    expect(totals.output).toBe(20)
    expect(totals.input).toBe(2240)
    expect(totals.context).toBe(2100)
  })

  it('times only main-agent output in the task total speed', () => {
    const trajectory = buildTrajectory(subagentLog(true), false)
    const { totals, turns } = taskStatistics(t, trajectory, 'latest')
    const main = turns
      .flatMap((turn) => turn.steps)
      .reduce((n, s) => n + s.output, 0)
    expect(totals.output).toBeGreaterThan(main)
    expect(totals.outputPerSecond).toBeCloseTo(main / (totals.modelMs / 1000))
  })

  it('counts usage without a message id as steps, as before', () => {
    const trajectory = buildTrajectory(subagentLog(false), false)
    const { totals, turns } = taskStatistics(t, trajectory, 'latest')
    expect(turns[0].steps.map((s) => s.context)).toEqual([1000, 60, 80, 1100])
    expect(totals.steps).toBe(4)
    expect(totals.subrequests).toBe(0)
  })

  it('points each turn at its first event for the conversation', () => {
    const trajectory = buildTrajectory(TWO_TURNS, false)
    const { turns } = taskStatistics(t, trajectory, 'latest')
    expect(turns.map((turn) => [turn.number, turn.seq])).toEqual([
      [1, 1],
      [2, 8],
    ])
  })

  it('points a turn that only reported usage at that usage', () => {
    const { turns } = taskStatistics(t, TRAJECTORY, 'latest')
    expect(turns[0].seq).toBe(1)
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

  it('keeps the step count of a turn while a search hides steps', async () => {
    const user = userEvent.setup()
    const t = task({ status: 'closed' }) as unknown as AgentTask
    render(
      <div className="flex h-150 flex-col">
        <StatisticsTab events={LOG} task={t} />
      </div>,
    )
    const search = screen.getByRole('searchbox', { name: 'Search statistics' })
    await user.type(search, 'All done')
    const turn = screen.getByRole('button', {
      name: 'Turn 1: its 2 steps, open while searching',
    })
    expect(turn).toHaveTextContent(/· 1 of 2 steps$/)
    await user.clear(search)
    expect(screen.getByRole('button', { name: /^Turn 1: / })).toHaveTextContent(
      /· 2 steps$/,
    )
  })

  it('leaves the turn folds alone while searching', async () => {
    const user = userEvent.setup()
    const t = task({ status: 'closed' }) as unknown as AgentTask
    render(
      <div className="flex h-150 flex-col">
        <StatisticsTab events={LOG} task={t} />
      </div>,
    )
    const search = screen.getByRole('searchbox', { name: 'Search statistics' })
    await user.type(search, 'All done')
    const turn = screen.getByRole('button', { name: /^Turn 1: / })
    expect(turn).toBeDisabled()
    await user.click(turn.closest('tr') as HTMLElement)
    await user.clear(search)
    expect(
      screen.getByRole('button', { name: 'Turn 1: hide its 2 steps' }),
    ).toHaveAttribute('aria-expanded', 'true')
  })

  it('says the task total speed is the main agent only', () => {
    const t = task({ status: 'closed' }) as unknown as AgentTask
    render(
      <div className="flex h-150 flex-col">
        <StatisticsTab events={subagentLog(true)} task={t} />
      </div>,
    )
    const footer = screen.getByText('Task total').closest('tr') as HTMLElement
    expect(
      within(footer).getByTitle(/^Main-agent output tokens per second/),
    ).toBeInTheDocument()
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

  it('shows a turn in the conversation without folding it', async () => {
    const user = userEvent.setup()
    const onShow = vi.fn()
    const t = task({ status: 'closed' }) as unknown as AgentTask
    render(
      <div className="flex h-150 flex-col">
        <StatisticsTab
          events={TWO_TURNS}
          onShowInConversation={onShow}
          task={t}
        />
      </div>,
    )
    const fold = screen.getByRole('button', { name: /^Turn 2: show its/ })
    await user.click(
      screen.getByRole('button', { name: 'Turn 2: show in conversation' }),
    )
    expect(onShow).toHaveBeenCalledExactlyOnceWith(8)
    expect(fold).toHaveAttribute('aria-expanded', 'false')
    await user.click(
      screen.getByRole('button', { name: 'Turn 1: show in conversation' }),
    )
    expect(onShow).toHaveBeenLastCalledWith(1)
    await user.click(fold)
    expect(fold).toHaveAttribute('aria-expanded', 'true')
  })

  it('names the button in a tooltip', async () => {
    const user = userEvent.setup()
    const t = task({ status: 'closed' }) as unknown as AgentTask
    render(
      <div className="flex h-150 flex-col">
        <StatisticsTab events={LOG} onShowInConversation={vi.fn()} task={t} />
      </div>,
    )
    await user.hover(
      screen.getByRole('button', { name: 'Turn 1: show in conversation' }),
    )
    expect(await screen.findByRole('tooltip')).toHaveTextContent(
      'Show in conversation',
    )
  })

  it('leaves the button out without a conversation to show', () => {
    const t = task({ status: 'closed' }) as unknown as AgentTask
    render(
      <div className="flex h-150 flex-col">
        <StatisticsTab events={LOG} task={t} />
      </div>,
    )
    expect(
      screen.queryByRole('button', { name: /show in conversation/ }),
    ).toBeNull()
  })
})

describe('StatisticsTab with many turns', () => {
  const MANY = [
    event(1, 'task.created', { description: 'Check', title: 'T' }),
    ...Array.from({ length: 100 }, (_, i) => [
      event(
        2 + i * 3,
        'turn',
        { body: `ask ${i}` },
        { actor_id: 'dev', actor_kind: 'human' },
      ),
      event(3 + i * 3, 'usage.reported', { tokens_in: 100, tokens_out: 10 }),
      event(4 + i * 3, 'turn', { body: `answer ${i}` }),
    ]).flat(),
  ]
  const isPane = (el: HTMLElement) => !!el.querySelector(':scope > div > table')
  const pane = () => screen.getByRole('table').parentElement!.parentElement!
  const t = task({ status: 'closed' }) as unknown as AgentTask
  let spy: ReturnType<typeof layout>
  beforeEach(() => {
    spy = layout({
      content: tableHeight(37),
      isPane,
      pane: 370,
      row: 37,
    })
  })
  afterEach(() => {
    cleanup()
    spy.mockRestore()
    vi.unstubAllGlobals()
  })

  it('renders only the turns in view and counts them all', () => {
    render(<StatisticsTab events={MANY} task={t} />)
    expect(screen.getByRole('table')).toHaveAttribute('aria-rowcount', '102')
    const turns = screen.getAllByRole('button', { name: /^Turn \d+: show/ })
    expect(turns.length).toBeLessThan(40)
    expect(screen.getByText('Task total')).toBeInTheDocument()
  })

  it('numbers the rows it renders for screen readers', async () => {
    render(<StatisticsTab events={MANY} task={t} />)
    const all = () => within(screen.getByRole('table')).getAllByRole('row')
    expect(all()[0]).toHaveAttribute('aria-rowindex', '1')
    expect(all().at(-1)).toHaveAttribute('aria-rowindex', '102')
    scrollPane(pane(), 37 * 60)
    await waitFor(() =>
      expect(Number(all()[1].getAttribute('aria-rowindex'))).toBeGreaterThan(
        40,
      ),
    )
    const indexes = all().map((r) => Number(r.getAttribute('aria-rowindex')))
    expect(indexes.every((n, i) => i === 0 || n > indexes[i - 1])).toBe(true)
  })

  it('shows a far turn in the conversation', async () => {
    const user = userEvent.setup()
    const onShow = vi.fn()
    render(
      <StatisticsTab events={MANY} onShowInConversation={onShow} task={t} />,
    )
    const { turns } = taskStatistics(t, buildTrajectory(MANY, false), 'latest')
    const last = turns[turns.length - 1]
    const name = `Turn ${last.number}: show in conversation`
    expect(screen.queryByRole('button', { name })).toBeNull()
    scrollPane(pane(), 100 * 37)
    await user.click(await screen.findByRole('button', { name }))
    expect(onShow).toHaveBeenCalledExactlyOnceWith(last.seq)
  })

  it('keeps the focused turn while it scrolls out of view', async () => {
    render(<StatisticsTab events={MANY} task={t} />)
    const [first] = screen.getAllByRole('button', {
      name: /^Turn \d+: show its/,
    })
    first.focus()
    scrollPane(pane(), 100 * 37)
    await screen.findByRole('button', { name: /^Turn 101: show/ })
    expect(first).toBeInTheDocument()
    expect(document.activeElement).toBe(first)
    await userEvent.keyboard('{Enter}')
    expect(first).toHaveAttribute('aria-expanded', 'true')
  })

  it('filters every turn from the data and marks what renders', async () => {
    const { marked, mutate } = captureHighlights()
    const user = userEvent.setup()
    render(<StatisticsTab events={MANY} task={t} />)
    await user.type(
      screen.getByRole('searchbox', { name: 'Search statistics' }),
      'answer 7',
    )
    expect(screen.getByRole('table')).toHaveAttribute('aria-rowcount', '24')
    scrollPane(pane(), 0)
    mutate()
    await waitFor(() => expect(marked.current).toContain('answer 7'))
    expect(marked.current).not.toContain('answer 79')
    scrollPane(pane(), 24 * 37)
    mutate()
    await waitFor(() => expect(marked.current).toContain('answer 79'))
    expect(marked.current).not.toContain('answer 7')
  })

  it('keeps its column widths fixed as rows mount', () => {
    render(<StatisticsTab events={MANY} task={t} />)
    const table = screen.getByRole('table')
    expect(table).toHaveClass('table-fixed')
    const cols = [...table.querySelectorAll<HTMLElement>('colgroup > col')]
    expect(cols).toHaveLength(9)
    expect(cols.filter((c) => c.style.width !== '')).toHaveLength(8)
  })

  it('lets the browser find a turn out of view and scrolls to it', async () => {
    render(<StatisticsTab events={MANY} task={t} />)
    const stub = findStub('ask 90')
    expect(stub).toHaveAttribute('hidden', 'until-found')
    expect(screen.queryByText('ask 90')).toBeNull()
    act(() => {
      stub.dispatchEvent(new Event('beforematch'))
    })
    expect(await screen.findByText('ask 90')).toBeInTheDocument()
  })

  it('lets the browser find a number a row out of view shows', () => {
    const events = MANY.map((e) =>
      e.seq === 3 + 90 * 3
        ? event(e.seq, 'usage.reported', { tokens_in: 987654, tokens_out: 10 })
        : e,
    )
    render(<StatisticsTab events={events} task={t} />)
    expect(screen.queryByText('ask 90')).toBeNull()
    expect(findStub('988k')).toBe(findStub('ask 90'))
  })

  it('lets the browser find a context change a row out of view shows', async () => {
    const user = userEvent.setup()
    const events = MANY.map((e) =>
      e.seq === 3 + 90 * 3
        ? event(e.seq, 'usage.reported', { tokens_in: 987654, tokens_out: 10 })
        : e,
    )
    render(<StatisticsTab events={events} task={t} />)
    expect(findStub('ask 90').textContent).not.toContain('988k+988k')
    await user.click(
      screen.getByRole('button', { name: 'Show context change' }),
    )
    expect(screen.queryByText('ask 90')).toBeNull()
    expect(findStub('ask 90').textContent).toContain('988k+988k')
    expect(findStub('ask 91').textContent).toContain('100−988k')
  })

  it('cuts off a value too long for its column with an ellipsis', () => {
    render(<StatisticsTab events={MANY} task={t} />)
    const [first] = screen.getAllByRole('button', {
      name: /^Turn \d+: show its/,
    })
    const turn = first.closest('tr')!
    const total = screen.getByText('Task total').closest('tr')!
    for (const row of [turn, total])
      for (const cell of [...row.cells].slice(0, -1))
        expect(
          cell.classList.contains('truncate') ||
            cell.querySelector('.truncate') !== null,
        ).toBe(true)
  })
})
