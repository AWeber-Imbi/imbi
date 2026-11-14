import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { act, render, screen } from '@/test/utils'
import type { AgentTask } from '@/types'

import { MODE_KEY } from '../conversationMode'
import { ConversationTab } from '../ConversationTab'
import { event, task } from './taskFixtures'

vi.mock('@/hooks/useHasPermission', () => ({
  useHasPermission: () => false,
}))

const LOG = [
  event(
    1,
    'turn',
    { body: 'fix it' },
    { actor_id: 'dev', actor_kind: 'human' },
  ),
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
    await user.click(screen.getByRole('button', { name: /Copy as Markdown/ }))
    expect(writeText).toHaveBeenCalledWith(
      expect.stringMatching(/^# Fix the build\n/),
    )
    expect(
      await screen.findByRole('button', { name: /Copied/ }),
    ).toBeInTheDocument()
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
      const button = screen.getByRole('button', { name: /Copy as Markdown/ })
      await user.click(button)
      await act(() => vi.advanceTimersByTimeAsync(1500))
      await user.click(button)
      await act(() => vi.advanceTimersByTimeAsync(1000))
      expect(button).toHaveTextContent('Copied')
      await act(() => vi.advanceTimersByTimeAsync(1100))
      expect(button).toHaveTextContent('Copy as Markdown')
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

  it('says when there is nothing yet', () => {
    renderTab('running', [])
    expect(screen.getByText('No conversation yet.')).toBeInTheDocument()
  })
})
