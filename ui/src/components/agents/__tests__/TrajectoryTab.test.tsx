import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@/test/utils'
import type { AgentTask } from '@/types'

import { inspectedSeq, startedText, tabsFor } from '../TrajectoryInspector'
import { focusedBy, totalText } from '../TrajectoryOverview'
import { TrajectoryTab } from '../TrajectoryTab'
import { DURATION_KEY } from '../TrajectoryToolbar'
import { frameOf, sameWindow, windowOf } from '../trajectoryWindow'
import { event, task } from './taskFixtures'
import {
  captureHighlights,
  findStub,
  layout,
  scrollPane,
  tableHeight,
} from './virtualLayout'

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

const isLedger = (el: HTMLElement) => !!el.querySelector(':scope > table')

function ledger() {
  return screen.getByRole('grid', { name: 'Trajectory' }).parentElement!
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

  it('keeps a folded turn folded when its first row is clicked', async () => {
    renderTab()
    await userEvent.click(
      screen.getByRole('button', { name: 'Collapse turns' }),
    )
    expect(rows()).toHaveLength(4)
    await userEvent.click(rows()[2])
    expect(rows()[2]).toHaveAttribute('aria-selected', 'true')
    expect(rows()).toHaveLength(4)
    await userEvent.dblClick(rows()[2])
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

  it('selects the record again when a #e link comes back', async () => {
    const path = '/agents/tasks/acme/T-1/trajectory'
    const go = (url: string) =>
      act(() => {
        window.history.pushState(null, '', url)
        window.dispatchEvent(new PopStateEvent('popstate'))
      })
    window.history.replaceState(null, '', `${path}#e5`)
    renderTab()
    expect(rows()[3]).toHaveAttribute('aria-selected', 'true')
    await userEvent.click(
      within(inspector()).getByRole('button', { name: 'Close inspector' }),
    )
    go(path)
    go(`${path}#e5`)
    expect(rows()[3]).toHaveAttribute('aria-selected', 'true')
    expect(inspector()).toBeInTheDocument()
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

  it('moves a fallback link to its event once the event arrives', () => {
    window.history.replaceState(
      null,
      '',
      '/agents/tasks/acme/T-1/trajectory#e12',
    )
    const t = task({ status: 'running' }) as unknown as AgentTask
    const view = render(
      <div className="flex h-150 flex-col">
        <TrajectoryTab events={LOG} task={t} />
      </div>,
    )
    expect(rows()[rows().length - 1]).toHaveAttribute('aria-selected', 'true')
    view.rerender(
      <div className="flex h-150 flex-col">
        <TrajectoryTab
          events={[...LOG, event(12, 'session.closed', {})]}
          task={t}
        />
      </div>,
    )
    const last = rows()[rows().length - 1]
    expect(last.dataset.kind).toBe('system')
    expect(last).toHaveAttribute('aria-selected', 'true')
  })

  const early = [
    event(1, 'task.created', { title: 'T' }),
    event(2, 'usage.reported', { message_id: 'm1', tokens_in: 1 }),
    event(3, 'turn', { body: 'Asking', kind: 'text', message_id: 'm1' }),
    event(4, 'usage.reported', { message_id: 's1', tokens_in: 2 }),
    event(5, 'usage.reported', { message_id: 'm2', tokens_in: 3 }),
    event(6, 'turn', { body: 'Done', kind: 'text', message_id: 'm2' }),
  ]
  const joined = event(
    7,
    'tool.called',
    { call_id: 'r1', message_id: 's1', parent_call_id: 'c1', tool: 'Read' },
    { actor_kind: 'subagent' },
  )
  function renderLive(events: typeof early) {
    const t = task({ status: 'running' }) as unknown as AgentTask
    const ui = (list: typeof early) => (
      <div className="flex h-150 flex-col">
        <TrajectoryTab events={list} task={t} />
      </div>
    )
    const view = render(ui(events))
    return (next: typeof early) => view.rerender(ui(next))
  }

  it('keeps a selected request once a subagent report leaves the list', async () => {
    window.history.replaceState(null, '', '/agents/tasks/acme/T-1/trajectory')
    const update = renderLive(early)
    await userEvent.click(screen.getByRole('button', { name: 'Request #3' }))
    update([...early, joined])
    expect(within(inspector()).getByText('Request #2')).toBeInTheDocument()
    expect(
      rows().find((r) => r.getAttribute('data-record') === early[4].event_id),
    ).toHaveAttribute('data-request-selected', 'true')
  })

  it('follows a linked subagent report to its Agent call', () => {
    window.history.replaceState(
      null,
      '',
      '/agents/tasks/acme/T-1/trajectory#e4',
    )
    const update = renderLive(early)
    expect(
      rows().find((r) => r.getAttribute('data-record') === early[3].event_id),
    ).toHaveAttribute('aria-selected', 'true')
    update([...early, joined])
    expect(
      rows().find((r) => r.getAttribute('data-record') === 'call:c1'),
    ).toHaveAttribute('aria-selected', 'true')
    expect(inspector()).toBeInTheDocument()
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

describe('TrajectoryTab empty states', () => {
  it('says when nothing matches and clears the search', async () => {
    renderTab()
    const search = screen.getByRole('searchbox', { name: 'Search trajectory' })
    await userEvent.type(search, 'zzqx-no-match')
    expect(screen.queryByRole('grid', { name: 'Trajectory' })).toBeNull()
    expect(screen.getByText('No matches')).toBeInTheDocument()
    expect(
      screen.getByText('Nothing in this view matches “zzqx-no-match”.'),
    ).toBeInTheDocument()
    const empty = screen
      .getByText('No matches')
      .closest('[data-slot="empty"]') as HTMLElement
    expect(empty).toHaveAttribute('data-search-skip')
    await userEvent.click(
      within(empty).getByRole('button', { name: 'Clear search' }),
    )
    expect(search).toHaveValue('')
    expect(screen.queryByText('No matches')).toBeNull()
    expect(rows().length).toBeGreaterThan(0)
  })

  it('hides the inspector while nothing matches', async () => {
    renderTab()
    await userEvent.click(rows()[3])
    expect(inspector()).toBeInTheDocument()
    const search = screen.getByRole('searchbox', { name: 'Search trajectory' })
    await userEvent.type(search, 'zzqx-no-match')
    expect(screen.getByText('No matches')).toBeInTheDocument()
    expect(screen.queryByRole('complementary')).toBeNull()
    await userEvent.clear(search)
    expect(inspector()).toBeInTheDocument()
  })

  it('says when there is no activity yet', () => {
    renderTab('running', [])
    expect(screen.getByText('No activity yet')).toBeInTheDocument()
    expect(screen.getByText('No trajectory yet.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Clear search' })).toBeNull()
  })
})

describe('TrajectoryTab toolbar', () => {
  beforeEach(() => window.localStorage.clear())

  it('collapses and expands every turn with one button', async () => {
    renderTab()
    await userEvent.click(
      screen.getByRole('button', { name: 'Collapse turns' }),
    )
    expect(rows()).toHaveLength(4)
    expect(
      screen.getByRole('button', { name: 'Expand turns' }),
    ).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(screen.getByRole('button', { name: 'Expand turns' }))
    expect(rows()).toHaveLength(9)
  })

  it('folds the calls under every assistant', async () => {
    renderTab()
    await userEvent.click(
      screen.getByRole('button', { name: 'Collapse tool calls' }),
    )
    expect(rows()).toHaveLength(8)
    expect(rows()[3]).toHaveTextContent('2 tool calls · Bash, Grep')
    expect(rows()[7]).toHaveTextContent('1 tool call · Bash')
  })

  it('disables a fold button with nothing to fold', () => {
    renderTab()
    expect(
      screen.getByRole('button', { name: 'Collapse subagent calls' }),
    ).toHaveAttribute('aria-disabled', 'true')
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

function leftOf(bar: HTMLElement) {
  return Number(/calc\((-?[\d.]+)%/.exec(bar.getAttribute('style') ?? '')?.[1])
}

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

  it('zooms past a selected span without looping', async () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {})
    renderTab()
    await userEvent.click(screen.getByRole('button', { name: 'Duration' }))
    await userEvent.click(rows()[3])
    for (let i = 0; i < 4; i++) fireEvent.wheel(track(), { deltaY: -2000 })
    await new Promise((r) => setTimeout(r, 50))
    expect(
      error.mock.calls.some((c) => String(c[0]).includes('Maximum update')),
    ).toBe(false)
    error.mockRestore()
  })

  it('keeps a manual pan away from the selected span', async () => {
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
    await userEvent.click(rows()[0])
    fireEvent.wheel(track(), { clientX: 0, deltaY: -2000 })
    expect(leftOf(spanBars()[0])).toBe(0)
    fireEvent.pointerDown(track(), { button: 2, clientX: 900 })
    fireEvent.pointerMove(track(), { button: 2, clientX: 0 })
    fireEvent.pointerUp(track(), { button: 2, clientX: 0 })
    await new Promise((r) => setTimeout(r, 20))
    expect(leftOf(spanBars()[0])).toBe(-100)
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

  it('scrolls to a range once, not again when a live event arrives', () => {
    const scrollTo = vi.fn()
    const smooth = () =>
      scrollTo.mock.calls.filter(
        ([options]) => (options as ScrollToOptions).behavior === 'smooth',
      )
    const original = Element.prototype.scrollTo
    Element.prototype.scrollTo = scrollTo
    const t = task({ status: 'running' }) as unknown as AgentTask
    const ui = (events: typeof LOG) => (
      <div className="flex h-150 flex-col">
        <TrajectoryTab events={events} task={t} />
      </div>
    )
    try {
      const view = render(ui(LOG))
      fireEvent.pointerDown(track(), { button: 0, clientX: 0 })
      fireEvent.pointerUp(track(), { button: 0, clientX: 0 })
      expect(rows()[0]).toHaveAttribute('data-timeline-focus', 'inside')
      expect(smooth()).toHaveLength(1)
      view.rerender(ui([...LOG, event(12, 'session.closed', {})]))
      expect(rows()[rows().length - 1].dataset.kind).toBe('system')
      expect(smooth()).toHaveLength(1)
    } finally {
      Element.prototype.scrollTo = original
    }
  })

  it('keeps a range at the live edge to the records it covered', () => {
    const scrollTo = vi.fn()
    const smooth = () =>
      scrollTo.mock.calls.filter(
        ([options]) => (options as ScrollToOptions).behavior === 'smooth',
      )
    const original = Element.prototype.scrollTo
    Element.prototype.scrollTo = scrollTo
    const t = task({ status: 'running' }) as unknown as AgentTask
    const ui = (events: typeof LOG) => (
      <div className="flex h-150 flex-col">
        <TrajectoryTab events={events} task={t} />
      </div>
    )
    try {
      const view = render(ui(LOG))
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
      fireEvent.pointerDown(track(), { button: 0, clientX: 600 })
      fireEvent.pointerMove(track(), { button: 0, clientX: 900 })
      fireEvent.pointerUp(track(), { button: 0, clientX: 900 })
      expect(rows()[rows().length - 1]).toHaveAttribute(
        'data-timeline-focus',
        'inside',
      )
      expect(smooth()).toHaveLength(1)
      view.rerender(ui([...LOG, event(12, 'session.closed', {})]))
      expect(rows()[rows().length - 1].dataset.kind).toBe('system')
      expect(rows()[rows().length - 1]).toHaveAttribute(
        'data-timeline-focus',
        'outside',
      )
      expect(spanBars()[spanBars().length - 1]).toHaveAttribute(
        'data-dim',
        'range',
      )
      expect(smooth()).toHaveLength(1)
    } finally {
      Element.prototype.scrollTo = original
    }
  })

  it('moves a range with its records when live rows land before it', () => {
    const t = task({ status: 'running' }) as unknown as AgentTask
    const sub = (seq: number, id: string) =>
      event(
        seq,
        'tool.called',
        { call_id: id, duration_ms: 5, parent_call_id: 'a1', tool: 'Grep' },
        { actor_kind: 'subagent' },
      )
    const base = [
      ...LOG,
      sub(12, 's1'),
      event(13, 'usage.reported', { tokens_in: 2, tokens_out: 5 }),
      event(14, 'turn', { body: 'Still going', kind: 'text' }),
    ]
    const ui = (events: typeof LOG) => (
      <div className="flex h-150 flex-col">
        <TrajectoryTab events={events} task={t} />
      </div>
    )
    const view = render(ui(base))
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
    const last = () => spanBars()[spanBars().length - 1]
    fireEvent.pointerDown(track(), { button: 0, clientX: 850 })
    fireEvent.pointerMove(track(), { button: 0, clientX: 900 })
    fireEvent.pointerUp(track(), { button: 0, clientX: 900 })
    const band = () =>
      track().querySelector<HTMLElement>('[data-range="committed"]')!
    const edges = () => [
      parseFloat(band().style.left),
      parseFloat(band().style.left) + parseFloat(band().style.width),
    ]
    expect(last()).not.toHaveAttribute('data-dim')
    const before = edges()
    const count = spanBars().length
    view.rerender(ui([...base, sub(15, 's2')]))
    expect(spanBars().length).toBe(count + 1)
    expect(last()).not.toHaveAttribute('data-dim')
    const [from, to] = edges()
    expect(from).toBeGreaterThan(before[0])
    expect(to).toBeCloseTo(100)
  })

  it('keeps a range ordered when its subagent requests leave', () => {
    const t = task({ status: 'running' }) as unknown as AgentTask
    const base = [
      event(1, 'task.created', { title: 'T' }),
      event(2, 'usage.reported', { message_id: 'm1', tokens_in: 1 }),
      event(3, 'usage.reported', { message_id: 's1', tokens_in: 2 }),
      event(4, 'usage.reported', { message_id: 's2', tokens_in: 2 }),
      event(5, 'usage.reported', { message_id: 'm2', tokens_in: 3 }),
      event(6, 'turn', { body: 'Done', kind: 'text', message_id: 'm2' }),
    ]
    const sub = (seq: number, id: string, message: string) =>
      event(
        seq,
        'tool.called',
        {
          call_id: id,
          message_id: message,
          parent_call_id: 'c1',
          tool: 'Read',
        },
        { actor_kind: 'subagent' },
      )
    const ui = (events: typeof LOG) => (
      <div className="flex h-150 flex-col">
        <TrajectoryTab events={events} task={t} />
      </div>
    )
    const view = render(ui(base))
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
    const ids = spanBars().map((b) => b.dataset.span)
    const first = ids.indexOf(base[1].event_id)
    expect(ids.slice(first, first + 3)).toEqual(
      base.slice(1, 4).map((e) => e.event_id),
    )
    const unit = 900 / ids.length
    fireEvent.pointerDown(track(), {
      button: 0,
      clientX: (first + 0.9) * unit,
    })
    fireEvent.pointerMove(track(), {
      button: 0,
      clientX: (first + 2.1) * unit,
    })
    fireEvent.pointerUp(track(), { button: 0, clientX: (first + 2.1) * unit })
    view.rerender(ui([...base, sub(7, 'r1', 's1'), sub(8, 'r2', 's2')]))
    expect(spanBars().map((b) => b.dataset.span)).not.toContain(
      base[2].event_id,
    )
    const band = track().querySelector<HTMLElement>('[data-range="committed"]')!
    const n = spanBars().length
    expect(parseFloat(band.style.left)).toBeCloseTo((first / n) * 100)
    expect(parseFloat(band.style.width)).toBeCloseTo(100 / n)
  })

  it('drops a drag on the strip when the browser cancels it', () => {
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
    expect(track().querySelector('[data-range="draft"]')).not.toBeNull()
    fireEvent.pointerCancel(track())
    expect(track().querySelector('[data-range]')).toBeNull()
    fireEvent.pointerMove(track(), { clientX: 300 })
    expect(track().querySelector('[data-range]')).toBeNull()
    expect(rows()[0]).not.toHaveAttribute('data-timeline-focus')
  })

  it('selects a request on a double-click of its dot without folding', async () => {
    renderTab()
    const dot = screen.getAllByRole('button', { name: /^Request #/ })[0]
    const before = rows().length
    await userEvent.dblClick(dot)
    expect(rows()).toHaveLength(before)
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

  it('fits the assistant tag to its label in the header', async () => {
    renderTab()
    const row = rows().find((r) => within(r).queryByText('ASSISTANT'))!
    expect(within(row).getByText('ASSISTANT').parentElement).toHaveClass(
      'w-full',
    )
    await userEvent.click(row)
    expect(
      within(inspector()).getByText('ASSISTANT').parentElement,
    ).not.toHaveClass('w-full')
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

  it('adds the subagent requests so far to the session usage', async () => {
    renderTab('closed', [
      event(1, 'task.created', { title: 'T' }),
      event(2, 'usage.reported', { message_id: 'm1', tokens_in: 1 }),
      event(3, 'tool.called', {
        arguments: {},
        call_id: 'c1',
        message_id: 'm1',
        tool: 'Agent',
      }),
      event(4, 'usage.reported', { message_id: 's1', tokens_in: 20 }),
      event(
        5,
        'tool.called',
        { call_id: 'r1', message_id: 's1', parent_call_id: 'c1', tool: 'Read' },
        { actor_kind: 'subagent' },
      ),
      event(6, 'usage.reported', { message_id: 'm2', tokens_in: 300 }),
      event(7, 'turn', { body: 'Done', kind: 'text', message_id: 'm2' }),
    ])
    await userEvent.click(screen.getByRole('button', { name: 'Request #2' }))
    await userEvent.click(
      within(inspector()).getByRole('tab', { name: 'Usage' }),
    )
    const group = (title: string) =>
      within(inspector()).getByText(title).parentElement
    expect(group('This request')).toHaveTextContent('300 tok')
    expect(group('Session cumulative')).toHaveTextContent('321 tok')
  })

  it('previews a person in full, with their Markdown', async () => {
    const long = `**Bold** ${'word '.repeat(150)}the end`
    renderTab('closed', [
      event(1, 'task.created', { description: long, title: 'T' }),
      ...LOG.slice(1),
    ])
    await userEvent.click(rows()[0])
    await userEvent.click(
      within(inspector()).getByRole('tab', { name: 'Preview' }),
    )
    expect(within(inspector()).getByText('Bold').tagName).toBe('STRONG')
    expect(inspector()).toHaveTextContent(/the end/)
  })

  it('shows the messages of a subagent call in Raw', async () => {
    const sub = { actor_kind: 'subagent' as const }
    renderTab('closed', [
      ...LOG,
      event(12, 'turn', { body: 'Sub says hi', parent_call_id: 'a1' }, sub),
      event(13, 'tool.called', {
        arguments: { description: 'look' },
        call_id: 'a1',
        duration_ms: 50,
        result: 'ok',
        tool: 'Agent',
      }),
    ])
    await userEvent.click(
      rows().find((r) => r.getAttribute('data-record') === 'call:a1')!,
    )
    await userEvent.click(within(inspector()).getByRole('tab', { name: 'Raw' }))
    expect(inspector()).toHaveTextContent('Sub says hi')
  })

  it('finds a subagent call by the messages of the subagent', async () => {
    const sub = { actor_kind: 'subagent' as const }
    renderTab('closed', [
      ...LOG,
      event(12, 'turn', { body: 'Sub says hi', parent_call_id: 'a1' }, sub),
      event(13, 'tool.called', {
        arguments: { description: 'look' },
        call_id: 'a1',
        duration_ms: 50,
        result: 'ok',
        tool: 'Agent',
      }),
    ])
    await userEvent.type(
      screen.getByRole('searchbox', { name: 'Search trajectory' }),
      'sub says hi',
    )
    expect(
      rows().some((r) => r.getAttribute('data-record') === 'call:a1'),
    ).toBe(true)
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

  it('stops resizing when the pointer is cancelled', async () => {
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
    fireEvent.pointerDown(handle, { button: 0, clientX: 500 })
    fireEvent.pointerMove(window, { clientX: 480 })
    expect(inspector().style.width).toBe('420px')
    fireEvent.pointerCancel(window)
    fireEvent.pointerMove(window, { clientX: 440 })
    expect(inspector().style.width).toBe('420px')
  })
})

describe('TrajectoryTab selection and the conversation', () => {
  function renderWith(onShow = vi.fn(), events = LOG) {
    const t = task({ status: 'closed' }) as unknown as AgentTask
    render(
      <div className="flex h-150 flex-col">
        <TrajectoryTab events={events} onShowInConversation={onShow} task={t} />
      </div>,
    )
    return onShow
  }

  it('tints and rings the selected row and the row of a selected request', async () => {
    renderWith()
    await userEvent.click(rows()[3])
    expect(rows()[3]).toHaveClass('bg-action/10', 'inset-ring-action/35')
    expect(rows()[2]).not.toHaveClass('bg-action/10')
    await userEvent.click(
      within(rows()[2]).getByRole('button', { name: 'Request #1' }),
    )
    expect(rows()[2]).toHaveAttribute('data-request-selected', 'true')
    expect(rows()[2]).toHaveClass('bg-action/10', 'inset-ring-action/35')
    expect(rows()[3]).not.toHaveClass('bg-action/10')
  })

  it('shows the selected event in the conversation', async () => {
    const onShow = renderWith()
    await userEvent.click(rows()[3])
    await userEvent.click(
      within(inspector()).getByRole('button', { name: 'Show in conversation' }),
    )
    expect(onShow).toHaveBeenLastCalledWith(5)
    await userEvent.click(
      within(rows()[2]).getByRole('button', { name: 'Request #1' }),
    )
    await userEvent.click(
      within(inspector()).getByRole('button', { name: 'Show in conversation' }),
    )
    expect(onShow).toHaveBeenLastCalledWith(4)
  })

  it('shows a subagent call by its first subagent event', async () => {
    const sub = { actor_kind: 'subagent' as const }
    const onShow = renderWith(vi.fn(), [
      ...LOG,
      event(12, 'turn', { body: 'Sub says hi', parent_call_id: 'a1' }, sub),
      event(13, 'tool.called', {
        arguments: { description: 'look' },
        call_id: 'a1',
        duration_ms: 50,
        result: 'ok',
        tool: 'Agent',
      }),
    ])
    await userEvent.click(
      rows().find((r) => r.getAttribute('data-record') === 'call:a1')!,
    )
    await userEvent.click(
      within(inspector()).getByRole('button', { name: 'Show in conversation' }),
    )
    expect(onShow).toHaveBeenLastCalledWith(12)
  })

  it('has no conversation button without a handler', async () => {
    renderTab()
    await userEvent.click(rows()[3])
    expect(
      within(inspector()).queryByRole('button', {
        name: 'Show in conversation',
      }),
    ).not.toBeInTheDocument()
  })

  it('frames the rows in view on the strip and follows the scroll', async () => {
    const spy = layout({
      content: tableHeight(36),
      isPane: isLedger,
      pane: 108,
      row: 36,
    })
    try {
      renderTab()
      scrollPane(ledger(), 0)
      const frame = () => document.querySelector<HTMLElement>('[data-window]')
      await waitFor(() => expect(frame()).toBeInTheDocument())
      expect(frame()?.style.left).toBe('0%')
      expect(frame()).toHaveClass('pointer-events-none')
      const width = frame()?.style.width
      scrollPane(ledger(), 36 * 5)
      await waitFor(() => expect(frame()?.style.left).not.toBe('0%'))
      expect(parseFloat(frame()?.style.left ?? '')).toBeCloseTo(500 / 9)
      expect(frame()?.style.width).toBe(width)
    } finally {
      spy.mockRestore()
    }
  })

  it('marks the selected span on the strip', async () => {
    renderTab()
    expect(document.querySelector('[data-picked]')).toBeNull()
    await userEvent.click(rows()[3])
    expect(document.querySelector('[data-picked]')).toBeInTheDocument()
  })
})

describe('TrajectoryTab with many rows', () => {
  const LONG = [
    event(1, 'task.created', { description: 'Check the release', title: 'T' }),
    event(2, 'session.opened', { session_id: 's' }),
    ...Array.from({ length: 150 }, (_, i) => [
      event(3 + i * 3, 'usage.reported', {
        message_id: `m${i}`,
        tokens_in: 1,
      }),
      event(4 + i * 3, 'turn', {
        body: `Step ${i}`,
        kind: 'text',
        message_id: `m${i}`,
      }),
      event(5 + i * 3, 'tool.called', {
        arguments: { command: `ls ${i}` },
        call_id: `c${i}`,
        duration_ms: 5,
        message_id: `m${i}`,
        result: `needle ${i}`,
        tool: 'Bash',
      }),
    ]).flat(),
  ]
  let spy: ReturnType<typeof layout>
  beforeEach(() => {
    spy = layout({
      content: tableHeight(36),
      isPane: isLedger,
      pane: 360,
      row: 36,
    })
  })
  afterEach(() => {
    cleanup()
    spy.mockRestore()
    vi.unstubAllGlobals()
  })

  it('renders only the rows in view and counts them all', async () => {
    renderTab('closed', LONG)
    const grid = screen.getByRole('grid', { name: 'Trajectory' })
    expect(grid).toHaveAttribute('aria-rowcount', '302')
    expect(rows().length).toBeLessThan(40)
    await waitFor(() =>
      expect(rows()[rows().length - 1]).toHaveAttribute('aria-rowindex', '302'),
    )
  })

  it('lets the browser find a row out of view and scrolls to it', async () => {
    renderTab('closed', LONG)
    const stub = findStub('needle 75')
    expect(stub).toHaveAttribute('hidden', 'until-found')
    expect(screen.queryByText('needle 75')).toBeNull()
    act(() => {
      stub.dispatchEvent(new Event('beforematch'))
    })
    expect(await screen.findByText('needle 75')).toBeInTheDocument()
  })

  it('lets the browser find a turn label out of view', () => {
    const turns = Array.from({ length: 100 }, (_, i) => [
      event(
        3 + i * 3,
        'turn',
        { body: `ask ${i}` },
        { actor_id: 'dev', actor_kind: 'human' },
      ),
      event(4 + i * 3, 'usage.reported', {
        message_id: `m${i}`,
        tokens_in: 1,
      }),
      event(5 + i * 3, 'turn', {
        body: `reply ${i}`,
        kind: 'text',
        message_id: `m${i}`,
      }),
    ]).flat()
    renderTab('closed', [...LONG.slice(0, 2), ...turns])
    expect(screen.queryByText('ask 74')).toBeNull()
    const stub = findStub('ask 74')
    expect(stub.textContent).toBe('Turn 76 USER ask 74')
    expect(findStub('Turn 76')).toBe(stub)
  })

  it('scrolls to a record a late #e link points at', () => {
    const scrollTo = vi.fn()
    window.history.replaceState(
      null,
      '',
      '/agents/tasks/acme/T-1/trajectory#e434',
    )
    const t = task({ status: 'running' }) as unknown as AgentTask
    const view = render(
      <div className="flex h-150 flex-col">
        <TrajectoryTab events={LONG.slice(0, 20)} task={t} />
      </div>,
    )
    ledger().scrollTo = scrollTo
    view.rerender(
      <div className="flex h-150 flex-col">
        <TrajectoryTab events={LONG} task={t} />
      </div>,
    )
    const selected = document.querySelector<HTMLElement>('[data-selected]')
    expect(selected).toHaveTextContent('ls 143')
    const index = Number(selected?.getAttribute('aria-rowindex')) - 1
    const [{ top }] = scrollTo.mock.lastCall as [{ top: number }]
    expect(top).toBeLessThanOrEqual(index * 36)
    expect(top + 360).toBeGreaterThanOrEqual(index * 36 + 36)
  })

  it('moves focus with the arrow keys, Home and End past the rows in view', async () => {
    renderTab('closed', LONG)
    scrollPane(ledger(), 0)
    rows()[0].focus()
    await userEvent.keyboard('{ArrowDown}')
    expect(document.activeElement).toHaveAttribute('aria-rowindex', '2')
    await userEvent.keyboard('{End}')
    await waitFor(() => expect(ledger().scrollTop).toBeGreaterThan(0))
    await waitFor(() =>
      expect(rows()[0]).not.toHaveAttribute('aria-rowindex', '1'),
    )
    expect(document.activeElement).toHaveAttribute('aria-rowindex', '302')
    expect(document.activeElement).toHaveTextContent('needle 149')
    await userEvent.keyboard('{ArrowUp}')
    expect(document.activeElement).toHaveAttribute('aria-rowindex', '301')
    await userEvent.keyboard('{Home}')
    expect(document.activeElement).toHaveAttribute('aria-rowindex', '1')
  })

  it('leaves focus where the reader moves it after Home on the first row', async () => {
    renderTab('closed', LONG)
    scrollPane(ledger(), 0)
    rows()[0].focus()
    await userEvent.keyboard('{Home}')
    const search = screen.getByRole('searchbox', { name: 'Search trajectory' })
    await userEvent.click(search)
    await userEvent.paste('needle')
    expect(document.activeElement).toBe(search)
    expect(search).toHaveValue('needle')
  })

  it('keeps the focused row rendered when rows land above it', async () => {
    const view = renderTab('closed', LONG)
    scrollPane(ledger(), 0)
    const dot = within(rows()[4]).getByRole('button', { name: /^Request #/ })
    dot.focus()
    const t = task({ status: 'closed' }) as unknown as AgentTask
    view.rerender(
      <div className="flex h-150 flex-col">
        <TrajectoryTab
          events={[
            ...LONG,
            event(500, 'tool.called', {
              arguments: { command: 'pwd' },
              call_id: 'k1',
              duration_ms: 1,
              parent_call_id: 'c0',
              result: 'x',
              tool: 'Bash',
            }),
          ]}
          task={t}
        />
      </div>,
    )
    expect(screen.getByRole('grid', { name: 'Trajectory' })).toHaveAttribute(
      'aria-rowcount',
      '303',
    )
    scrollPane(ledger(), 5000)
    await waitFor(() =>
      expect(rows()[0]).not.toHaveAttribute('aria-rowindex', '1'),
    )
    expect(dot).toBeInTheDocument()
    expect(document.activeElement).toBe(dot)
  })

  it('keeps a row rendered while its request dot has focus', async () => {
    renderTab('closed', LONG)
    scrollPane(ledger(), 0)
    const dot = within(rows()[2]).getByRole('button', { name: /^Request #/ })
    dot.focus()
    scrollPane(ledger(), 5000)
    await waitFor(() =>
      expect(rows()[0]).not.toHaveAttribute('aria-rowindex', '1'),
    )
    expect(dot).toBeInTheDocument()
    expect(document.activeElement).toBe(dot)
  })

  it('folds every call and opens one from the keyboard', async () => {
    renderTab('closed', LONG)
    rows()[0].focus()
    await userEvent.keyboard('{End}')
    await userEvent.click(
      screen.getByRole('button', { name: 'Collapse tool calls' }),
    )
    const grid = screen.getByRole('grid', { name: 'Trajectory' })
    expect(grid).toHaveAttribute('aria-rowcount', '302')
    const summary = screen.getAllByRole('row', {
      name: /^Expand 1 tool call/,
    })
    expect(summary.length).toBeLessThan(40)
    summary[0].focus()
    expect(document.activeElement).toBe(summary[0])
    const at = summary[0].getAttribute('aria-rowindex')
    const row = () =>
      document.querySelector<HTMLElement>(`[aria-rowindex="${at}"]`)
    expect(row()?.dataset.kind).toBeUndefined()
    await userEvent.keyboard('{Enter}')
    expect(row()?.dataset.kind).toBe('tool')
    expect(row()).toHaveTextContent(/needle \d+/)
  })

  it('filters every record from the data and marks what renders', async () => {
    const { marked, mutate } = captureHighlights()
    renderTab('closed', LONG)
    screen.getByRole('searchbox', { name: 'Search trajectory' }).focus()
    await userEvent.paste('needle 1')
    const grid = screen.getByRole('grid', { name: 'Trajectory' })
    expect(grid).toHaveAttribute('aria-rowcount', '61')
    expect(rows().length).toBeLessThan(61)
    scrollPane(ledger(), 0)
    mutate()
    await waitFor(() => expect(marked.current[0]).toBe('needle 1'))
    expect(marked.current.every((text) => text.startsWith('needle 1'))).toBe(
      true,
    )
    expect(marked.current).toHaveLength(rows().length)
    scrollPane(ledger(), 60 * 36)
    mutate()
    await waitFor(() =>
      expect(rows()[rows().length - 1]).toHaveTextContent('needle 149'),
    )
    await waitFor(() => expect(marked.current).toContain('needle 149'))
    expect(marked.current).not.toContain('needle 10')
  }, 15_000)

  it('copies every event, not only the rows in view', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn((_: string) => Promise.resolve())
    renderTab('closed', LONG)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    await user.click(screen.getByRole('button', { name: /^Copy/ }))
    await user.click(screen.getByRole('menuitem', { name: 'Copy as JSON' }))
    const copied = JSON.parse(writeText.mock.calls[0][0]) as {
      events: unknown[]
    }
    expect(rows().length).toBeLessThan(40)
    expect(copied.events).toHaveLength(LONG.length)
  })
})

describe('trajectory window helpers', () => {
  const spans = [
    { end: 1, id: 'a', lane: 0 as const, start: 0 },
    { end: 4, id: 'b', lane: 1 as const, start: 1 },
    { end: 3, id: 'c', lane: 2 as const, start: 2 },
  ]

  it('takes the first and last rows that show', () => {
    const list = ['a', 'b', 'c'].map((id, i) => ({
      bottom: i * 10 + 10,
      id,
      top: i * 10,
    }))
    expect(windowOf(list, 5, 15)).toEqual({
      from: 'a',
      ids: ['a', 'b'],
      to: 'b',
    })
    expect(windowOf(list, 10, 30)).toEqual({
      from: 'b',
      ids: ['b', 'c'],
      to: 'c',
    })
    expect(windowOf(list, 40, 50)).toBeNull()
  })

  it('tells a window apart by every row, not only its ends', () => {
    const at = (ids: string[]) =>
      windowOf(
        ids.map((id, i) => ({ bottom: i * 10 + 10, id, top: i * 10 })),
        0,
        100,
      )
    const all = at(['a', 'b', 'c'])
    const filtered = at(['a', 'c'])
    expect([filtered?.from, filtered?.to]).toEqual([all?.from, all?.to])
    expect(sameWindow(all, filtered)).toBe(false)
    expect(sameWindow(all, at(['a', 'b', 'c']))).toBe(true)
    expect(sameWindow(null, null)).toBe(true)
    expect(sameWindow(all, null)).toBe(false)
  })

  it('frames from the earliest start to the latest end', () => {
    const win = (ids: string[]) => ({ from: ids[0], ids, to: ids.at(-1)! })
    expect(frameOf(spans, win(['b', 'c']))).toEqual([1, 4])
    expect(frameOf(spans, win(['a']))).toEqual([0, 1])
    expect(frameOf(spans, win(['x']))).toBeNull()
    expect(frameOf(spans, null)).toBeNull()
  })

  it('frames a row between the first and last that starts earlier', () => {
    const out = [
      { end: 10, id: 'a', lane: 2 as const, start: 9 },
      { end: 11, id: 'b', lane: 2 as const, start: 1 },
      { end: 12, id: 'c', lane: 2 as const, start: 11 },
    ]
    expect(frameOf(out, { from: 'a', ids: ['a', 'b', 'c'], to: 'c' })).toEqual([
      1, 12,
    ])
  })
})

describe('inspector helpers', () => {
  it('finds the first shown event of a record or a request', () => {
    const ev = (seq: number, type = 'turn') => ({ seq, type })
    const trajectory = {
      records: [
        { events: [ev(3, 'usage.reported'), ev(7), ev(4)], id: 'm' },
        { events: [ev(2, 'usage.reported')], id: 'u', seqs: [2] },
      ],
    } as never
    expect(
      inspectedSeq(
        { record: { events: [ev(9), ev(6)] }, type: 'record' } as never,
        trajectory,
      ),
    ).toBe(6)
    expect(
      inspectedSeq(
        {
          request: { assistant: 'm', usage: { seq: 3 } },
          type: 'request',
        } as never,
        trajectory,
      ),
    ).toBe(4)
    expect(
      inspectedSeq(
        {
          request: { assistant: 'u', usage: { seq: 2 } },
          type: 'request',
        } as never,
        trajectory,
      ),
    ).toBe(2)
    expect(
      inspectedSeq(
        { record: { events: [], seqs: [] }, type: 'record' } as never,
        trajectory,
      ),
    ).toBeNull()
  })

  it('gives each kind its tabs', () => {
    const t = { record: { kind: 'user' }, type: 'record' } as never
    expect(tabsFor(t)).toEqual(['Summary', 'Preview', 'Raw'])
  })

  it('formats the start time with milliseconds', () => {
    const ms = new Date(2026, 9, 8, 12, 0, 5, 250).getTime()
    expect(startedText(ms)).toBe('2026-10-08 12:00:05.250')
  })
})

describe('TrajectoryTab folds across tasks', () => {
  afterEach(() => {
    vi.mocked(window.localStorage.getItem).mockReturnValue(null)
  })

  it('opens a task with the turns folded when that was the last choice', () => {
    vi.mocked(window.localStorage.getItem).mockImplementation((key: string) =>
      key === 'imbi.trajectory.folds' ? '["turns"]' : null,
    )
    renderTab()
    expect(rows()).toHaveLength(4)
    expect(
      screen.getByRole('button', { name: 'Expand turns' }),
    ).toHaveAttribute('aria-pressed', 'true')
  })

  it('keeps a linked record in view when its turn becomes foldable', () => {
    vi.mocked(window.localStorage.getItem).mockImplementation((key: string) =>
      key === 'imbi.trajectory.folds' ? '["turns"]' : null,
    )
    window.history.replaceState(
      null,
      '',
      '/agents/tasks/acme/T-1/trajectory#e2',
    )
    const t = task({ status: 'running' }) as unknown as AgentTask
    const view = render(
      <div className="flex h-150 flex-col">
        <TrajectoryTab events={LOG.slice(0, 2)} task={t} />
      </div>,
    )
    const selected = () =>
      rows().filter((r) => r.getAttribute('aria-selected') === 'true')
    expect(selected()).toHaveLength(1)
    view.rerender(
      <div className="flex h-150 flex-col">
        <TrajectoryTab events={LOG.slice(0, 4)} task={t} />
      </div>,
    )
    expect(selected()).toHaveLength(1)
  })

  it('clears a remembered fold with one click after a row was unfolded', async () => {
    vi.mocked(window.localStorage.getItem).mockImplementation((key: string) =>
      key === 'imbi.trajectory.folds' ? '["turns"]' : null,
    )
    renderTab()
    expect(rows()).toHaveLength(4)
    await userEvent.click(rows()[1])
    expect(rows().length).toBeGreaterThan(4)
    const button = screen.getByRole('button', { name: 'Expand turns' })
    expect(button).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(button)
    expect(vi.mocked(window.localStorage.setItem)).toHaveBeenLastCalledWith(
      'imbi.trajectory.folds',
      '[]',
    )
  })

  it('remembers a fold button for the next task', async () => {
    renderTab()
    const setItem = vi.mocked(window.localStorage.setItem)
    setItem.mockClear()
    await userEvent.click(
      screen.getByRole('button', { name: 'Collapse turns' }),
    )
    expect(setItem).toHaveBeenCalledExactlyOnceWith(
      'imbi.trajectory.folds',
      '["turns"]',
    )
  })
})
