import { Route, Routes } from 'react-router-dom'

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import * as endpoints from '@/api/endpoints'
import { fireEvent, render, screen, waitFor, within } from '@/test/utils'

import { AgentsArea } from '../AgentsArea'
import { EVENT_POLL_MS } from '../taskQueries'
import { agent, catalog, promptVersion } from './fixtures'
import { event, task } from './taskFixtures'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  controlAgentTask: vi.fn(),
  countWaitingAgentTasks: vi.fn(),
  createAgentTask: vi.fn(),
  getAgentTask: vi.fn(),
  getAgentToolCatalog: vi.fn(),
  listAdminUsers: vi.fn(),
  listAgents: vi.fn(),
  listAgentTaskEvents: vi.fn(),
  listAgentTasks: vi.fn(),
  reassignAgentTask: vi.fn(),
  replyAgentTask: vi.fn(),
  resolveAgentTaskRequest: vi.fn(),
  resolvePrompt: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/ThemeContext', () => ({
  useTheme: () => ({ isDarkMode: false }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ user: { is_admin: true, permissions: [] } }),
}))

const BLOCKED = task({
  blocked_since: '2026-10-08T12:00:03Z',
  last_seq: 3,
  short_id: 'T-3',
  status: 'blocked',
  title: 'Apply the fix',
})

const LOG = [
  event(
    1,
    'task.created',
    {},
    { actor_id: 'dev@example.com', actor_kind: 'human', channel: 'web' },
  ),
  event(2, 'turn', { body: 'I read the task.' }),
  event(3, 'request.opened', {
    kind: 'feedback',
    options: ['yes', 'no'],
    request_id: 'req-1',
    title: 'Apply the fix?',
    why: 'One question.',
  }),
]

function renderAt(path: string) {
  window.history.pushState({}, '', path)
  return render(
    <Routes>
      <Route
        element={<AgentsArea />}
        path="/agents/:section?/:slug?/:action?"
      />
    </Routes>,
  )
}

