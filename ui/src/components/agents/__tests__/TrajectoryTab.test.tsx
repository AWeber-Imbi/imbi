import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fireEvent, render, screen, within } from '@/test/utils'
import type { AgentTask } from '@/types'

import { startedText, tabsFor } from '../TrajectoryInspector'
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

describe('TrajectoryTab links and live tasks', () => {
  it('falls back to the record before a seq no record holds', () => {
    window.history.replaceState(
      null,
      '',
      '/agents/tasks/acme/T-1/trajectory#e50',
    )
    renderTab()
    expect(rows()[rows().length - 1]).toHaveAttribute('aria-selected', 'true')
  })

  it('treats a blocked task as live, so a running call is Pending', async () => {
    window.history.replaceState(null, '', '/agents/tasks/acme/T-1/trajectory')
    renderTab('blocked', [
      ...LOG,
      event(
        12,
        'tool.called',
        { call_id: 's1', duration_ms: 5, parent_call_id: 'a1', tool: 'Grep' },
        { actor_kind: 'subagent' },
      ),
    ])
    const pending = rows().find(
      (r) => r.getAttribute('data-record') === 'call:a1',
    )!
    await userEvent.click(pending)
    expect(
      within(inspector()).getByText('Status').nextElementSibling,
    ).toHaveTextContent('Pending')
  })

  it('keeps a running call selected once it is written', async () => {
    window.history.replaceState(null, '', '/agents/tasks/acme/T-1/trajectory')
    const sub = event(
      12,
      'tool.called',
      { call_id: 's1', duration_ms: 5, parent_call_id: 'a1', tool: 'Grep' },
      { actor_kind: 'subagent' },
    )
    const t = (status: AgentTask['status']) =>
      task({ status }) as unknown as AgentTask
    const view = render(
      <div className="flex h-150 flex-col">
        <TrajectoryTab events={[...LOG, sub]} task={t('running')} />
      </div>,
    )
    await userEvent.click(
      rows().find((r) => r.getAttribute('data-record') === 'call:a1')!,
    )
    view.rerender(
      <div className="flex h-150 flex-col">
        <TrajectoryTab
          events={[
            ...LOG,
            sub,
            event(13, 'tool.called', {
              call_id: 'a1',
              duration_ms: 50,
              result: 'ok',
              tool: 'Agent',
            }),
          ]}
          task={t('running')}
        />
      </div>,
    )
    expect(
      rows().find((r) => r.getAttribute('data-record') === 'call:a1'),
    ).toHaveAttribute('aria-selected', 'true')
    expect(inspector()).toBeInTheDocument()
  })

  it('clears the search when a span re-selects a hidden record', async () => {
    window.history.replaceState(null, '', '/agents/tasks/acme/T-1/trajectory')
    renderTab()
    await userEvent.click(rows()[3])
    const search = screen.getByRole('searchbox', { name: 'Search trajectory' })
    await userEvent.type(search, 'grep')
    const bar = spanBars()[3]
    fireEvent.pointerDown(bar, { button: 0, clientX: 10 })
    fireEvent.pointerUp(bar, { button: 0, clientX: 10 })
    expect(search).toHaveValue('')
    expect(rows()[3]).toHaveAttribute('aria-selected', 'true')
  })

  it('moves between inspector tabs with the arrow keys', async () => {
    window.history.replaceState(null, '', '/agents/tasks/acme/T-1/trajectory')
    renderTab()
    await userEvent.click(rows()[3])
    const summary = within(inspector()).getByRole('tab', { name: 'Summary' })
    expect(within(inspector()).getByRole('tabpanel')).toHaveAccessibleName(
      'Summary',
    )
    summary.focus()
    await userEvent.keyboard('{ArrowRight}')
    const payload = within(inspector()).getByRole('tab', { name: 'Payload' })
    expect(payload).toHaveAttribute('aria-selected', 'true')
    expect(payload).toHaveFocus()
    await userEvent.keyboard('{ArrowLeft}')
    expect(summary).toHaveAttribute('aria-selected', 'true')
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
      screen.getByRole('button', { name: 'No subcalls to fold' }),
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

  it('clears the search when a span selects a record it hides', async () => {
    renderTab()
    const search = screen.getByRole('searchbox', { name: 'Search trajectory' })
    await userEvent.type(search, 'grep')
    expect(rows()).toHaveLength(1)
    const bar = spanBars()[3]
    fireEvent.pointerDown(bar, { button: 0, clientX: 10 })
    fireEvent.pointerUp(bar, { button: 0, clientX: 10 })
    expect(search).toHaveValue('')
    expect(rows()[3]).toHaveAttribute('aria-selected', 'true')
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

function inspector() {
  return screen.getByRole('complementary', { name: 'Inspector' })
}

function tabNames() {
  return within(inspector())
    .getAllByRole('tab')
    .map((t) => t.textContent)
}

describe('TrajectoryTab inspector', () => {
  it('opens on selection and closes with its button', async () => {
    renderTab()
    expect(screen.queryByRole('complementary')).not.toBeInTheDocument()
    await userEvent.click(rows()[3])
    expect(within(inspector()).getByText('TOOL')).toBeInTheDocument()
    expect(within(inspector()).getByText('Turn 1 · Step 1')).toBeInTheDocument()
    await userEvent.click(
      within(inspector()).getByRole('button', { name: 'Close inspector' }),
    )
    expect(screen.queryByRole('complementary')).not.toBeInTheDocument()
  })

  it('shows the tool tabs, summary and payload', async () => {
    renderTab()
    await userEvent.click(rows()[3])
    expect(tabNames()).toEqual(['Summary', 'Payload', 'Result', 'Timing'])
    expect(within(inspector()).getByText('Completed')).toBeInTheDocument()
    await userEvent.click(
      within(inspector()).getByRole('tab', { name: 'Payload' }),
    )
    expect(within(inspector()).getByRole('tabpanel')).toHaveTextContent(
      '"command": "ls"',
    )
    await userEvent.click(
      within(inspector()).getByRole('tab', { name: 'Timing' }),
    )
    expect(within(inspector()).getByText('500 ms')).toBeInTheDocument()
    expect(
      within(inspector()).getByText('Session timestamps'),
    ).toBeInTheDocument()
  })

  it('shows a failed tool as Failed', async () => {
    renderTab()
    await userEvent.click(rows()[4])
    expect(within(inspector()).getByText('Failed')).toBeInTheDocument()
  })

  it('keeps the last tab a record supports', async () => {
    renderTab()
    await userEvent.click(rows()[3])
    await userEvent.click(
      within(inspector()).getByRole('tab', { name: 'Result' }),
    )
    await userEvent.click(rows()[4])
    expect(
      within(inspector()).getByRole('tab', { name: 'Result' }),
    ).toHaveAttribute('aria-selected', 'true')
    await userEvent.click(rows()[2])
    expect(
      within(inspector()).getByRole('tab', { name: 'Summary' }),
    ).toHaveAttribute('aria-selected', 'true')
  })

  it('opens a request from its dot, with usage and its message', async () => {
    renderTab()
    await userEvent.click(
      within(rows()[2]).getByRole('button', { name: 'Request #1' }),
    )
    expect(within(inspector()).getByText('Request #1')).toBeInTheDocument()
    expect(tabNames()).toEqual(['Summary', 'Usage', 'Timing'])
    expect(
      within(inspector()).getAllByText('TTFT')[0].nextElementSibling,
    ).toHaveTextContent('Not recorded')
    await userEvent.click(
      within(inspector()).getByRole('tab', { name: 'Usage' }),
    )
    expect(within(inspector()).getByText('This request')).toBeInTheDocument()
    expect(
      within(inspector()).getByText('Session cumulative'),
    ).toBeInTheDocument()
    await userEvent.click(
      within(inspector()).getByRole('tab', { name: 'Summary' }),
    )
    await userEvent.click(
      within(inspector()).getByRole('button', { name: 'Assistant Message' }),
    )
    expect(rows()[2]).toHaveAttribute('aria-selected', 'true')
  })

  it('shows thinking in the assistant preview', async () => {
    renderTab()
    await userEvent.click(rows()[2])
    await userEvent.click(
      within(inspector()).getByRole('tab', { name: 'Preview' }),
    )
    expect(
      within(inspector()).getByRole('button', { name: 'Thinking' }),
    ).toHaveAttribute('aria-expanded', 'true')
    expect(
      within(inspector()).getByText('Looking at releases'),
    ).toBeInTheDocument()
  })

  it('resizes with the arrow keys and resets on double-click', async () => {
    renderTab()
    await userEvent.click(rows()[3])
    const handle = within(inspector()).getByRole('separator', {
      name: 'Resize inspector',
    })
    vi.spyOn(inspector(), 'getBoundingClientRect').mockReturnValue({
      bottom: 0,
      height: 0,
      left: 0,
      right: 400,
      toJSON: () => ({}),
      top: 0,
      width: 400,
      x: 0,
      y: 0,
    })
    handle.focus()
    await userEvent.keyboard('{ArrowLeft}')
    expect(inspector().style.width).toBe('416px')
    await userEvent.keyboard('{ArrowRight}{ArrowRight}')
    expect(inspector().style.width).toBe('384px')
    await userEvent.dblClick(handle)
    expect(inspector().style.width).toBe('')
  })
})

describe('inspector helpers', () => {
  it('gives each kind its tabs', () => {
    const t = { record: { kind: 'user' }, type: 'record' } as never
    expect(tabsFor(t)).toEqual(['Summary', 'Preview', 'Raw'])
  })

  it('formats the start time with milliseconds', () => {
    const ms = new Date(2026, 9, 8, 12, 0, 5, 250).getTime()
    expect(startedText(ms)).toBe('2026-10-08 12:00:05.250')
  })
})
