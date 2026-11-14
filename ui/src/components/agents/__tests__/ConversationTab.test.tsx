import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { act, cleanup, render, screen, waitFor, within } from '@/test/utils'
import type { AgentTask } from '@/types'

import { MODE_KEY } from '../conversationMode'
import { ConversationTab } from '../ConversationTab'
import type { TaskRequestView } from '../taskEvents'
import { TaskSearchProvider } from '../taskSearch'
import { event, task } from './taskFixtures'
import { captureHighlights, layout, scrollPane } from './virtualLayout'

vi.mock('@/hooks/useHasPermission', () => ({
  useHasPermission: () => false,
}))

const HUMAN = { actor_id: 'dev', actor_kind: 'human' } as const

const LOG = [
  event(1, 'turn', { body: 'fix it' }, HUMAN),
  event(2, 'turn', { body: 'Looking at the build.', kind: 'thinking' }),
  event(3, 'tool.called', {
    arguments: { command: 'make test' },
    call_id: 'c3',
    result: 'tests passed',
    tool: 'Bash',
  }),
  event(4, 'turn', { body: 'fixed' }),
]

function renderTab(status: AgentTask['status'], events = LOG) {
  const t = task({ status }) as unknown as AgentTask
  return render(
    <div className="flex h-150 flex-col">
      <ConversationTab events={events} orgSlug="acme" requests={[]} task={t} />
    </div>,
  )
}

