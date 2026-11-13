import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { render, screen, within } from '@/test/utils'
import type { AgentTask } from '@/types'

import { formatElapsed } from '../taskEvents'
import { TaskLogTab } from '../TaskLogTab'
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
  event(3, 'tool.called', {
    arguments: { command: 'make test' },
    call_id: 'c3',
    duration_ms: 1500,
    result: 'tests passed',
    tool: 'Bash',
  }),
  event(4, 'turn', { body: 'fixed' }),
]

function renderLog(path = '/t/log') {
  window.history.pushState({}, '', path)
  const t = task({ status: 'closed' }) as unknown as AgentTask
  return render(
    <div className="flex h-150 flex-col">
      <TaskLogTab events={LOG} orgSlug="acme" requests={[]} task={t} />
    </div>,
  )
}

const inspector = () =>
  screen.queryByRole('complementary', { name: 'Event inspector' })

describe('TaskLogTab inspector', () => {
  beforeEach(() => window.history.pushState({}, '', '/'))

  it('opens on the event of a deep link', () => {
    renderLog('/t/log#e3')
    const panel = inspector()!
    expect(within(panel).getByRole('heading')).toHaveTextContent('Bash')
    expect(within(panel).getByText(formatElapsed(1500))).toBeInTheDocument()
    expect(
      within(panel).getByText(/"command": "make test"/),
    ).toBeInTheDocument()
  })

  it('opens when the reader picks a row, and shows the output', async () => {
    const user = userEvent.setup()
    renderLog()
    expect(inspector()).toBeNull()
    const row = document.getElementById('e3')!
    await user.click(within(row).getByTitle('Link to this event'))
    const panel = inspector()!
    expect(row).toHaveAttribute('aria-current', 'true')
    await user.click(within(panel).getByRole('tab', { name: 'Output' }))
    expect(within(panel).getByText('tests passed')).toBeInTheDocument()
    await user.click(within(panel).getByRole('tab', { name: 'Raw' }))
    expect(within(panel).getByText(/"call_id": "c3"/)).toBeInTheDocument()
  })

  it('closes and drops the hash', async () => {
    const user = userEvent.setup()
    renderLog('/t/log#e4')
    expect(within(inspector()!).getByText('fixed')).toBeInTheDocument()
    await user.click(
      screen.getByRole('button', { name: 'Close the inspector' }),
    )
    expect(inspector()).toBeNull()
    expect(window.location.hash).toBe('')
  })
})
