import { Route, Routes } from 'react-router-dom'

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import * as endpoints from '@/api/endpoints'
import { act, fireEvent, render, screen, waitFor, within } from '@/test/utils'

import { AgentsArea } from '../AgentsArea'
import { EVENT_POLL_MS } from '../taskQueries'
import { agent, catalog, promptVersion } from './fixtures'
import { event, task } from './taskFixtures'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  controlAgentTask: vi.fn(),
  countWaitingAgentTasks: vi.fn(),
  createAgentTask: vi.fn(),
  deleteAgentTask: vi.fn(),
  getAgentTask: vi.fn(),
  getAgentToolCatalog: vi.fn(),
  getProjectsSlim: vi.fn(),
  listAdminUsers: vi.fn(),
  listAgents: vi.fn(),
  listAgentTaskEvents: vi.fn(),
  listAgentTaskPage: vi.fn(),
  listAgentTasks: vi.fn(),
  reassignAgentTask: vi.fn(),
  replyAgentTask: vi.fn(),
  resolveAgentTaskRequest: vi.fn(),
  resolvePrompt: vi.fn(),
  retryAgentTask: vi.fn(),
}))

const ORGS = vi.hoisted(() => [{ slug: 'acme' }, { slug: 'beta' }])
const setSelectedOrganization = vi.hoisted(() => vi.fn())

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({
    organizations: ORGS,
    selectedOrganization: ORGS[0],
    setSelectedOrganization,
  }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/ThemeContext', () => ({
  useTheme: () => ({ isDarkMode: false }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    user: {
      is_admin: true,
      organizations: [
        { organization_slug: 'acme', permissions: [] },
        { organization_slug: 'beta', permissions: [] },
      ],
      permissions: [],
    },
  }),
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

/** The sentinel observers; `scrollToEnd` shows each sentinel. */
let observers: IntersectionObserverCallback[] = []
/** Each closed page, by the cursor that reads it. */
function closedPages(pages: Record<string, endpoints.AgentTaskPage>) {
  vi.mocked(endpoints.listAgentTaskPage).mockImplementation(
    async (org, params, signal) =>
      params.status?.includes('closed')
        ? pages[params.cursor ?? '']
        : { entries: await endpoints.listAgentTasks(org, params, signal) },
  )
}

function closedTask(n: number) {
  return task({
    closed_at: `2026-10-0${n}T11:00:00Z`,
    id: `closed-${n}`,
    outcome: 'done_acted',
    short_id: `T-${10 + n}`,
    status: 'closed',
    title: `Closed ${n}`,
  })
}

function renderAt(path: string) {
  window.history.pushState({}, '', path)
  return render(
    <Routes>
      <Route
        element={<AgentsArea />}
        path="/agents/:section?/:slug?/:action?/:tab?"
      />
    </Routes>,
  )
}

function scrollToEnd() {
  act(() => {
    for (const callback of observers)
      callback(
        [{ isIntersecting: true } as IntersectionObserverEntry],
        {} as IntersectionObserver,
      )
  })
}