describe('Tasks', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.listAgents).mockResolvedValue([agent()])
    vi.mocked(endpoints.listAdminUsers).mockResolvedValue([])
    vi.mocked(endpoints.countWaitingAgentTasks).mockResolvedValue({ count: 2 })
    vi.mocked(endpoints.listAgentTasks).mockImplementation(
      async (_org, params) =>
        params.status?.includes('closed')
          ? [
              task({
                closed_at: '2026-10-08T11:00:00Z',
                outcome: 'done_acted',
                short_id: 'T-1',
                status: 'closed',
                title: 'Old work',
              }),
            ]
          : [
              task({ short_id: 'T-4', status: 'running', title: 'Busy' }),
              BLOCKED,
              task({
                blocked_since: '2026-10-08T09:00:00Z',
                owner: 'pat@example.com',
                short_id: 'T-2',
                status: 'blocked',
                title: 'Waiting longest',
              }),
            ],
    )
    vi.mocked(endpoints.getAgentTask).mockResolvedValue(BLOCKED)
    vi.mocked(endpoints.listAgentTaskEvents).mockImplementation(
      async (_org, _id, afterSeq) => LOG.filter((e) => e.seq > afterSeq),
    )
  })

  it('groups the inbox, oldest block first, with the waiting count', async () => {
    renderAt('/agents/tasks')
    const input = await screen.findByRole('region', {
      name: 'Human input required',
    })
    expect(
      within(input)
        .getAllByRole('link')
        .map((a) => a.textContent),
    ).toEqual([
      expect.stringContaining('Waiting longest'),
      expect.stringContaining('Apply the fix'),
    ])
    const sections = screen
      .getAllByRole('region')
      .map((s) => s.getAttribute('aria-label'))
    expect(sections).toEqual([
      'Human input required',
      'Running',
      'Recently closed',
    ])
    expect(await screen.findByTitle('2 waiting on you')).toBeInTheDocument()
  })

  it('filters by text on the server, and by state and mine', async () => {
    renderAt('/agents/tasks')
    await screen.findByText('Busy')
    fireEvent.change(screen.getByLabelText('Filter tasks'), {
      target: { value: 'billing' },
    })
    await waitFor(() =>
      expect(endpoints.listAgentTasks).toHaveBeenCalledWith(
        'acme',
        expect.objectContaining({ q: 'billing' }),
        expect.anything(),
      ),
    )
    fireEvent.click(screen.getByRole('button', { name: 'My tasks' }))
    await waitFor(() =>
      expect(endpoints.listAgentTasks).toHaveBeenCalledWith(
        'acme',
        expect.objectContaining({ mine: true, q: 'billing' }),
        expect.anything(),
      ),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Filter by State' }))
    fireEvent.click(await screen.findByLabelText('Running'))
    await waitFor(() =>
      expect(screen.queryByText('Apply the fix')).not.toBeInTheDocument(),
    )
    expect(screen.getByText('Busy')).toBeInTheDocument()
    expect(screen.getByText('1 of 4 tasks')).toBeInTheDocument()
  })

  it('answers a feedback request', async () => {
    vi.mocked(endpoints.resolveAgentTaskRequest).mockResolvedValue({})
    renderAt('/agents/tasks/T-3/input')
    fireEvent.click(await screen.findByRole('button', { name: 'yes' }))
    await waitFor(() =>
      expect(endpoints.resolveAgentTaskRequest).toHaveBeenCalledWith(
        'acme',
        'T-3',
        'req-1',
        { answer: 'yes', status: 'answered' },
      ),
    )
  })

  it('collapses a request that someone else resolved (I4)', async () => {
    vi.mocked(endpoints.resolveAgentTaskRequest).mockRejectedValue(
      new ApiError(409, 'Conflict', {
        detail: {
          error: 'request_resolved',
          message: 'Request req-1 is answered by pat@example.com',
          resolved_at: '2026-10-08T12:00:05Z',
          resolved_by: 'pat@example.com',
          status: 'answered',
        },
      }),
    )
    renderAt('/agents/tasks/T-3/input')
    fireEvent.click(await screen.findByRole('button', { name: 'no' }))
    expect(
      await screen.findByText('Answered by pat@example.com'),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'yes' }),
    ).not.toBeInTheDocument()
    expect(screen.queryByText('Waiting on you')).not.toBeInTheDocument()
  })

  it('sends Reply and hold', async () => {
    vi.mocked(endpoints.replyAgentTask).mockResolvedValue(BLOCKED)
    renderAt('/agents/tasks/T-3/conversation')
    fireEvent.change(await screen.findByLabelText('Reply'), {
      target: { value: 'Wait for me.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Reply and hold' }))
    await waitFor(() =>
      expect(endpoints.replyAgentTask).toHaveBeenCalledWith(
        'acme',
        'T-3',
        'Wait for me.',
        true,
      ),
    )
    await waitFor(() => expect(screen.getByLabelText('Reply')).toHaveValue(''))
  })

  it(
    'appends new events by seq without a reload (O4)',
    async () => {
      renderAt('/agents/tasks/T-3/conversation')
      await screen.findByText('I read the task.')
      LOG.push(event(4, 'turn', { body: 'A new turn.' }))
      try {
        expect(
          await screen.findByText(
            'A new turn.',
            {},
            { timeout: EVENT_POLL_MS + 2000 },
          ),
        ).toBeInTheDocument()
      } finally {
        LOG.pop()
      }
      expect(screen.getByText('I read the task.')).toBeInTheDocument()
      expect(endpoints.listAgentTaskEvents).toHaveBeenCalledWith(
        'acme',
        'T-3',
        3,
        expect.any(Number),
        expect.anything(),
      )
    },
    EVENT_POLL_MS + 5000,
  )

  it('runs an agent from its detail page', async () => {
    vi.mocked(endpoints.resolvePrompt).mockResolvedValue({
      label: 'stable',
      ref: 'agents/mender@stable',
      version: promptVersion(),
    })
    vi.mocked(endpoints.getAgentToolCatalog).mockResolvedValue(catalog())
    vi.mocked(endpoints.createAgentTask).mockResolvedValue(
      task({ short_id: 'T-9' }),
    )
    renderAt('/agents/manage/mender')
    fireEvent.click(await screen.findByRole('button', { name: 'Run' }))
    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'Check the build' },
    })
    fireEvent.change(screen.getByLabelText('Instruction'), {
      target: { value: 'Find why it fails.' },
    })
    fireEvent.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Run' }),
    )
    await waitFor(() =>
      expect(endpoints.createAgentTask).toHaveBeenCalledWith('acme', {
        agent_slug: 'mender',
        description: 'Find why it fails.',
        title: 'Check the build',
      }),
    )
    await waitFor(() =>
      expect(window.location.pathname).toBe('/agents/tasks/T-9'),
    )
  })
})
