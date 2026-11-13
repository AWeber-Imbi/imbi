import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { render, screen } from '@/test/utils'
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

  it('says when there is nothing yet', () => {
    renderTab('running', [])
    expect(screen.getByText('No conversation yet.')).toBeInTheDocument()
  })
})