describe('ConversationTab', () => {
  let store: Map<string, string>
  beforeEach(() => {
    store = new Map()
    vi.mocked(window.localStorage.getItem).mockImplementation(
      (key: string) => store.get(key) ?? null,
    )
    vi.mocked(window.localStorage.setItem).mockImplementation(
      (key: string, value: string) => {
        store.set(key, value)
      },
    )
  })

  it('folds a finished turn and keeps the messages in view', () => {
    renderTab('closed')
    expect(screen.getByText('fix it')).toBeInTheDocument()
    expect(screen.getByText('fixed')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Worked for 3s/ }),
    ).toBeInTheDocument()
    expect(screen.queryByText(/Ran a command/)).not.toBeInTheDocument()
  })

  it('wraps a warning instead of clipping it', async () => {
    const user = userEvent.setup()
    const warning = `Retrying the build. ${'Step '.repeat(60)}then report.`
    renderTab('closed', [
      ...LOG.slice(0, 3),
      event(4, 'turn', { body: warning, kind: 'warning' }),
      event(5, 'turn', { body: 'fixed' }),
    ])
    await user.click(screen.getByRole('radio', { name: 'Verbose' }))
    const title = screen.getByText(warning)
    expect(title).not.toHaveClass('truncate')
    expect(title).toHaveClass('whitespace-pre-wrap')
  })

  it('opens the turn, then a call, one click at a time', async () => {
    const user = userEvent.setup()
    renderTab('closed')
    await user.click(screen.getByRole('button', { name: /Worked for/ }))
    await user.click(screen.getByRole('button', { name: /Ran a command/ }))
    const call = screen.getByRole('button', { name: /Bash make test/ })
    expect(screen.queryByText(/tests passed/)).not.toBeInTheDocument()
    await user.click(call)
    expect(screen.getByText(/tests passed/)).toBeInTheDocument()
  })

  it('opens every group in Verbose but no call, and keeps the mode', async () => {
    const user = userEvent.setup()
    renderTab('closed')
    await user.click(screen.getByRole('radio', { name: 'Verbose' }))
    expect(
      screen.getByRole('button', { name: /Bash make test/ }),
    ).toBeInTheDocument()
    expect(screen.queryByText(/tests passed/)).not.toBeInTheDocument()
    expect(store.get(MODE_KEY)).toBe('verbose')
    await user.click(screen.getByRole('button', { name: /Worked for/ }))
    expect(
      screen.queryByRole('button', { name: /Bash make test/ }),
    ).not.toBeInTheDocument()
  })

  describe('a turn another view asks for', () => {
    const TWO = [
      ...LOG,
      event(5, 'turn', { body: 'now test it' }, HUMAN),
      event(6, 'tool.called', {
        arguments: { command: 'make check' },
        call_id: 'c6',
        result: 'checked',
        tool: 'Bash',
      }),
      event(7, 'turn', { body: 'tested' }),
    ]
    const flashed = () => document.querySelector('[data-flash]')

    beforeEach(() => {
      vi.useFakeTimers()
    })
    afterEach(() => {
      vi.useRealTimers()
      window.history.replaceState(null, '', '/')
    })

    it('opens the turn and its work, flashes it, then fades', () => {
      window.history.replaceState(
        { idx: 0, key: 'reveal', usr: { revealSeq: 3 } },
        '',
        '/',
      )
      renderTab('closed', TWO)
      expect(flashed()).toHaveTextContent('fix it')
      expect(flashed()).not.toHaveTextContent('now test it')
      expect(flashed()).toHaveClass('bg-action/8')
      const [first, second] = screen.getAllByRole('button', {
        name: /Worked for/,
      })
      expect(first).toHaveAttribute('aria-expanded', 'true')
      expect(second).toHaveAttribute('aria-expanded', 'false')
      expect(
        screen.getByRole('button', { name: /Bash make test/ }),
      ).toBeInTheDocument()
      expect(window.history.state?.usr).toBeNull()
      act(() => {
        vi.advanceTimersByTime(1600)
      })
      expect(flashed()).toBeNull()
    })

    it('flashes the turn of a later event', () => {
      window.history.replaceState(
        { idx: 0, key: 'reveal', usr: { revealSeq: 6 } },
        '',
        '/',
      )
      renderTab('closed', TWO)
      expect(flashed()).toHaveTextContent('now test it')
    })

    it('flashes nothing without a request', () => {
      renderTab('closed', TWO)
      expect(flashed()).toBeNull()
    })

    it('flashes the turn of an event permalink and clears it', () => {
      window.history.replaceState(null, '', '/#e6')
      renderTab('closed', TWO)
      expect(flashed()).toHaveTextContent('now test it')
      expect(window.location.hash).toBe('')
    })

    it('opens the Agent call that holds a subagent event', () => {
      window.history.replaceState(
        { idx: 0, key: 'reveal', usr: { revealSeq: 2 } },
        '',
        '/',
      )
      renderTab('closed', [
        LOG[0],
        event(2, 'tool.called', {
          arguments: { command: 'ls' },
          call_id: 'c2',
          parent_call_id: 'task-1',
          result: 'a.py',
          tool: 'Bash',
        }),
        event(3, 'tool.called', {
          arguments: { description: 'look', subagent_type: 'search' },
          call_id: 'task-1',
          result: 'Found it.',
          tool: 'Task',
        }),
        event(4, 'turn', { body: 'fixed' }),
      ])
      expect(
        screen.getByRole('button', { name: /Bash ls/ }),
      ).toBeInTheDocument()
    })
  })

  it('keeps a turn the reader opened open across a mode change', async () => {
    const user = userEvent.setup()
    renderTab('closed')
    await user.click(screen.getByRole('button', { name: /Worked for/ }))
    await user.click(screen.getByRole('radio', { name: 'Compact' }))
    expect(
      screen.getByRole('button', { name: /Ran a command/ }),
    ).toBeInTheDocument()
  })

  it('shows the live work of a running turn and cannot fold it', () => {
    renderTab('running', LOG.slice(0, 3))
    expect(screen.getByText('Working…')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Bash make test/ }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /Working/ }),
    ).not.toBeInTheDocument()
  })

  it('sums up a finished turn in its footer, not a running one', () => {
    renderTab('closed')
    expect(screen.getByText('3s · 1 tool')).toBeInTheDocument()
  })

  it('does not show a paused task as working', () => {
    renderTab('paused', LOG.slice(0, 3))
    expect(screen.queryByText('Working…')).not.toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Worked for/ }),
    ).toBeInTheDocument()
  })

  it('gives a reply-only turn a footer too', () => {
    renderTab('closed', [LOG[0], event(2, 'turn', { body: 'Hi.' })])
    expect(screen.getByText('1s')).toBeInTheDocument()
  })

  it('has no footer while the turn runs', () => {
    renderTab('running', LOG.slice(0, 3))
    expect(screen.queryByText(/1 tool/)).not.toBeInTheDocument()
  })

  it('copies the conversation as Markdown', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn(() => Promise.resolve())
    renderTab('closed')
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    await user.click(screen.getByRole('button', { name: /^Copy/ }))
    await user.click(screen.getByRole('menuitem', { name: 'Copy as Markdown' }))
    expect(writeText).toHaveBeenCalledWith(
      expect.stringMatching(
        /^# Fix the build\n\n> Find why the build fails\.\n/,
      ),
    )
    expect(
      await screen.findByRole('button', { name: /Copied Markdown/ }),
    ).toBeInTheDocument()
  })

  it('copies the task and its events as JSON', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn((_: string) => Promise.resolve())
    renderTab('closed')
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    await user.click(screen.getByRole('button', { name: /^Copy/ }))
    await user.click(screen.getByRole('menuitem', { name: 'Copy as JSON' }))
    const copied = JSON.parse(writeText.mock.calls[0][0]) as {
      events: unknown[]
      task: { title: string }
    }
    expect(copied.task.title).toBe('Fix the build')
    expect(copied.events.length).toBeGreaterThan(0)
  })

  it('resets Copied two seconds after the last click', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
      renderTab('closed')
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: { writeText: vi.fn(() => Promise.resolve()) },
      })
      const button = screen.getByRole('button', { name: /^Copy/ })
      const copyMarkdown = async () => {
        await user.click(button)
        await user.click(
          screen.getByRole('menuitem', { name: 'Copy as Markdown' }),
        )
      }
      await copyMarkdown()
      await act(() => vi.advanceTimersByTimeAsync(1500))
      await copyMarkdown()
      await act(() => vi.advanceTimersByTimeAsync(1000))
      expect(button).toHaveAccessibleName('Copied Markdown')
      await act(() => vi.advanceTimersByTimeAsync(1100))
      expect(button).toHaveAccessibleName('Copy')
    } finally {
      vi.useRealTimers()
    }
  })

  it('sets subagent work apart under its call', async () => {
    const user = userEvent.setup()
    renderTab('closed', [
      LOG[0],
      event(2, 'tool.called', {
        arguments: { command: 'ls' },
        call_id: 'c2',
        parent_call_id: 'task-1',
        result: 'a.py',
        tool: 'Bash',
      }),
      event(3, 'tool.called', {
        arguments: { description: 'look', subagent_type: 'search' },
        call_id: 'task-1',
        result: 'Found it.',
        tool: 'Task',
      }),
      event(4, 'turn', { body: 'fixed' }),
    ])
    await user.click(screen.getByRole('radio', { name: 'Verbose' }))
    await user.click(screen.getByRole('button', { name: /Subagent search/ }))
    expect(screen.getByText(/search subagent/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Bash ls/ })).toBeInTheDocument()
  })

  it('labels a subagent message as a message and hides usage', async () => {
    const user = userEvent.setup()
    renderTab('closed', [
      LOG[0],
      event(2, 'turn', { body: 'Looking around.', parent_call_id: 'task-1' }),
      event(3, 'usage.reported', { parent_call_id: 'task-1', tokens_in: 9 }),
      event(4, 'tool.called', {
        arguments: { subagent_type: 'search' },
        call_id: 'task-1',
        result: 'Found it.',
        tool: 'Task',
      }),
      event(5, 'turn', { body: 'fixed' }),
    ])
    await user.click(screen.getByRole('radio', { name: 'Verbose' }))
    await user.click(screen.getByRole('button', { name: /Subagent/ }))
    const marker = screen
      .getByText('search subagent · 1 step')
      .closest('[data-slot="marker"]')
    expect(marker?.nextElementSibling?.children).toHaveLength(1)
    expect(
      screen.getByRole('button', { name: /^Looking around\.$/ }),
    ).toBeInTheDocument()
  })

  it('keeps a running subagent open once its call is written', async () => {
    const user = userEvent.setup()
    const child = event(2, 'tool.called', {
      arguments: { command: 'ls' },
      call_id: 'c2',
      parent_call_id: 'task-1',
      result: 'a.py',
      tool: 'Bash',
    })
    const t = task({ status: 'running' }) as unknown as AgentTask
    const view = (events: ReturnType<typeof event>[]) => (
      <div className="flex h-150 flex-col">
        <ConversationTab
          events={events}
          orgSlug="acme"
          requests={[]}
          task={t}
        />
      </div>
    )
    const { rerender } = render(view([LOG[0], child]))
    expect(screen.queryByRole('button', { name: /Bash ls/ })).toBeNull()
    await user.click(screen.getByRole('button', { name: /Subagent Running/ }))
    expect(screen.getByRole('button', { name: /Bash ls/ })).toBeInTheDocument()
    expect(screen.getByText('Subagent · 1 step')).toBeInTheDocument()
    rerender(
      view([
        LOG[0],
        child,
        event(3, 'tool.called', {
          arguments: { description: 'look', subagent_type: 'search' },
          call_id: 'task-1',
          result: 'Found it.',
          tool: 'Task',
        }),
      ]),
    )
    expect(
      screen.getByRole('button', { name: /Subagent search/ }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Bash ls/ })).toBeInTheDocument()
  })

  it.each([
    ['paused', 'Not finished yet'],
    ['closed', 'Did not finish'],
  ] as const)(
    'labels an unwritten subagent call on a %s task',
    async (status, text) => {
      const user = userEvent.setup()
      renderTab(status, [
        LOG[0],
        event(2, 'turn', { body: 'Looking around.', parent_call_id: 'task-1' }),
      ])
      await user.click(screen.getByRole('radio', { name: 'Verbose' }))
      expect(
        screen.getByRole('button', { name: new RegExp(`Subagent ${text}`) }),
      ).toBeInTheDocument()
    },
  )

  it('toggles a turn without pointing at a missing region', async () => {
    const user = userEvent.setup()
    renderTab('closed')
    const header = screen.getByRole('button', { name: /Worked for 3s/ })
    expect(header).toHaveAttribute('aria-expanded', 'false')
    expect(header).not.toHaveAttribute('aria-controls')
    await user.click(header)
    expect(header).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText(/ran a command/i)).toBeInTheDocument()
  })

  it('opens with what started the task', () => {
    const t = task({
      description: 'Review the ingest service',
      origin: { kind: 'webhook' },
      status: 'closed',
    }) as unknown as AgentTask
    render(
      <div className="flex h-150 flex-col">
        <ConversationTab events={LOG} orgSlug="acme" requests={[]} task={t} />
      </div>,
    )
    expect(screen.getByText('Review the ingest service')).toBeInTheDocument()
    expect(screen.getByText('Webhook')).toBeInTheDocument()
  })

  it('does not repeat a request a person already sent', () => {
    const t = task({
      description: 'fix it',
      status: 'closed',
    }) as unknown as AgentTask
    render(
      <div className="flex h-150 flex-col">
        <ConversationTab events={LOG} orgSlug="acme" requests={[]} task={t} />
      </div>,
    )
    expect(screen.getAllByText('fix it')).toHaveLength(1)
  })

  it('leaves the start and the close to the footer and outcome', () => {
    renderTab('closed', [
      event(1, 'state.changed', { from: 'queued', to: 'running' }),
      ...LOG,
      event(5, 'state.changed', { from: 'running', to: 'paused' }),
      event(6, 'state.changed', { from: 'paused', to: 'closed' }),
    ])
    expect(screen.queryByText('Started')).toBeNull()
    expect(screen.queryByText('Stopped')).toBeNull()
    expect(screen.getByText('Paused')).toBeInTheDocument()
  })

  it('says when nothing matches, hiding the ask, and clears the search', async () => {
    const user = userEvent.setup()
    renderTab('closed')
    expect(screen.getByText('Find why the build fails.')).toBeInTheDocument()
    const box = screen.getByRole('searchbox', { name: 'Search conversation' })
    await user.type(box, 'zzqx-no-match')
    expect(screen.getByText('No matches')).toBeInTheDocument()
    expect(
      screen.getByText('Nothing in this view matches “zzqx-no-match”.'),
    ).toBeInTheDocument()
    expect(screen.queryByText('Find why the build fails.')).toBeNull()
    const empty = screen
      .getByText('No matches')
      .closest('[data-slot="empty"]') as HTMLElement
    expect(empty).toHaveAttribute('data-search-skip')
    await user.click(
      within(empty).getByRole('button', { name: 'Clear search' }),
    )
    expect(box).toHaveValue('')
    expect(screen.queryByText('No matches')).toBeNull()
    expect(screen.getByText('Find why the build fails.')).toBeInTheDocument()
    expect(screen.getByText('fixed')).toBeInTheDocument()
  })

  it('keeps no fold click made while a search holds rows open', async () => {
    const user = userEvent.setup()
    renderTab('closed')
    await user.click(screen.getByRole('radio', { name: 'Verbose' }))
    const box = screen.getByRole('searchbox', { name: 'Search conversation' })
    await user.type(box, 'make')
    await user.click(screen.getByRole('button', { name: /Ran a command/ }))
    await user.clear(box)
    expect(
      screen.getByRole('button', { name: /Bash make test/ }),
    ).toBeInTheDocument()
  })

  it('shows the cut part of an output a search matches', async () => {
    const user = userEvent.setup()
    const result = Array.from({ length: 60 }, (_, i) =>
      i === 50 ? 'the hidden clue' : `line ${i}`,
    ).join('\n')
    const t = task({ status: 'closed' }) as unknown as AgentTask
    render(
      <TaskSearchProvider>
        <div className="flex h-150 flex-col">
          <ConversationTab
            events={[
              LOG[0],
              event(2, 'tool.called', {
                arguments: { command: 'make test' },
                call_id: 'c2',
                result,
                tool: 'Bash',
              }),
              event(3, 'turn', { body: 'fixed' }),
            ]}
            orgSlug="acme"
            requests={[]}
            task={t}
          />
        </div>
      </TaskSearchProvider>,
    )
    expect(screen.queryByText(/the hidden clue/)).toBeNull()
    await user.type(
      screen.getByRole('searchbox', { name: 'Search conversation' }),
      'hidden clue',
    )
    expect(screen.getByText(/the hidden clue/)).toBeInTheDocument()
  })

  it('keeps the ask when only the ask matches the search', async () => {
    const user = userEvent.setup()
    renderTab('closed')
    const box = screen.getByRole('searchbox', { name: 'Search conversation' })
    await user.type(box, 'why the build')
    expect(screen.queryByText('No matches')).toBeNull()
    expect(screen.queryByText('No conversation yet.')).toBeNull()
    expect(
      screen.getByText(
        (_, el) =>
          el?.tagName === 'P' && el.textContent === 'Find why the build fails.',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText('fixed')).toBeNull()
  })

  it('shows all of a long ask when the search matches past its preview', async () => {
    const user = userEvent.setup()
    const description = `${'word '.repeat(150)}the hidden clue`
    const t = task({ description, status: 'closed' }) as unknown as AgentTask
    render(
      <div className="flex h-150 flex-col">
        <ConversationTab events={LOG} orgSlug="acme" requests={[]} task={t} />
      </div>,
    )
    expect(screen.queryByText(/the hidden clue/)).toBeNull()
    await user.type(
      screen.getByRole('searchbox', { name: 'Search conversation' }),
      'hidden clue',
    )
    expect(screen.getByText(/the hidden clue$/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Show all' })).toBeNull()
  })

  it('says when there is nothing yet', () => {
    renderTab('running', [])
    expect(screen.getByText('No conversation yet.')).toBeInTheDocument()
  })

  it.each(['tests passed', 'Looking at the build'])(
    'finds a turn by text only its work holds: %s',
    async (text) => {
      const user = userEvent.setup()
      renderTab('closed')
      await user.type(
        screen.getByRole('searchbox', { name: 'Search conversation' }),
        text,
      )
      expect(screen.queryByText(/No turns match/)).toBeNull()
      expect(screen.getByText('fixed')).toBeInTheDocument()
    },
  )

  it('shows what a person answered to a request', () => {
    renderTab('closed', [
      ...LOG,
      event(
        5,
        'request.resolved',
        {
          answer: 'Use the staging database',
          constraints: ['No writes'],
          kind: 'feedback',
          request_id: 'r1',
          resolved_by: 'dev',
          status: 'answered',
        },
        { actor_id: 'dev', actor_kind: 'human' },
      ),
    ])
    expect(screen.getByText('Use the staging database')).toBeInTheDocument()
    expect(screen.getByText('No writes')).toBeInTheDocument()
  })
})

describe('ConversationTab with many turns', () => {
  const MANY = Array.from({ length: 80 }, (_, i) => [
    event(1 + i * 2, 'turn', { body: `ask ${i}` }, HUMAN),
    event(2 + i * 2, 'turn', { body: `reply ${i}` }),
  ]).flat()
  const isPane = (el: HTMLElement) =>
    el.getAttribute('aria-label') === 'Conversation'
  const pane = () => screen.getByRole('region', { name: 'Conversation' })
  const content = (el: HTMLElement) =>
    parseFloat(
      el.querySelector<HTMLElement>('[style*="height"]')?.style.height ?? '0',
    )
  const view = (status: AgentTask['status'], events = MANY) => {
    const t = task({ status }) as unknown as AgentTask
    return (
      <div className="flex h-150 flex-col">
        <ConversationTab
          events={events}
          orgSlug="acme"
          requests={[]}
          task={t}
        />
      </div>
    )
  }
  const replies = () => screen.queryAllByText(/^reply \d+$/)
  const flashed = () => document.querySelector<HTMLElement>('[data-flash]')
  const scrollTo = vi.fn()
  const original = Element.prototype.scrollTo
  let spy: ReturnType<typeof layout>
  beforeEach(() => {
    spy = layout({ content, isPane, pane: 600, row: 100 })
    scrollTo.mockReset()
    Element.prototype.scrollTo = scrollTo
  })
  afterEach(() => {
    cleanup()
    spy.mockRestore()
    Element.prototype.scrollTo = original
    vi.unstubAllGlobals()
    window.history.replaceState(null, '', '/')
  })

  it('renders only the turns in view and opens at the latest', async () => {
    render(view('closed'))
    await waitFor(() =>
      expect(screen.getByText('reply 79')).toBeInTheDocument(),
    )
    expect(screen.queryByText('reply 0')).not.toBeInTheDocument()
    expect(replies().length).toBeLessThan(20)
  })

  it('follows the bottom while the task runs, until the reader scrolls up', async () => {
    const { rerender } = render(view('running', MANY.slice(0, 100)))
    await waitFor(() =>
      expect(screen.getByText('reply 49')).toBeInTheDocument(),
    )
    const latest = screen.getByRole('button', { name: 'Scroll to end' })
    expect(latest).toHaveAttribute('data-active', 'false')
    rerender(view('running', MANY.slice(0, 102)))
    await waitFor(() =>
      expect(screen.getByText('reply 50')).toBeInTheDocument(),
    )
    expect(pane().scrollTop).toBe(content(pane()) - 600)
    scrollPane(pane(), 0)
    expect(latest).toHaveAttribute('data-active', 'true')
    rerender(view('running', MANY.slice(0, 104)))
    expect(pane().scrollTop).toBe(0)
    expect(screen.queryByText('reply 51')).not.toBeInTheDocument()
  })

  it('jumps to the latest turn and keeps following it', async () => {
    const user = userEvent.setup()
    scrollTo.mockImplementation(function (
      this: Element,
      options: ScrollToOptions,
    ) {
      this.scrollTop =
        options.behavior === 'smooth'
          ? this.scrollTop + 100
          : (options.top ?? 0)
    })
    const { rerender } = render(view('running', MANY.slice(0, 100)))
    await waitFor(() =>
      expect(screen.getByText('reply 49')).toBeInTheDocument(),
    )
    scrollPane(pane(), 0)
    const latest = screen.getByRole('button', { name: 'Scroll to end' })
    await waitFor(() => expect(latest).toHaveAttribute('data-active', 'true'))
    await user.click(latest)
    await waitFor(() => expect(pane().scrollTop).toBe(content(pane()) - 600))
    rerender(view('running', MANY.slice(0, 102)))
    await waitFor(() =>
      expect(screen.getByText('reply 50')).toBeInTheDocument(),
    )
    await waitFor(() => expect(pane().scrollTop).toBe(content(pane()) - 600))
  })

  it('keeps a long ask shown in full after it scrolls out of view', async () => {
    const user = userEvent.setup()
    const description = `${'word '.repeat(150)}the end`
    const t = task({ description, status: 'closed' }) as unknown as AgentTask
    render(
      <div className="flex h-150 flex-col">
        <ConversationTab events={MANY} orgSlug="acme" requests={[]} task={t} />
      </div>,
    )
    await waitFor(() =>
      expect(screen.getByText('reply 79')).toBeInTheDocument(),
    )
    scrollPane(pane(), 0)
    await user.click(await screen.findByRole('button', { name: 'Show all' }))
    expect(screen.getByText(/the end$/)).toBeInTheDocument()
    scrollPane(pane(), content(pane()) - 600)
    const last = await screen.findByText('reply 79')
    last.tabIndex = -1
    act(() => last.focus())
    await waitFor(() =>
      expect(screen.queryByText(/the end$/)).not.toBeInTheDocument(),
    )
    scrollPane(pane(), 0)
    expect(await screen.findByText(/the end$/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show less' })).toBeVisible()
  })

  it('keeps a turn with an open request rendered while it is out of view', async () => {
    const events = [
      event(1, 'turn', { body: 'ask 0' }, HUMAN),
      event(2, 'request.opened', {
        kind: 'feedback',
        request_id: 'r1',
        title: 'Pick a database',
      }),
      event(3, 'turn', { body: 'reply 0' }),
      ...MANY.slice(2).map((e) => ({ ...e, seq: e.seq + 1 })),
    ]
    const request: TaskRequestView = {
      answer: null,
      artifact_digests: null,
      artifacts: [],
      expires_at: null,
      id: 'r1',
      kind: 'feedback',
      opened_at: '2026-10-08T12:00:02Z',
      opened_by: null,
      options: [],
      resolved_at: null,
      resolved_by: null,
      status: 'open',
      title: 'Pick a database',
      why: null,
    }
    const t = task({ status: 'running' }) as unknown as AgentTask
    render(
      <div className="flex h-150 flex-col">
        <ConversationTab
          events={events}
          orgSlug="acme"
          requests={[request]}
          task={t}
        />
      </div>,
    )
    await waitFor(() =>
      expect(screen.getByText('reply 79')).toBeInTheDocument(),
    )
    expect(screen.getByText('ask 0')).toBeInTheDocument()
    expect(screen.queryByText('ask 1')).not.toBeInTheDocument()
  })

  it('stays where the reader opens a fold at the bottom', async () => {
    const user = userEvent.setup()
    const observers: { els: Set<Element>; fire: ResizeObserverCallback }[] = []
    vi.stubGlobal(
      'ResizeObserver',
      class {
        els = new Set<Element>()
        constructor(fire: ResizeObserverCallback) {
          observers.push({ els: this.els, fire })
        }
        disconnect() {
          this.els.clear()
        }
        observe(el: Element) {
          this.els.add(el)
        }
        unobserve(el: Element) {
          this.els.delete(el)
        }
      },
    )
    spy.mockRestore()
    spy = layout({
      content,
      isPane,
      pane: 600,
      row: (el) => 100 + 10 * el.querySelectorAll('*').length,
    })
    render(
      view('closed', [
        ...MANY,
        event(
          161,
          'turn',
          { body: 'ask 80' },
          { ...HUMAN, at: '2026-10-08T12:05:00Z' },
        ),
        event(
          162,
          'tool.called',
          {
            arguments: { command: 'make test' },
            call_id: 'c162',
            result: 'tests passed',
            tool: 'Bash',
          },
          { at: '2026-10-08T12:05:01Z' },
        ),
        event(
          163,
          'turn',
          { body: 'reply 80' },
          { at: '2026-10-08T12:05:09Z' },
        ),
      ]),
    )
    await waitFor(() =>
      expect(screen.getByText('reply 80')).toBeInTheDocument(),
    )
    await waitFor(() => expect(pane().scrollTop).toBe(content(pane()) - 600))
    const before = pane().scrollTop
    await user.click(screen.getByRole('button', { name: /Worked for/ }))
    const row = screen
      .getByText('reply 80')
      .closest<HTMLElement>('[data-index]')!
    act(() => {
      for (const o of observers)
        if (o.els.has(row))
          o.fire(
            [{ target: row } as unknown as ResizeObserverEntry],
            o as unknown as ResizeObserver,
          )
    })
    expect(content(pane()) - 600).toBeGreaterThan(before)
    expect(pane().scrollTop).toBe(before)
  })

  it('scrolls to a far turn another view asks for, and flashes it', async () => {
    window.history.replaceState(
      { idx: 0, key: 'reveal', usr: { revealSeq: 3 } },
      '',
      '/',
    )
    render(view('closed'))
    await waitFor(() => expect(flashed()).toHaveTextContent('ask 1'))
    expect(flashed()).not.toHaveTextContent('ask 2')
    const item = flashed()!.closest<HTMLElement>('[data-index]')!
    await waitFor(() =>
      expect(scrollTo).toHaveBeenLastCalledWith(
        expect.objectContaining({
          top: Number(
            /translateY\(([\d.]+)px\)/.exec(item.style.transform)?.[1],
          ),
        }),
      ),
    )
    expect(screen.queryByText('reply 79')).toBeInTheDocument()
  })

  it('scrolls to an event link once the events load', async () => {
    window.history.replaceState(null, '', '/#e150')
    const { rerender } = render(view('running', []))
    expect(flashed()).toBeNull()
    expect(window.location.hash).toBe('#e150')
    rerender(view('running'))
    await waitFor(() => expect(flashed()).toHaveTextContent('reply 74'))
    expect(window.location.hash).toBe('')
    expect(scrollTo).toHaveBeenCalled()
  })

  it('filters every turn from the data and marks what renders', async () => {
    const { marked, mutate } = captureHighlights()
    const user = userEvent.setup()
    render(view('closed'))
    await user.type(
      screen.getByRole('searchbox', { name: 'Search conversation' }),
      'reply 7',
    )
    expect(screen.queryByText('reply 8')).not.toBeInTheDocument()
    expect(screen.queryByText('ask 8')).not.toBeInTheDocument()
    scrollPane(pane(), 1_000_000)
    mutate()
    await waitFor(() => expect(marked.current).toContain('reply 79'))
    expect(marked.current).not.toContain('reply 7')
    scrollPane(pane(), 0)
    mutate()
    await waitFor(() => expect(marked.current).toContain('reply 7'))
    expect(marked.current.every((text) => /^reply 7\d?$/.test(text))).toBe(true)
  })

  it('copies every turn, not only the ones in view', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn((_: string) => Promise.resolve())
    render(view('closed'))
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    await waitFor(() =>
      expect(screen.getByText('reply 79')).toBeInTheDocument(),
    )
    expect(screen.queryByText('reply 0')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /^Copy/ }))
    await user.click(screen.getByRole('menuitem', { name: 'Copy as Markdown' }))
    const copied = writeText.mock.calls[0][0]
    expect(copied).toContain('reply 0')
    expect(copied).toContain('reply 79')
  })
})
