import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { render, screen, within } from '@/test/utils'
import type { AgentTask } from '@/types'

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
