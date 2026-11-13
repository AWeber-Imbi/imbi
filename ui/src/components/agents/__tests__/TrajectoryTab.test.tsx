import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fireEvent, render, screen, within } from '@/test/utils'
import type { AgentTask } from '@/types'

import { focusedBy, totalText } from '../TrajectoryOverview'
import { TrajectoryTab } from '../TrajectoryTab'
import { DURATION_KEY } from '../TrajectoryToolbar'
import { event, task } from './taskFixtures'

const LOG = [
  event(1, 'task.created', { description: 'Check the release', title: 'T' }),
  event(2, 'session.opened', { session_id: 's' }),
  event(3, 'usage.reported', { tokens_in: 2, tokens_out: 9 }),
  event(4, 'turn', { body: 'Looking at releases', kind: 'thinking' }),
  event(5, 'tool.called', {
    arguments: { command: 'ls' },
    call_id: 'c1',
    duration_ms: 500,
    result: 'a.txt',
    tool: 'Bash',
  }),
  event(6, 'tool.called', {
    arguments: { pattern: 'x' },
    call_id: 'c2',
    duration_ms: 20,
    is_error: true,
    result: 'denied',
    tool: 'Grep',
  }),
  event(7, 'usage.reported', { tokens_in: 2, tokens_out: 30 }),
  event(8, 'turn', { body: 'All done.', kind: 'text' }),
  event(
    9,
    'turn',
    { body: 'Also check prod' },
    { actor_id: 'dev', actor_kind: 'human' },
  ),
  event(10, 'usage.reported', { tokens_in: 2, tokens_out: 5 }),
  event(11, 'tool.called', {
    arguments: { command: 'pwd' },
    call_id: 'c3',
    duration_ms: 5,
    result: '',
    tool: 'Bash',
  }),
]

function renderTab(status: AgentTask['status'] = 'closed', events = LOG) {
  const t = task({ status }) as unknown as AgentTask
  return render(
    <div className="flex h-150 flex-col">
      <TrajectoryTab events={events} task={t} />
    </div>,
  )
}

function rows() {
  return within(screen.getByRole('grid', { name: 'Trajectory' })).getAllByRole(
    'row',
  )
}

beforeEach(() => {
  window.history.replaceState(null, '', '/agents/tasks/acme/T-1/trajectory')
})

describe('TrajectoryTab ledger', () => {
  it('shows one row per record with its kind tag', () => {
    renderTab()
    expect(rows().map((r) => r.dataset.kind)).toEqual([
      'user',
      'system',
      'assistant',
      'tool',
      'tool',
      'assistant',
      'user',
      'assistant',
      'tool',
    ])
    expect(within(rows()[0]).getByText('USER')).toBeInTheDocument()
    expect(within(rows()[0]).getByText('Check the release')).toBeInTheDocument()
  })

  it('shows a tool as name, args, an arrow and the result', () => {
    renderTab()
    const bash = rows()[3]
    expect(within(bash).getByText('Bash')).toBeInTheDocument()
    expect(within(bash).getByText('ls')).toBeInTheDocument()
    expect(within(bash).getByText('→')).toBeInTheDocument()
    expect(within(bash).getByText('a.txt')).toBeInTheDocument()
    expect(within(rows()[8]).getByText('No output')).toBeInTheDocument()
    expect(rows()[4]).toHaveAttribute('data-error', 'true')
  })

  it('labels turn starts and tool-only requests', () => {
    renderTab()
    expect(within(rows()[0]).getByText('Turn 1')).toBeInTheDocument()
    expect(within(rows()[6]).getByText('Turn 2')).toBeInTheDocument()
    expect(rows()[6]).toHaveAttribute('data-turn-start', 'true')
    expect(within(rows()[7]).getByText('(tool call only)')).toBeInTheDocument()
  })

  it('puts a request dot on each assistant row', () => {
    renderTab()
    expect(
      within(rows()[2]).getByRole('button', { name: 'Request #1' }),
    ).toBeInTheDocument()
    expect(
      within(rows()[7]).getByRole('button', { name: 'Request #3' }),
    ).toBeInTheDocument()
  })

  it('selects a row on click and on Enter, and links it', async () => {
    renderTab()
    await userEvent.click(rows()[3])
    expect(rows()[3]).toHaveAttribute('aria-selected', 'true')
    expect(window.location.hash).toBe('#e5')
    rows()[5].focus()
    await userEvent.keyboard('{Enter}')
    expect(rows()[5]).toHaveAttribute('aria-selected', 'true')
    expect(rows()[3]).toHaveAttribute('aria-selected', 'false')
  })

  it('folds and unfolds the calls of an assistant on double-click', async () => {
    renderTab()
    await userEvent.dblClick(rows()[2])
    const summary = rows()[3]
    expect(summary).toHaveTextContent('2 tool calls · Bash, Grep')
    expect(rows()).toHaveLength(8)
    await userEvent.click(summary)
    expect(rows()).toHaveLength(9)
  })

  it('folds a turn on double-click of its first row', async () => {
    renderTab()
    await userEvent.dblClick(rows()[0])
    expect(rows()[1]).toHaveTextContent('2 steps · 2 tool calls')
    expect(rows()).toHaveLength(2 + 3)
  })

  it('selects the record of a #e link, falling back to the one before', () => {
    window.history.replaceState(
      null,
      '',
      '/agents/tasks/acme/T-1/trajectory#e4',
    )
    renderTab()
    expect(rows()[2]).toHaveAttribute('aria-selected', 'true')
  })
})