describe('Tasks', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    observers = []
    vi.stubGlobal(
      'IntersectionObserver',
      class {
        constructor(callback: IntersectionObserverCallback) {
          observers.push(callback)
        }
        disconnect() {}
        observe() {}
      },
    )
    vi.mocked(endpoints.listAgentTaskPage).mockImplementation(
      async (org, params, signal) => ({
        entries: await endpoints.listAgentTasks(org, params, signal),
      }),
    )
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
                status: 'paused',
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

  it('links each task with its org', async () => {
    renderAt('/agents/tasks')
    expect((await screen.findByText('Busy')).closest('a')).toHaveAttribute(
      'href',
      '/agents/tasks/acme/T-4',
    )
  })

  it('redirects an old link to the selected org', async () => {
    renderAt('/agents/tasks/T-3/input')
    await waitFor(() =>
      expect(window.location.pathname).toBe('/agents/tasks/acme/T-3/input'),
    )
    expect(await screen.findByRole('button', { name: 'yes' })).toBeVisible()
  })

  it('opens a task in the org of the link', async () => {
    renderAt('/agents/tasks/beta/T-3')
    await waitFor(() =>
      expect(endpoints.getAgentTask).toHaveBeenCalledWith(
        'beta',
        'T-3',
        expect.anything(),
      ),
    )
    expect(setSelectedOrganization).toHaveBeenCalledWith(ORGS[1])
    expect(endpoints.getAgentTask).not.toHaveBeenCalledWith(
      'acme',
      'T-3',
      expect.anything(),
    )
  })

  it('does not open a task in an org that is not yours', async () => {
    renderAt('/agents/tasks/zeta/T-3')
    expect(
      await screen.findByText('You are not a member of the organization zeta.'),
    ).toBeInTheDocument()
    expect(endpoints.getAgentTask).not.toHaveBeenCalled()
  })

  it('reads the next closed page when the end is in view', async () => {
    closedPages({
      '': { entries: [closedTask(2)], nextCursor: 'c2' },
      c2: { entries: [closedTask(1)] },
    })
    renderAt('/agents/tasks')
    const group = await screen.findByRole('region', { name: 'Recently closed' })
    expect(within(group).getByText('1+')).toBeInTheDocument()
    expect(screen.queryByText('Closed 1')).not.toBeInTheDocument()
    scrollToEnd()
    expect(await screen.findByText('Closed 1')).toBeInTheDocument()
    expect(endpoints.listAgentTaskPage).toHaveBeenCalledWith(
      'acme',
      expect.objectContaining({ cursor: 'c2', status: ['closed'] }),
      expect.anything(),
    )
    expect(within(group).getByText('2')).toBeInTheDocument()
  })

  it('does not read a failed open page again until Retry', async () => {
    let fail = true
    vi.mocked(endpoints.listAgentTaskPage).mockImplementation(
      async (_org, params) => {
        if (params.status?.includes('closed')) return { entries: [] }
        if (params.cursor !== 'o2')
          return { entries: [BLOCKED], nextCursor: 'o2' }
        if (fail) throw new Error('boom')
        return {
          entries: [task({ id: 'open-2', short_id: 'T-2', title: 'Page two' })],
        }
      },
    )
    renderAt('/agents/tasks')
    expect(
      await screen.findByText(/Could not load tasks: boom/),
    ).toBeInTheDocument()
    const page2 = () =>
      vi
        .mocked(endpoints.listAgentTaskPage)
        .mock.calls.filter(([, p]) => p.cursor === 'o2').length
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50))
    })
    expect(page2()).toBe(1)
    fail = false
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('Page two')).toBeInTheDocument()
    expect(page2()).toBe(2)
  })

  it('reads every open page and merges the groups', async () => {
    vi.mocked(endpoints.listAgentTaskPage).mockImplementation(
      async (_org, params) =>
        params.status?.includes('closed')
          ? { entries: [] }
          : params.cursor === 'o2'
            ? {
                entries: [
                  task({
                    blocked_since: '2026-10-08T09:00:00Z',
                    id: 'open-2',
                    short_id: 'T-2',
                    status: 'paused',
                    title: 'Waiting longest',
                  }),
                ],
              }
            : { entries: [BLOCKED], nextCursor: 'o2' },
    )
    renderAt('/agents/tasks')
    // No scroll: the second open page loads by itself.
    const input = await screen.findByRole('region', {
      name: 'Human input required',
    })
    await waitFor(() =>
      expect(
        within(input)
          .getAllByRole('link')
          .map((a) => a.textContent),
      ).toEqual([
        expect.stringContaining('Waiting longest'),
        expect.stringContaining('Apply the fix'),
      ]),
    )
    expect(within(input).getByText('2')).toBeInTheDocument()
  })

  it('keeps the loaded pages when the list refreshes', async () => {
    closedPages({
      '': { entries: [closedTask(2)], nextCursor: 'c2' },
      c2: { entries: [closedTask(1)] },
    })
    vi.mocked(endpoints.resolveAgentTaskRequest).mockResolvedValue({})
    renderAt('/agents/tasks/acme/T-3/input')
    await screen.findByText('Closed 2')
    scrollToEnd()
    const row = await screen.findByText('Closed 1')
    const reads = () =>
      vi
        .mocked(endpoints.listAgentTaskPage)
        .mock.calls.filter(([, params]) => params.cursor === 'c2').length
    expect(reads()).toBe(1)
    // An answer refreshes the inbox.
    fireEvent.click(await screen.findByRole('button', { name: 'yes' }))
    await waitFor(() => expect(reads()).toBe(2))
    expect(screen.getByText('Closed 1')).toBe(row)
    expect(screen.getByText('Closed 2')).toBeInTheDocument()
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

  it('shows a paused task with an open request under Needs input', async () => {
    renderAt('/agents/tasks')
    await screen.findByText('Busy')
    fireEvent.click(screen.getByRole('button', { name: 'Filter by State' }))
    fireEvent.click(await screen.findByLabelText('Needs input'))
    await waitFor(() =>
      expect(screen.queryByText('Busy')).not.toBeInTheDocument(),
    )
    expect(screen.getByText('Waiting longest')).toBeInTheDocument()
    expect(screen.getByText('Apply the fix')).toBeInTheDocument()
  })

  it('answers a feedback request', async () => {
    vi.mocked(endpoints.resolveAgentTaskRequest).mockResolvedValue({})
    renderAt('/agents/tasks/acme/T-3/input')
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
    renderAt('/agents/tasks/acme/T-3/input')
    fireEvent.click(await screen.findByRole('button', { name: 'no' }))
    expect(
      await screen.findByText('Answered by pat@example.com'),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'yes' }),
    ).not.toBeInTheDocument()
    expect(screen.queryByText('Waiting on you')).not.toBeInTheDocument()
  })

  it('renders Signals and checks (J2)', async () => {
    const log = [
      ...LOG,
      event(4, 'check.reported', {
        baseline: '120ms',
        delta: 38,
        name: 'p95 latency',
        source: 'grafana',
        value: '158ms',
        verdict: 'fail',
      }),
      event(5, 'check.reported', { name: 'tests', verdict: 'pending' }),
    ]
    vi.mocked(endpoints.listAgentTaskEvents).mockImplementation(
      async (_org, _id, afterSeq) => log.filter((e) => e.seq > afterSeq),
    )
    renderAt('/agents/tasks/acme/T-3/checks')
    const row = (await screen.findByText('p95 latency')).closest('li')!
    expect(within(row).getByText('Failing')).toBeInTheDocument()
    expect(within(row).getByText('158ms')).toBeInTheDocument()
    expect(
      within(row).getByText('delta +38 · baseline 120ms · source grafana'),
    ).toBeInTheDocument()
    const other = screen.getByText('tests').closest('li')!
    expect(within(other).getByText('pending')).toBeInTheDocument()
    expect(within(other).getByText('—')).toBeInTheDocument()
    expect(
      screen.getByRole('tab', { name: 'Signals and checks1 failing' }),
    ).toHaveAttribute('aria-selected', 'true')
  })

  describe('Conversation', () => {
    const log = [
      ...LOG,
      event(4, 'turn', { body: 'Look first.', kind: 'thinking' }),
      event(
        5,
        'turn',
        { body: 'Searching the feeds.', parent_call_id: 'task-1' },
        { actor_kind: 'subagent' },
      ),
      event(6, 'tool.called', {
        arguments: { command: 'uv run pytest -q' },
        call_id: 'bash-1',
        is_error: true,
        result: '1 failed, 3 passed',
        tool: 'Bash',
      }),
      event(7, 'tool.called', {
        arguments: { description: 'Find calls', subagent_type: 'search' },
        call_id: 'task-1',
        result: 'Two call sites.',
        tool: 'Task',
      }),
      event(8, 'phase.changed', { phase: 'fix' }),
    ]

    beforeEach(() => {
      vi.mocked(endpoints.listAgentTaskEvents).mockImplementation(
        async (_org, _id, afterSeq) => log.filter((e) => e.seq > afterSeq),
      )
    })

    it('shows turns, calls, and nested subagent work in one timeline', async () => {
      renderAt('/agents/tasks/acme/T-3/conversation')
      expect(await screen.findByText('I read the task.')).toBeInTheDocument()
      expect(screen.getByText('Look first.')).toBeInTheDocument()
      expect(screen.getByText('failed')).toBeInTheDocument()
      // Full detail shows the command and its output.
      expect(screen.getByText(/1 failed, 3 passed/)).toBeInTheDocument()
      const subagent = screen.getByText('search · Find calls').closest('div')!
      expect(subagent.parentElement!.parentElement).toHaveTextContent(
        'Searching the feeds.',
      )
      expect(screen.getByText('Phase fix')).toBeInTheDocument()
    })

    it('filters by kind, errors, and text', async () => {
      renderAt('/agents/tasks/acme/T-3/conversation')
      await screen.findByText('I read the task.')
      fireEvent.click(screen.getByRole('button', { name: /^Tools/ }))
      expect(screen.queryByText('uv run pytest -q')).not.toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: /^Tools/ }))
      fireEvent.click(screen.getByRole('button', { name: /^Errors only/ }))
      expect(screen.queryByText('I read the task.')).not.toBeInTheDocument()
      expect(screen.getByText('uv run pytest -q')).toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: /^Errors only/ }))
      fireEvent.change(screen.getByLabelText('Search this task'), {
        target: { value: 'feeds' },
      })
      expect(screen.queryByText('I read the task.')).not.toBeInTheDocument()
      expect(screen.getByText('Searching the feeds.')).toBeInTheDocument()
    })

    it('collapses tool calls and thinking in Compact', async () => {
      renderAt('/agents/tasks/acme/T-3/conversation')
      await screen.findByText('Look first.')
      fireEvent.click(screen.getByRole('radio', { name: 'Compact' }))
      expect(screen.queryByText('Look first.')).not.toBeInTheDocument()
      expect(screen.queryByText(/1 failed, 3 passed/)).not.toBeInTheDocument()
      fireEvent.click(screen.getByText('uv run pytest -q'))
      expect(screen.getByText(/1 failed, 3 passed/)).toBeInTheDocument()
    })

    it('renders cut arguments, notebooks, long edits, and nested plans', async () => {
      vi.mocked(endpoints.getAgentTask).mockResolvedValue({
        ...BLOCKED,
        closed_at: '2026-10-08T13:00:00Z',
        outcome: 'cancelled_by_human',
        status: 'closed',
      })
      vi.mocked(endpoints.listAgentTaskEvents).mockResolvedValue([
        ...LOG,
        event(4, 'tool.called', {
          arguments: '{"file_path": "big.txt", "content": "aaa',
          arguments_truncated: true,
          call_id: 'write-1',
          tool: 'Write',
        }),
        event(5, 'tool.called', {
          arguments: { new_source: 'print(1)', notebook_path: 'nb.ipynb' },
          call_id: 'nb-1',
          tool: 'NotebookEdit',
        }),
        event(6, 'tool.called', {
          arguments: {
            content: Array.from({ length: 60 }, (_, i) => `l${i}`).join('\n'),
            file_path: 'long.txt',
          },
          call_id: 'write-2',
          tool: 'Write',
        }),
        event(
          7,
          'todos.updated',
          { parent_call_id: 'task-9', todos: [{ done: true, title: 'Dig' }] },
          { actor_kind: 'subagent' },
        ),
      ])
      renderAt('/agents/tasks/acme/T-3/conversation')
      await screen.findByText('I read the task.')
      expect(
        screen.getAllByText(/"file_path": "big.txt"/).length,
      ).toBeGreaterThan(0)
      expect(screen.getAllByText('nb.ipynb').length).toBe(2)
      expect(screen.getByText('+ print(1)')).toBeInTheDocument()
      expect(screen.queryByText('+ l59')).not.toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: 'Show all 60 lines' }))
      expect(screen.getByText('+ l59')).toBeInTheDocument()
      expect(screen.getByText('Did not finish')).toBeInTheDocument()
      expect(screen.getByText(/1 of 1 done/)).toBeInTheDocument()
    })

    it('opens an old Actions taken link on the Conversation', async () => {
      renderAt('/agents/tasks/acme/T-3/actions')
      expect(
        await screen.findByRole('tab', { name: /^Conversation/ }),
      ).toHaveAttribute('aria-selected', 'true')
    })
  })

  it('keeps the reply box on every tab while the task is open', async () => {
    renderAt('/agents/tasks/acme/T-3/overview')
    expect(await screen.findByLabelText('Reply')).toBeInTheDocument()
  })

  it('has no reply box on a closed task', async () => {
    vi.mocked(endpoints.getAgentTask).mockResolvedValue({
      ...BLOCKED,
      closed_at: '2026-10-08T13:00:00Z',
      outcome: 'done_acted',
      status: 'closed',
    })
    renderAt('/agents/tasks/acme/T-3/conversation')
    await screen.findByText('I read the task.')
    expect(screen.queryByLabelText('Reply')).not.toBeInTheDocument()
  })

  it('cancels a task after a confirm', async () => {
    vi.mocked(endpoints.controlAgentTask).mockResolvedValue({
      ...BLOCKED,
      control: 'cancel',
    })
    renderAt('/agents/tasks/acme/T-3/conversation')
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel task' }))
    expect(endpoints.controlAgentTask).not.toHaveBeenCalled()
    fireEvent.click(
      within(screen.getByRole('alertdialog')).getByRole('button', {
        name: 'Cancel task',
      }),
    )
    await waitFor(() =>
      expect(endpoints.controlAgentTask).toHaveBeenCalledWith(
        'acme',
        'T-3',
        'cancel',
      ),
    )
  })

  it('deletes a closed task after a confirm', async () => {
    vi.mocked(endpoints.getAgentTask).mockResolvedValue(closedTask(1))
    vi.mocked(endpoints.deleteAgentTask).mockResolvedValue(undefined)
    renderAt('/agents/tasks/acme/T-11')
    fireEvent.click(await screen.findByRole('button', { name: 'Delete task' }))
    expect(endpoints.deleteAgentTask).not.toHaveBeenCalled()
    fireEvent.click(
      within(screen.getByRole('alertdialog')).getByRole('button', {
        name: 'Delete task',
      }),
    )
    await waitFor(() =>
      expect(endpoints.deleteAgentTask).toHaveBeenCalledWith('acme', 'T-11'),
    )
    expect(await screen.findByText('Select a task.')).toBeInTheDocument()
  })

  it('has no Delete for an open task', async () => {
    renderAt('/agents/tasks/acme/T-3')
    await screen.findByRole('button', { name: 'Cancel task' })
    expect(
      screen.queryByRole('button', { name: 'Delete task' }),
    ).not.toBeInTheDocument()
  })

  it('retries a failed task with a note', async () => {
    vi.mocked(endpoints.getAgentTask).mockResolvedValue({
      ...closedTask(1),
      outcome: 'failed_error',
    })
    vi.mocked(endpoints.retryAgentTask).mockResolvedValue(task())
    renderAt('/agents/tasks/acme/T-11')
    fireEvent.click(await screen.findByRole('button', { name: 'Retry task' }))
    fireEvent.change(screen.getByLabelText('Note for the retry'), {
      target: { value: ' Use the new token. ' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() =>
      expect(endpoints.retryAgentTask).toHaveBeenCalledWith('acme', 'T-11', {
        idempotency_key: expect.any(String),
        note: 'Use the new token.',
      }),
    )
  })

  it('sends the same key when a retry after an error repeats', async () => {
    vi.mocked(endpoints.getAgentTask).mockResolvedValue({
      ...closedTask(1),
      outcome: 'failed_error',
    })
    vi.mocked(endpoints.retryAgentTask).mockRejectedValue(
      new Error('Network error'),
    )
    renderAt('/agents/tasks/acme/T-11')
    fireEvent.click(await screen.findByRole('button', { name: 'Retry task' }))
    const submit = screen.getByRole('button', { name: 'Retry' })
    fireEvent.click(submit)
    await screen.findByRole('alert')
    expect(screen.getByLabelText('Note for the retry')).toHaveAttribute(
      'readonly',
    )
    fireEvent.click(submit)
    await waitFor(() =>
      expect(endpoints.retryAgentTask).toHaveBeenCalledTimes(2),
    )
    const [first, second] = vi
      .mocked(endpoints.retryAgentTask)
      .mock.calls.map(([, , body]) => body.idempotency_key)
    expect(first).toEqual(expect.any(String))
    expect(second).toBe(first)
  })

  it('has no Retry for a task that did not fail', async () => {
    vi.mocked(endpoints.getAgentTask).mockResolvedValue(closedTask(1))
    renderAt('/agents/tasks/acme/T-11')
    await screen.findByRole('button', { name: 'Delete task' })
    expect(
      screen.queryByRole('button', { name: 'Retry task' }),
    ).not.toBeInTheDocument()
  })

  it('returns focus to Cancel when the confirm closes', async () => {
    renderAt('/agents/tasks/acme/T-3/conversation')
    const button = await screen.findByRole('button', { name: 'Cancel task' })
    button.focus()
    fireEvent.click(button)
    fireEvent.click(
      within(screen.getByRole('alertdialog')).getByRole('button', {
        name: 'Cancel',
      }),
    )
    await waitFor(() => expect(button).toHaveFocus())
    expect(endpoints.controlAgentTask).not.toHaveBeenCalled()
  })

  it('sends Reply and hold', async () => {
    vi.mocked(endpoints.replyAgentTask).mockResolvedValue(BLOCKED)
    renderAt('/agents/tasks/acme/T-3/conversation')
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
      renderAt('/agents/tasks/acme/T-3/conversation')
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
    vi.mocked(endpoints.getProjectsSlim).mockResolvedValue([
      {
        archived: false,
        id: 'p-1',
        project_types: [{ name: 'HTTP API' }],
        slug: 'billing',
      },
    ] as Awaited<ReturnType<typeof endpoints.getProjectsSlim>>)
    renderAt('/agents/manage/mender')
    fireEvent.click(await screen.findByRole('button', { name: 'Run' }))
    const dialog = screen.getByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText(/What should the agent/), {
      target: { value: 'Check the build\nFind why it fails.' },
    })
    fireEvent.click(await within(dialog).findByText('billing'))
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create task' }))
    await waitFor(() =>
      expect(endpoints.createAgentTask).toHaveBeenCalledWith('acme', {
        agent_slug: 'mender',
        description: 'Check the build\nFind why it fails.',
        project_id: 'p-1',
        title: 'Check the build',
      }),
    )
    await waitFor(() =>
      expect(window.location.pathname).toBe('/agents/tasks/acme/T-9'),
    )
  })
})