describe('TrajectoryTab toolbar', () => {
  it('collapses and expands every turn with one button', async () => {
    renderTab()
    await userEvent.click(
      screen.getByRole('button', { name: 'Collapse turns' }),
    )
    expect(rows()).toHaveLength(4)
    expect(
      screen.getByRole('button', { name: 'Expand turns' }),
    ).toHaveTextContent('⊞')
    await userEvent.click(screen.getByRole('button', { name: 'Expand turns' }))
    expect(rows()).toHaveLength(9)
  })

  it('folds the calls under every assistant', async () => {
    renderTab()
    await userEvent.click(
      screen.getByRole('button', { name: 'Collapse calls' }),
    )
    expect(rows()).toHaveLength(8)
    expect(rows()[3]).toHaveTextContent('2 tool calls · Bash, Grep')
    expect(rows()[7]).toHaveTextContent('1 tool call · Bash')
  })

  it('disables a fold button with nothing to fold', () => {
    renderTab()
    expect(
      screen.getByRole('button', { name: 'Collapse subcalls' }),
    ).toBeDisabled()
  })

  it('searches every record and ignores folds', async () => {
    renderTab()
    await userEvent.click(
      screen.getByRole('button', { name: 'Collapse turns' }),
    )
    await userEvent.type(
      screen.getByRole('searchbox', { name: 'Search trajectory' }),
      'denied',
    )
    expect(rows()).toHaveLength(1)
    expect(rows()[0]).toHaveTextContent('Grep')
  })

  it('keeps the Duration toggle in the browser', async () => {
    renderTab()
    const toggle = screen.getByRole('button', { name: 'Duration' })
    expect(toggle).toHaveAttribute('aria-pressed', 'false')
    await userEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-pressed', 'true')
    expect(vi.mocked(window.localStorage.setItem)).toHaveBeenCalledWith(
      DURATION_KEY,
      'true',
    )
  })
})

function spanBars() {
  return [...track().querySelectorAll<HTMLElement>('[data-span]')]
}

function track() {
  return screen.getByRole('application', { name: 'Timing overview' })
}

describe('TrajectoryTab overview', () => {
  it('draws one span per record in three lanes', () => {
    renderTab()
    expect(screen.getByText('Input')).toBeInTheDocument()
    expect(screen.getByText('Model')).toBeInTheDocument()
    expect(screen.getByText('Tools')).toBeInTheDocument()
    expect(spanBars()).toHaveLength(9)
    expect(spanBars().map((s) => s.style.top)).toEqual([
      '0px',
      '0px',
      '14px',
      '28px',
      '28px',
      '14px',
      '0px',
      '14px',
      '28px',
    ])
  })

  it('selects a record when its span is clicked', () => {
    renderTab()
    const bar = spanBars()[3]
    fireEvent.pointerDown(bar, { button: 0, clientX: 10 })
    fireEvent.pointerUp(bar, { button: 0, clientX: 10 })
    expect(rows()[3]).toHaveAttribute('aria-selected', 'true')
    expect(spanBars()[3]).toHaveAttribute('data-current', 'true')
  })

  it('focuses the ledger on a dragged range, and Escape clears it', () => {
    renderTab()
    vi.spyOn(track(), 'getBoundingClientRect').mockReturnValue({
      bottom: 50,
      height: 50,
      left: 0,
      right: 900,
      toJSON: () => ({}),
      top: 0,
      width: 900,
      x: 0,
      y: 0,
    })
    fireEvent.pointerDown(track(), { button: 0, clientX: 0 })
    fireEvent.pointerMove(track(), { button: 0, clientX: 150 })
    fireEvent.pointerUp(track(), { button: 0, clientX: 150 })
    expect(rows()[0]).toHaveAttribute('data-timeline-focus', 'inside')
    expect(rows()[8]).toHaveAttribute('data-timeline-focus', 'outside')
    expect(spanBars()[8]).toHaveAttribute('data-dim', 'range')
    fireEvent.keyDown(track(), { key: 'Escape' })
    expect(rows()[8]).not.toHaveAttribute('data-timeline-focus')
  })

  it('clears the range on a right click', () => {
    renderTab()
    fireEvent.pointerDown(track(), { button: 0, clientX: 0 })
    fireEvent.pointerUp(track(), { button: 0, clientX: 0 })
    expect(rows()[0]).toHaveAttribute('data-timeline-focus')
    fireEvent.pointerDown(track(), { button: 2, clientX: 0 })
    fireEvent.pointerUp(track(), { button: 2, clientX: 0 })
    expect(rows()[0]).not.toHaveAttribute('data-timeline-focus')
  })

  it('dims the spans that do not match the search', async () => {
    renderTab()
    await userEvent.type(
      screen.getByRole('searchbox', { name: 'Search trajectory' }),
      'denied',
    )
    const dimmed = spanBars().filter((s) => s.dataset.dim === 'search')
    expect(dimmed).toHaveLength(8)
  })

  it('says when there is no timing data', () => {
    renderTab('closed', [])
    expect(screen.getByText('No timing data')).toBeInTheDocument()
  })
})

describe('overview helpers', () => {
  it('focuses the records active at any point of a range', () => {
    const spans = [
      { end: 1, id: 'a', lane: 0 as const, start: 0 },
      { end: 3, id: 'b', lane: 1 as const, start: 1 },
      { end: 4, id: 'c', lane: 2 as const, start: 3.5 },
    ]
    expect([...focusedBy(spans, [1.5, 2])!]).toEqual(['b'])
    expect(focusedBy(spans, null)).toBeNull()
  })

  it('formats totals with thousands separators', () => {
    expect(totalText(1234.4)).toBe('Total 1,234 ms')
  })
})
