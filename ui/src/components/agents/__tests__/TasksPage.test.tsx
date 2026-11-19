import { Route, Routes } from 'react-router-dom'

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import * as endpoints from '@/api/endpoints'
import { LegacyTasksRedirect } from '@/pages/LegacyTasksRedirect'
import { act, fireEvent, render, screen, waitFor, within } from '@/test/utils'
import type { TicketListItem } from '@/types'

import { AgentsArea } from '../AgentsArea'
import { groupOf, groupTasks } from '../taskEvents'
import { EVENT_POLL_MS } from '../taskQueries'
import { TasksPage } from '../TasksPage'
import { agent, catalog, promptVersion } from './fixtures'
import { event, task } from './taskFixtures'
import { layout, scrollPane } from './virtualLayout'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  controlTicket: vi.fn(),
  countTickets: vi.fn(),
  countWaitingTickets: vi.fn(),
  createTicket: vi.fn(),
  deleteTicket: vi.fn(),
  getAgentToolCatalog: vi.fn(),
  getProjectsSlim: vi.fn(),
  getTicket: vi.fn(),
  getTicketPosition: vi.fn(),
  listAdminUsers: vi.fn(),
  listAgents: vi.fn(),
  listTicketEvents: vi.fn(),
  listTickets: vi.fn(),
  reassignTicket: vi.fn(),
  replyTicket: vi.fn(),
  resolvePrompt: vi.fn(),
  resolveTicketRequest: vi.fn(),
  retryTicket: vi.fn(),
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

const TASKS = [
  task({
    closed_at: '2026-10-08T11:00:00Z',
    outcome: 'done_acted',
    short_id: 'T-1',
    status: 'closed',
    title: 'Old work',
  }),
  task({ short_id: 'T-4', status: 'running', title: 'Busy' }),
  BLOCKED,
  task({
    blocked_since: '2026-10-08T09:00:00Z',
    owner: 'pat@example.com',
    short_id: 'T-2',
    status: 'paused',
    title: 'Waiting longest',
  }),
]

type Position = Awaited<ReturnType<typeof endpoints.getTicketPosition>>

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

/** The titles of the tasks in the inbox, in order. */
function inboxTitles() {
  return screen
    .getAllByRole('link')
    .filter((a) => a.getAttribute('href')?.startsWith('/tickets/acme/'))
    .map((a) => a.querySelector('.font-medium[title]')?.getAttribute('title'))
}

function renderAt(path: string) {
  window.history.pushState({}, '', path)
  return render(
    <Routes>
      <Route element={<TasksPage />} path="/tickets/:slug?/:action?/:tab?" />
      <Route
        element={<LegacyTasksRedirect />}
        path="/agents/tasks/:slug?/:action?/:tab?"
      />
      <Route
        element={<AgentsArea />}
        path="/agents/:section?/:slug?/:action?/:tab?"
      />
    </Routes>,
  )
}

/** Serves `tasks` as the API does: counted and paged by inbox group. */
function serve(tasks: TicketListItem[]) {
  const matching = (params: endpoints.TicketListParams) =>
    tasks.filter(
      (t) =>
        !params.status ||
        params.status.includes(t.status) ||
        (params.status.includes('blocked') && groupOf(t) === 'input'),
    )
  vi.mocked(endpoints.countTickets).mockImplementation(async (_org, params) => {
    const counts = { closed: 0, input: 0, paused: 0, queued: 0, running: 0 }
    for (const t of matching(params)) counts[groupOf(t)] += 1
    return counts
  })
  vi.mocked(endpoints.listTickets).mockImplementation(async (_org, params) => {
    const found = matching(params)
    if (!params.group) return found
    const group =
      groupTasks(found).find((g) => g.id === params.group)?.tasks ?? []
    const offset = params.offset ?? 0
    return group.slice(offset, offset + (params.limit ?? 50))
  })
}

describe('Tasks', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal(
      'IntersectionObserver',
      class {
        disconnect() {}
        observe() {}
      },
    )
    vi.mocked(endpoints.listAgents).mockResolvedValue([agent()])
    vi.mocked(endpoints.listAdminUsers).mockResolvedValue([])
    vi.mocked(endpoints.countWaitingTickets).mockResolvedValue({ count: 2 })
    serve(TASKS)
    vi.mocked(endpoints.getTicket).mockResolvedValue(BLOCKED)
    vi.mocked(endpoints.listTicketEvents).mockImplementation(
      async (_org, _id, afterSeq) => LOG.filter((e) => e.seq > afterSeq),
    )
  })

  it('groups the inbox, oldest block first, with the waiting count', async () => {
    renderAt('/tickets')
    await screen.findByText('Waiting longest')
    await waitFor(() =>
      expect(inboxTitles()).toEqual([
        'Waiting longest',
        'Apply the fix',
        'Busy',
        'Old work',
      ]),
    )
    expect(
      screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent),
    ).toEqual(['Human input required2', 'Running1', 'Recently closed1'])
    expect(screen.getByText('4 tickets')).toBeInTheDocument()
  })

  it('links each task with its org', async () => {
    renderAt('/tickets')
    expect((await screen.findByText('Busy')).closest('a')).toHaveAttribute(
      'href',
      '/tickets/acme/T-4',
    )
  })

  it('redirects an old Agents > Tasks link to the ticket', async () => {
    renderAt('/agents/tasks/acme/T-3/trajectory#e6')
    await waitFor(() =>
      expect(window.location.pathname).toBe('/tickets/acme/T-3/trajectory'),
    )
    expect(window.location.hash).toBe('#e6')
  })

  it('keeps the inbox filter when it redirects an old link', async () => {
    renderAt('/agents/tasks/acme/T-3?state=blocked#e6')
    await waitFor(() =>
      expect(window.location.pathname).toBe('/tickets/acme/T-3/trajectory'),
    )
    expect(window.location.search).toBe('?state=blocked')
    expect(window.location.hash).toBe('#e6')
  })

  it('redirects an old Agents > Tasks link without an org', async () => {
    renderAt('/agents/tasks/T-3/trajectory?state=blocked#e6')
    await waitFor(() =>
      expect(window.location.pathname).toBe('/tickets/acme/T-3/trajectory'),
    )
    expect(window.location.search).toBe('?state=blocked')
    expect(window.location.hash).toBe('#e6')
  })

  it('redirects the old Agents > Tasks list', async () => {
    renderAt('/agents/tasks')
    await waitFor(() => expect(window.location.pathname).toBe('/tickets'))
  })

  it('redirects an old link to the selected org', async () => {
    renderAt('/tickets/T-3/input')
    await waitFor(() =>
      expect(window.location.pathname).toBe('/tickets/acme/T-3/input'),
    )
    expect(await screen.findByRole('button', { name: 'yes' })).toBeVisible()
  })

  it('opens a task in the org of the link', async () => {
    renderAt('/tickets/beta/T-3')
    await waitFor(() =>
      expect(endpoints.getTicket).toHaveBeenCalledWith(
        'beta',
        'T-3',
        expect.anything(),
      ),
    )
    expect(setSelectedOrganization).toHaveBeenCalledWith(ORGS[1])
    expect(endpoints.getTicket).not.toHaveBeenCalledWith(
      'acme',
      'T-3',
      expect.anything(),
    )
  })

  it('opens a task on the tab used last', async () => {
    vi.mocked(window.localStorage.getItem).mockImplementation((key) =>
      key === 'imbi.task.tab' ? '"statistics"' : null,
    )
    try {
      renderAt('/tickets/acme/T-3')
      expect(
        await screen.findByRole('tab', { name: /^Activity/, selected: true }),
      ).toBeInTheDocument()
      expect(screen.getByRole('radio', { name: 'Statistics' })).toHaveAttribute(
        'aria-checked',
        'true',
      )
    } finally {
      vi.mocked(window.localStorage.getItem).mockReturnValue(null)
    }
  })

  it('names the remembered tab in the address', async () => {
    vi.mocked(window.localStorage.getItem).mockImplementation((key) =>
      key === 'imbi.task.tab' ? '"trajectory"' : null,
    )
    try {
      renderAt('/tickets/acme/T-3')
      await waitFor(() =>
        expect(window.location.pathname).toBe('/tickets/acme/T-3/trajectory'),
      )
    } finally {
      vi.mocked(window.localStorage.getItem).mockReturnValue(null)
    }
  })

  it('sends an event link with no tab to the Trajectory', async () => {
    renderAt('/tickets/acme/T-3#e6')
    await waitFor(() =>
      expect(window.location.pathname).toBe('/tickets/acme/T-3/trajectory'),
    )
    expect(window.location.hash).toBe('#e6')
  })

  it('remembers the view an old Actions link opens', async () => {
    renderAt('/tickets/acme/T-3/actions')
    await screen.findByRole('tab', { name: /^Activity/, selected: true })
    expect(window.localStorage.setItem).toHaveBeenCalledWith(
      'imbi.task.tab',
      '"conversation"',
    )
    expect(window.localStorage.setItem).toHaveBeenCalledWith(
      'imbi.task.view',
      '"conversation"',
    )
  })

  it('remembers the tab a task was opened on', async () => {
    renderAt('/tickets/acme/T-3/trajectory')
    await screen.findByRole('tab', { name: /^Activity/, selected: true })
    expect(window.localStorage.setItem).toHaveBeenCalledWith(
      'imbi.task.tab',
      '"trajectory"',
    )
  })

  it('does not open a task in an org that is not yours', async () => {
    renderAt('/tickets/zeta/T-3')
    expect(
      await screen.findByText('You are not a member of the organization zeta.'),
    ).toBeInTheDocument()
    expect(endpoints.getTicket).not.toHaveBeenCalled()
  })

  it('sizes each group by its count and reads the pages it shows', async () => {
    const closed = Array.from({ length: 60 }, (_, i) =>
      task({
        closed_at: new Date(Date.UTC(2026, 9, 1, 0, i)).toISOString(),
        id: `closed-${i}`,
        outcome: 'done_acted',
        short_id: `T-${100 + i}`,
        status: 'closed',
        title: `Closed ${i}`,
      }),
    )
    serve([...TASKS.slice(1), ...closed])
    renderAt('/tickets')
    expect(
      await screen.findByRole('heading', { name: /Recently closed60/ }),
    ).toBeInTheDocument()
    expect(await screen.findByText('Closed 0')).toBeInTheDocument()
    expect(endpoints.listTickets).toHaveBeenCalledWith(
      'acme',
      expect.objectContaining({ group: 'closed', limit: 50, offset: 50 }),
      expect.anything(),
    )
    expect(screen.getByText('63 tickets')).toBeInTheDocument()
  })

  it('reads a page only once it scrolls into view', async () => {
    const closed = Array.from({ length: 60 }, (_, i) =>
      task({
        closed_at: new Date(Date.UTC(2026, 9, 1, 0, i)).toISOString(),
        id: `closed-${i}`,
        outcome: 'done_acted',
        short_id: `T-${100 + i}`,
        status: 'closed',
        title: `Closed ${i}`,
      }),
    )
    serve([...TASKS.slice(1), ...closed])
    const isPane = (el: HTMLElement) =>
      el.classList.contains('overflow-y-auto') &&
      el.querySelector(':scope > .relative') !== null
    const spy = layout({
      content: (el) =>
        parseFloat(
          el.querySelector<HTMLElement>(':scope > .relative')?.style.height ??
            '0',
        ),
      isPane,
      pane: 600,
      row: (el) => (el.querySelector('h3') ? 29 : 72),
    })
    const reads = () =>
      vi
        .mocked(endpoints.listTickets)
        .mock.calls.filter(([, p]) => p.group === 'closed' && p.offset === 50)
        .length
    try {
      renderAt('/tickets')
      expect(await screen.findByText('Closed 59')).toBeInTheDocument()
      const pane = screen
        .getByText('Closed 59')
        .closest<HTMLElement>('.overflow-y-auto')!
      scrollPane(pane, 0)
      await act(async () => {
        await new Promise((r) => setTimeout(r, 20))
      })
      expect(reads()).toBe(0)
      expect(screen.queryByText('Closed 0')).not.toBeInTheDocument()
      scrollPane(pane, 100_000)
      await waitFor(() => expect(reads()).toBe(1))
      expect(await screen.findByText('Closed 0')).toBeInTheDocument()
      const pinned = within(
        document.querySelector<HTMLElement>('[data-sticky]')!,
      ).getByRole('button', { name: /Recently closed/ })
      expect(pinned).not.toHaveAttribute('tabindex')
    } finally {
      spy.mockRestore()
    }
  })

  it('collapses a group and remembers it', async () => {
    renderAt('/tickets')
    await screen.findByText('Old work')
    const toggle = screen.getByRole('button', { name: /Recently closed/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(toggle)
    await waitFor(() =>
      expect(screen.queryByText('Old work')).not.toBeInTheDocument(),
    )
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByText('Busy')).toBeInTheDocument()
    expect(window.localStorage.setItem).toHaveBeenCalledWith(
      'imbi.tasks.collapsed',
      '["closed"]',
    )
    fireEvent.click(toggle)
    expect(await screen.findByText('Old work')).toBeInTheDocument()
  })

  it('keeps the header of the group in view at the top', async () => {
    renderAt('/tickets')
    const scroller = (await screen.findByText('Busy')).closest<HTMLElement>(
      '.overflow-y-auto',
    )!
    expect(document.querySelector('[data-sticky]')).toBeNull()
    fireEvent.scroll(scroller, { target: { scrollTop: 200 } })
    await waitFor(() =>
      expect(document.querySelector('[data-sticky]')).toBeInTheDocument(),
    )
    const pinned = within(
      document.querySelector<HTMLElement>('[data-sticky]')!,
    ).getByRole('button', { hidden: true })
    expect(pinned).toHaveAttribute('aria-expanded', 'true')
    expect(pinned).toHaveAttribute('tabindex', '-1')
    fireEvent.scroll(scroller, { target: { scrollTop: 0 } })
    await waitFor(() =>
      expect(document.querySelector('[data-sticky]')).toBeNull(),
    )
  })

  it('reveals the selected task when the page opens', async () => {
    vi.mocked(window.localStorage.getItem).mockImplementation((key) =>
      key === 'imbi.tasks.collapsed' ? '["input"]' : null,
    )
    vi.mocked(endpoints.getTicketPosition).mockResolvedValue({
      group: 'input',
      index: 1,
    })
    try {
      renderAt('/tickets/acme/T-3?agent=agt-1')
      await waitFor(() => expect(inboxTitles()).toContain('Apply the fix'))
      expect(endpoints.getTicketPosition).toHaveBeenCalledTimes(1)
      expect(endpoints.getTicketPosition).toHaveBeenCalledWith(
        'acme',
        'T-3',
        expect.objectContaining({ agent_id: ['agt-1'] }),
      )
    } finally {
      vi.mocked(window.localStorage.getItem).mockReturnValue(null)
    }
  })

  it('reveals the selected task on demand, opening its group', async () => {
    vi.mocked(endpoints.getTicketPosition).mockResolvedValue({
      group: 'input',
      index: 1,
    })
    renderAt('/tickets/acme/T-3')
    await waitFor(() => expect(inboxTitles()).toContain('Apply the fix'))
    fireEvent.click(
      screen.getByRole('button', { expanded: true, name: /Human input/i }),
    )
    await waitFor(() => expect(inboxTitles()).not.toContain('Apply the fix'))
    fireEvent.click(screen.getByRole('button', { name: 'Reveal in list' }))
    await waitFor(() => expect(inboxTitles()).toContain('Apply the fix'))
    expect(endpoints.getTicketPosition).toHaveBeenCalledTimes(2)
  })

  it('keeps collapse changes made while a reveal waits', async () => {
    vi.mocked(window.localStorage.getItem).mockImplementation((key) =>
      key === 'imbi.tasks.collapsed' ? '["input"]' : null,
    )
    let found!: (at: Position) => void
    vi.mocked(endpoints.getTicketPosition).mockReturnValue(
      new Promise((resolve) => {
        found = resolve
      }),
    )
    try {
      renderAt('/tickets/acme/T-3')
      await screen.findByText('Old work')
      fireEvent.click(screen.getByRole('button', { name: /Recently closed/ }))
      await waitFor(() =>
        expect(screen.queryByText('Old work')).not.toBeInTheDocument(),
      )
      await act(async () => found({ group: 'input', index: 1 }))
      await waitFor(() => expect(inboxTitles()).toContain('Apply the fix'))
      expect(screen.queryByText('Old work')).not.toBeInTheDocument()
      expect(window.localStorage.setItem).toHaveBeenLastCalledWith(
        'imbi.tasks.collapsed',
        '["closed"]',
      )
    } finally {
      vi.mocked(window.localStorage.getItem).mockReturnValue(null)
    }
  })

  it('ignores a reveal for a task no longer selected', async () => {
    vi.mocked(window.localStorage.getItem).mockImplementation((key) =>
      key === 'imbi.tasks.collapsed' ? '["input"]' : null,
    )
    let found!: (at: Position) => void
    vi.mocked(endpoints.getTicketPosition).mockReturnValue(
      new Promise((resolve) => {
        found = resolve
      }),
    )
    try {
      renderAt('/tickets/acme/T-3')
      fireEvent.click(await screen.findByText('Busy'))
      await waitFor(() =>
        expect(window.location.pathname).toMatch(/^\/tickets\/acme\/T-4/),
      )
      await act(async () => found({ group: 'input', index: 1 }))
      expect(inboxTitles()).not.toContain('Apply the fix')
      expect(
        screen.getByRole('button', { name: /Human input/i }),
      ).toHaveAttribute('aria-expanded', 'false')
    } finally {
      vi.mocked(window.localStorage.getItem).mockReturnValue(null)
    }
  })

  it('does not reveal on load without a selected task', async () => {
    renderAt('/tickets')
    await screen.findByText('Busy')
    expect(endpoints.getTicketPosition).not.toHaveBeenCalled()
    expect(
      screen.getByRole('button', { name: 'Reveal in list' }),
    ).toBeDisabled()
  })

  it('opens with the groups collapsed last time', async () => {
    vi.mocked(window.localStorage.getItem).mockImplementation((key) =>
      key === 'imbi.tasks.collapsed' ? '["closed","input"]' : null,
    )
    try {
      renderAt('/tickets')
      await screen.findByText('Busy')
      expect(screen.queryByText('Old work')).not.toBeInTheDocument()
      expect(screen.queryByText('Apply the fix')).not.toBeInTheDocument()
      expect(endpoints.listTickets).not.toHaveBeenCalledWith(
        'acme',
        expect.objectContaining({ group: 'closed' }),
        expect.anything(),
      )
    } finally {
      vi.mocked(window.localStorage.getItem).mockReturnValue(null)
    }
  })

  it('does not read a failed page again until Retry', async () => {
    let fail = true
    const served = vi.mocked(endpoints.listTickets).getMockImplementation()!
    vi.mocked(endpoints.listTickets).mockImplementation(
      async (org, params, signal) => {
        if (params.group === 'running' && fail) throw new Error('boom')
        return served(org, params, signal)
      },
    )
    renderAt('/tickets')
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not load ticketsboom',
    )
    const reads = () =>
      vi
        .mocked(endpoints.listTickets)
        .mock.calls.filter(([, p]) => p.group === 'running').length
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50))
    })
    const failedReads = reads()
    expect(screen.getByText('Old work')).toBeInTheDocument()
    fail = false
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('Busy')).toBeInTheDocument()
    expect(reads()).toBe(failedReads + 1)
  })

  it('keeps the loaded rows when the list refreshes', async () => {
    vi.mocked(endpoints.resolveTicketRequest).mockResolvedValue({})
    renderAt('/tickets/acme/T-3/input')
    const row = await screen.findByText('Old work')
    const reads = () =>
      vi
        .mocked(endpoints.listTickets)
        .mock.calls.filter(([, params]) => params.group === 'closed').length
    const before = reads()
    // An answer refreshes the inbox.
    fireEvent.click(await screen.findByRole('button', { name: 'yes' }))
    await waitFor(() => expect(reads()).toBeGreaterThan(before))
    expect(screen.getByText('Old work')).toBe(row)
  })

  it('filters by text and by my tasks on the server', async () => {
    renderAt('/tickets')
    await screen.findByText('Busy')
    fireEvent.change(screen.getByLabelText('Filter tickets'), {
      target: { value: 'billing' },
    })
    await waitFor(() =>
      expect(endpoints.listTickets).toHaveBeenCalledWith(
        'acme',
        expect.objectContaining({ q: 'billing' }),
        expect.anything(),
      ),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }))
    fireEvent.click(
      await screen.findByRole('option', { name: 'Assigned to me' }),
    )
    await waitFor(() =>
      expect(endpoints.listTickets).toHaveBeenCalledWith(
        'acme',
        expect.objectContaining({ mine: true, q: 'billing' }),
        expect.anything(),
      ),
    )
    expect(screen.getByText('Assignee is')).toBeInTheDocument()
    expect(window.location.search).toBe('?assignee=me')
  })

  it('names each assignee, with the domain when two share a name', async () => {
    serve([
      task({
        id: 'own-1',
        owner: 'pat@example.com',
        short_id: 'T-5',
        title: 'A',
      }),
      task({
        id: 'own-2',
        owner: 'pat@other.example',
        short_id: 'T-6',
        title: 'B',
      }),
      task({
        id: 'own-3',
        owner: 'sam@example.com',
        short_id: 'T-7',
        title: 'C',
      }),
    ])
    renderAt('/tickets')
    expect((await screen.findByText('A')).closest('a')).toHaveTextContent(
      'Assigned to pat@example.com',
    )
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }))
    fireEvent.click(await screen.findByRole('option', { name: 'Assignee' }))
    expect(
      await screen.findByRole('option', { name: 'pat@example.com' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('option', { name: 'pat@other.example' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'sam' })).toBeInTheDocument()
  })

  it('marks the parts of a task that the search matched', async () => {
    serve([
      task({
        highlights: [
          {
            field: 'title',
            parts: [
              { match: false, text: 'Fix the ' },
              { match: true, text: 'billing' },
              { match: false, text: ' job' },
            ],
          },
          {
            field: 'agent',
            id: 'agt-1',
            parts: [
              { match: true, text: 'Bill' },
              { match: false, text: 'ing bot' },
            ],
          },
        ],
        short_id: 'T-9',
        title: 'Fix the billing job',
      }),
    ])
    renderAt('/tickets')
    const row = await screen.findByRole('link', { name: /T-9/ })
    expect(
      [...row.querySelectorAll('[data-search-match]')].map(
        (match) => match.textContent,
      ),
    ).toEqual(['billing', 'Bill'])
    expect(row).toHaveTextContent('Fix the billing job')
    expect(row).toHaveTextContent('Billing bot')
  })

  it('filters open states without reading the closed tasks', async () => {
    renderAt('/tickets')
    await screen.findByText('Busy')
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }))
    fireEvent.click(await screen.findByRole('option', { name: 'State' }))
    fireEvent.click(await screen.findByRole('option', { name: 'Running' }))
    await waitFor(() =>
      expect(screen.queryByText('Apply the fix')).not.toBeInTheDocument(),
    )
    expect(screen.getByText('Busy')).toBeInTheDocument()
    expect(screen.queryByText('Old work')).not.toBeInTheDocument()
    expect(screen.getByText('1 ticket')).toBeInTheDocument()
    expect(window.location.search).toBe('?state=running')
  })

  it('shows a paused task with an open request under Needs input', async () => {
    renderAt('/tickets?state=blocked')
    await screen.findByText('Waiting longest')
    expect(screen.getByText('Apply the fix')).toBeInTheDocument()
    expect(screen.queryByText('Busy')).not.toBeInTheDocument()
  })

  it('reads the filters from the address', async () => {
    renderAt('/tickets?state=closed')
    await screen.findByText('Old work')
    expect(screen.queryByText('Busy')).not.toBeInTheDocument()
    expect(endpoints.listTickets).not.toHaveBeenCalledWith(
      'acme',
      expect.objectContaining({ status: expect.arrayContaining(['running']) }),
      expect.anything(),
    )
    expect(screen.getByText('Closed')).toBeInTheDocument()
  })

  it('filters by agents on the server and removes them from the chip', async () => {
    vi.mocked(endpoints.listAgents).mockResolvedValue([
      agent(),
      { ...agent(), id: 'agt-2', name: 'Shipper' },
    ])
    renderAt('/tickets')
    await screen.findByText('Busy')
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }))
    fireEvent.click(await screen.findByRole('option', { name: 'Agent' }))
    fireEvent.click(await screen.findByRole('option', { name: 'Mender' }))
    fireEvent.click(await screen.findByRole('option', { name: 'Shipper' }))
    await waitFor(() =>
      expect(endpoints.listTickets).toHaveBeenCalledWith(
        'acme',
        expect.objectContaining({ agent_id: ['agt-1', 'agt-2'] }),
        expect.anything(),
      ),
    )
    expect(window.location.search).toBe('?agent=agt-1&agent=agt-2')
    expect(screen.getByRole('option', { name: 'Shipper' })).toHaveAttribute(
      'aria-checked',
      'true',
    )
    fireEvent.click(
      screen.getByRole('button', { name: 'Remove the Agent filter' }),
    )
    await waitFor(() => expect(window.location.search).toBe(''))
  })

  it('finds a value by typing on the field list', async () => {
    renderAt('/tickets')
    await screen.findByText('Busy')
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }))
    fireEvent.change(await screen.findByPlaceholderText('Filter by…'), {
      target: { value: 'pause' },
    })
    fireEvent.click(await screen.findByRole('option', { name: 'State Paused' }))
    await waitFor(() => expect(window.location.search).toBe('?state=paused'))
    expect(
      screen.getByRole('option', { name: 'State Paused' }),
    ).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(screen.getByRole('option', { name: 'State Paused' }))
    await waitFor(() => expect(window.location.search).toBe(''))
  })

  it('matches menu values by substring, not by scattered letters', async () => {
    renderAt('/tickets')
    await screen.findByText('Busy')
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }))
    fireEvent.change(await screen.findByPlaceholderText('Filter by…'), {
      target: { value: 'rng' },
    })
    expect(await screen.findByText('No matches.')).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'State:Running' })).toBeNull()
  })

  it('follows a link to other filters', async () => {
    renderAt('/tickets?state=closed')
    await screen.findByText('Old work')
    act(() => {
      window.history.pushState({}, '', '/tickets?state=running')
      window.dispatchEvent(new PopStateEvent('popstate'))
    })
    await waitFor(() =>
      expect(screen.queryByText('Old work')).not.toBeInTheDocument(),
    )
    expect(await screen.findByText('Busy')).toBeInTheDocument()
    expect(window.location.search).toBe('?state=running')
  })

  it('clears the filters on Back to an address without them', async () => {
    renderAt('/tickets?state=closed')
    await screen.findByText('Old work')
    act(() => {
      window.history.pushState({}, '', '/tickets')
      window.dispatchEvent(new PopStateEvent('popstate'))
    })
    expect(await screen.findByText('Busy')).toBeInTheDocument()
    expect(window.location.search).toBe('')
  })

  it('keeps the filters when a task opens', async () => {
    renderAt('/tickets?state=blocked')
    fireEvent.click(await screen.findByText('Apply the fix'))
    await waitFor(() =>
      expect(window.location.pathname).toMatch(/^\/tickets\/acme\/T-3/),
    )
    expect(window.location.search).toBe('?state=blocked')
  })

  it('answers a feedback request', async () => {
    vi.mocked(endpoints.resolveTicketRequest).mockResolvedValue({})
    renderAt('/tickets/acme/T-3/input')
    fireEvent.click(await screen.findByRole('button', { name: 'yes' }))
    await waitFor(() =>
      expect(endpoints.resolveTicketRequest).toHaveBeenCalledWith(
        'acme',
        'T-3',
        'req-1',
        { answer: 'yes', status: 'answered' },
      ),
    )
  })

  it('collapses a request that someone else resolved (I4)', async () => {
    vi.mocked(endpoints.resolveTicketRequest).mockRejectedValue(
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
    renderAt('/tickets/acme/T-3/input')
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
    vi.mocked(endpoints.listTicketEvents).mockImplementation(
      async (_org, _id, afterSeq) => log.filter((e) => e.seq > afterSeq),
    )
    renderAt('/tickets/acme/T-3/checks')
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

  describe('Trajectory', () => {
    const log = [
      ...LOG,
      event(4, 'usage.reported', { tokens_in: 3, tokens_out: 40 }),
      event(5, 'turn', { body: 'Look first.', kind: 'thinking' }),
      event(6, 'tool.called', {
        arguments: { command: 'uv run pytest -q' },
        call_id: 'bash-1',
        duration_ms: 900,
        is_error: true,
        result: '1 failed, 3 passed',
        tool: 'Bash',
      }),
      event(
        7,
        'tool.called',
        { call_id: 'grep-1', parent_call_id: 'task-1', tool: 'Grep' },
        { actor_kind: 'subagent' },
      ),
      event(8, 'tool.called', {
        arguments: { description: 'Find calls', subagent_type: 'search' },
        call_id: 'task-1',
        result: 'Two call sites.',
        tool: 'Task',
      }),
      event(9, 'phase.changed', { phase: 'fix' }),
    ]

    beforeEach(() => {
      vi.mocked(endpoints.listTicketEvents).mockImplementation(
        async (_org, _id, afterSeq) => log.filter((e) => e.seq > afterSeq),
      )
    })

    async function ledgerRows() {
      const grid = await screen.findByRole('grid', { name: 'Trajectory' })
      await within(grid).findByText('Phase fix')
      return within(grid).getAllByRole('row')
    }

    it('shows every record with its DSH kind', async () => {
      renderAt('/tickets/acme/T-3/trajectory')
      const rows = await ledgerRows()
      expect(rows.map((r) => r.dataset.kind)).toEqual([
        'user',
        'assistant',
        'context',
        'assistant',
        'tool',
        'tool',
        'subtool',
        'system',
      ])
      expect(within(rows[1]).getByText('I read the task.')).toBeInTheDocument()
      expect(
        within(rows[4]).getByText('1 failed, 3 passed'),
      ).toBeInTheDocument()
      expect(screen.getByRole('radio', { name: 'Trajectory' })).toHaveAttribute(
        'aria-checked',
        'true',
      )
      expect(
        screen.getByRole('tab', { name: `Activity${rows.length}` }),
      ).toHaveAttribute('aria-selected', 'true')
    })

    it('searches the trajectory', async () => {
      renderAt('/tickets/acme/T-3/trajectory')
      await ledgerRows()
      fireEvent.change(
        screen.getByRole('searchbox', { name: 'Search trajectory' }),
        { target: { value: 'pytest' } },
      )
      const grid = screen.getByRole('grid', { name: 'Trajectory' })
      expect(within(grid).getAllByRole('row')).toHaveLength(1)
    })

    it('selects the record of a #e link and opens the inspector', async () => {
      renderAt('/tickets/acme/T-3/trajectory#e6')
      const rows = await ledgerRows()
      await waitFor(() =>
        expect(rows[4]).toHaveAttribute('aria-selected', 'true'),
      )
      expect(
        screen.getByRole('complementary', { name: 'Inspector' }),
      ).toHaveTextContent('Failed')
    })

    it('sends an old Log link to the Trajectory', async () => {
      renderAt('/tickets/acme/T-3/log#e6')
      expect(
        await screen.findByRole('radio', { name: /^Trajectory/ }),
      ).toHaveAttribute('aria-checked', 'true')
      await waitFor(() =>
        expect(window.location.pathname).toBe('/tickets/acme/T-3/trajectory'),
      )
      expect(window.location.hash).toBe('#e6')
    })

    it('sends an old Conversation event link to the Trajectory', async () => {
      renderAt('/tickets/acme/T-3/conversation#e2')
      await waitFor(() =>
        expect(window.location.pathname).toBe('/tickets/acme/T-3/trajectory'),
      )
      expect(window.location.hash).toBe('#e2')
    })

    it('sends an Activity event link to the Trajectory', async () => {
      renderAt('/tickets/acme/T-3/activity#e6')
      await waitFor(() =>
        expect(window.location.pathname).toBe('/tickets/acme/T-3/trajectory'),
      )
      expect(window.location.hash).toBe('#e6')
      const rows = await ledgerRows()
      await waitFor(() =>
        expect(rows[4]).toHaveAttribute('aria-selected', 'true'),
      )
    })

    it('opens an old Actions taken link on the Conversation', async () => {
      renderAt('/tickets/acme/T-3/actions')
      expect(
        await screen.findByRole('radio', { name: /^Conversation/ }),
      ).toHaveAttribute('aria-checked', 'true')
    })

    it('shows a Trajectory event in the Conversation', async () => {
      renderAt('/tickets/acme/T-3/trajectory#e6')
      const rows = await ledgerRows()
      await waitFor(() =>
        expect(rows[4]).toHaveAttribute('aria-selected', 'true'),
      )
      fireEvent.click(
        screen.getByRole('button', { name: 'Show in conversation' }),
      )
      await waitFor(() =>
        expect(window.location.pathname).toBe('/tickets/acme/T-3/conversation'),
      )
      expect(window.location.hash).toBe('')
      await waitFor(() =>
        expect(document.querySelector('[data-flash]')).toBeInTheDocument(),
      )
    })

    it('inspects a Conversation call in the Trajectory', async () => {
      renderAt('/tickets/acme/T-3/conversation')
      fireEvent.click(await screen.findByRole('radio', { name: 'Verbose' }))
      fireEvent.click(
        await screen.findByRole('button', { name: /Bash uv run pytest -q/ }),
      )
      fireEvent.click(
        screen.getByRole('button', { name: 'Inspect Bash in the trajectory' }),
      )
      await waitFor(() =>
        expect(window.location.pathname).toBe('/tickets/acme/T-3/trajectory'),
      )
      expect(window.location.hash).toBe('#e6')
      const rows = await ledgerRows()
      await waitFor(() =>
        expect(rows[4]).toHaveAttribute('aria-selected', 'true'),
      )
      expect(
        screen.getByRole('complementary', { name: 'Inspector' }),
      ).toHaveTextContent('Failed')
    })

    it('goes Back from an inspection to the Conversation', async () => {
      renderAt('/tickets/acme/T-3/activity')
      fireEvent.click(await screen.findByRole('radio', { name: 'Verbose' }))
      fireEvent.click(
        await screen.findByRole('button', { name: /Bash uv run pytest -q/ }),
      )
      fireEvent.click(
        screen.getByRole('button', { name: 'Inspect Bash in the trajectory' }),
      )
      await waitFor(() =>
        expect(window.location.pathname).toBe('/tickets/acme/T-3/trajectory'),
      )
      await ledgerRows()
      window.history.back()
      await waitFor(() =>
        expect(window.location.pathname).toBe('/tickets/acme/T-3/conversation'),
      )
      await waitFor(() =>
        expect(
          screen.getByRole('radio', { name: /^Conversation/ }),
        ).toHaveAttribute('aria-checked', 'true'),
      )
    })

    it('inspects a subagent call in the Trajectory', async () => {
      renderAt('/tickets/acme/T-3/conversation')
      fireEvent.click(await screen.findByRole('radio', { name: 'Verbose' }))
      fireEvent.click(await screen.findByRole('button', { name: /Find calls/ }))
      fireEvent.click(await screen.findByRole('button', { name: /^Grep/ }))
      fireEvent.click(
        screen.getByRole('button', { name: 'Inspect Grep in the trajectory' }),
      )
      await waitFor(() => expect(window.location.hash).toBe('#e7'))
      const rows = await ledgerRows()
      await waitFor(() =>
        expect(rows[6]).toHaveAttribute('aria-selected', 'true'),
      )
    })

    it('shows a Statistics turn in the Conversation', async () => {
      renderAt('/tickets/acme/T-3/statistics')
      fireEvent.click(
        await screen.findByRole('button', {
          name: 'Turn 1: show in conversation',
        }),
      )
      await waitFor(() =>
        expect(window.location.pathname).toBe('/tickets/acme/T-3/conversation'),
      )
      await waitFor(() =>
        expect(document.querySelector('[data-flash]')).toBeInTheDocument(),
      )
    })

    it('opens Activity on the view used last', async () => {
      vi.mocked(window.localStorage.getItem).mockImplementation((key) =>
        key === 'imbi.task.view' ? '"statistics"' : null,
      )
      try {
        renderAt('/tickets/acme/T-3/overview')
        fireEvent.click(await screen.findByRole('tab', { name: /^Activity/ }))
        await waitFor(() =>
          expect(window.location.pathname).toBe('/tickets/acme/T-3/statistics'),
        )
      } finally {
        vi.mocked(window.localStorage.getItem).mockReturnValue(null)
      }
    })

    it('switches the Activity view from the toolbar', async () => {
      renderAt('/tickets/acme/T-3/conversation')
      fireEvent.click(await screen.findByRole('radio', { name: /^Trajectory/ }))
      await waitFor(() =>
        expect(window.location.pathname).toBe('/tickets/acme/T-3/trajectory'),
      )
      expect(window.localStorage.setItem).toHaveBeenCalledWith(
        'imbi.task.view',
        '"trajectory"',
      )
    })
  })

  it('keeps the reply box on every tab while the task is open', async () => {
    renderAt('/tickets/acme/T-3/overview')
    expect(await screen.findByLabelText('Reply')).toBeInTheDocument()
  })

  it('has no reply box on a closed task', async () => {
    vi.mocked(endpoints.getTicket).mockResolvedValue({
      ...BLOCKED,
      closed_at: '2026-10-08T13:00:00Z',
      outcome: 'done_acted',
      status: 'closed',
    })
    renderAt('/tickets/acme/T-3/conversation')
    await screen.findByText('I read the task.')
    expect(screen.queryByLabelText('Reply')).not.toBeInTheDocument()
  })

  it('cancels a task after a confirm', async () => {
    vi.mocked(endpoints.controlTicket).mockResolvedValue({
      ...BLOCKED,
      control: 'cancel',
    })
    renderAt('/tickets/acme/T-3/conversation')
    fireEvent.click(
      await screen.findByRole('button', { name: 'Cancel ticket' }),
    )
    expect(endpoints.controlTicket).not.toHaveBeenCalled()
    fireEvent.click(
      within(screen.getByRole('alertdialog')).getByRole('button', {
        name: 'Cancel ticket',
      }),
    )
    await waitFor(() =>
      expect(endpoints.controlTicket).toHaveBeenCalledWith(
        'acme',
        'T-3',
        'cancel',
      ),
    )
  })

  it('deletes a closed task after a confirm', async () => {
    vi.mocked(endpoints.getTicket).mockResolvedValue(closedTask(1))
    vi.mocked(endpoints.deleteTicket).mockResolvedValue(undefined)
    renderAt('/tickets/acme/T-11')
    fireEvent.click(
      await screen.findByRole('button', { name: 'Delete ticket' }),
    )
    expect(endpoints.deleteTicket).not.toHaveBeenCalled()
    fireEvent.click(
      within(screen.getByRole('alertdialog')).getByRole('button', {
        name: 'Delete ticket',
      }),
    )
    await waitFor(() =>
      expect(endpoints.deleteTicket).toHaveBeenCalledWith('acme', 'T-11'),
    )
    expect(await screen.findByText('Select a ticket.')).toBeInTheDocument()
  })

  it('has no Delete for an open task', async () => {
    renderAt('/tickets/acme/T-3')
    await screen.findByRole('button', { name: 'Cancel ticket' })
    expect(
      screen.queryByRole('button', { name: 'Delete ticket' }),
    ).not.toBeInTheDocument()
  })

  it('retries a failed task with a note', async () => {
    vi.mocked(endpoints.getTicket).mockResolvedValue({
      ...closedTask(1),
      outcome: 'failed_error',
    })
    vi.mocked(endpoints.retryTicket).mockResolvedValue(task())
    renderAt('/tickets/acme/T-11')
    fireEvent.click(await screen.findByRole('button', { name: 'Retry ticket' }))
    fireEvent.change(screen.getByLabelText('Note for the retry'), {
      target: { value: ' Use the new token. ' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() =>
      expect(endpoints.retryTicket).toHaveBeenCalledWith('acme', 'T-11', {
        idempotency_key: expect.any(String),
        note: 'Use the new token.',
      }),
    )
  })

  it('sends the same key when a retry after an error repeats', async () => {
    vi.mocked(endpoints.getTicket).mockResolvedValue({
      ...closedTask(1),
      outcome: 'failed_error',
    })
    vi.mocked(endpoints.retryTicket).mockRejectedValue(
      new Error('Network error'),
    )
    renderAt('/tickets/acme/T-11')
    fireEvent.click(await screen.findByRole('button', { name: 'Retry ticket' }))
    const submit = screen.getByRole('button', { name: 'Retry' })
    fireEvent.click(submit)
    await screen.findByRole('alert')
    expect(screen.getByLabelText('Note for the retry')).toHaveAttribute(
      'readonly',
    )
    fireEvent.click(submit)
    await waitFor(() => expect(endpoints.retryTicket).toHaveBeenCalledTimes(2))
    const [first, second] = vi
      .mocked(endpoints.retryTicket)
      .mock.calls.map(([, , body]) => body.idempotency_key)
    expect(first).toEqual(expect.any(String))
    expect(second).toBe(first)
  })

  it('locks the note while a retry is pending', async () => {
    vi.mocked(endpoints.getTicket).mockResolvedValue({
      ...closedTask(1),
      outcome: 'failed_error',
    })
    vi.mocked(endpoints.retryTicket).mockReturnValue(new Promise(() => {}))
    renderAt('/tickets/acme/T-11')
    fireEvent.click(await screen.findByRole('button', { name: 'Retry ticket' }))
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() =>
      expect(screen.getByLabelText('Note for the retry')).toHaveAttribute(
        'readonly',
      ),
    )
  })

  it('keeps the note editable after a rejected retry', async () => {
    vi.mocked(endpoints.getTicket).mockResolvedValue({
      ...closedTask(1),
      outcome: 'failed_error',
    })
    vi.mocked(endpoints.retryTicket).mockRejectedValue(
      new ApiError(422, 'Unprocessable Entity'),
    )
    renderAt('/tickets/acme/T-11')
    fireEvent.click(await screen.findByRole('button', { name: 'Retry ticket' }))
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await screen.findByRole('alert')
    expect(screen.getByLabelText('Note for the retry')).not.toHaveAttribute(
      'readonly',
    )
  })

  it('has no Retry for a task that did not fail', async () => {
    vi.mocked(endpoints.getTicket).mockResolvedValue(closedTask(1))
    renderAt('/tickets/acme/T-11')
    await screen.findByRole('button', { name: 'Delete ticket' })
    expect(
      screen.queryByRole('button', { name: 'Retry ticket' }),
    ).not.toBeInTheDocument()
  })

  it('returns focus to Cancel when the confirm closes', async () => {
    renderAt('/tickets/acme/T-3/conversation')
    const button = await screen.findByRole('button', { name: 'Cancel ticket' })
    button.focus()
    fireEvent.click(button)
    fireEvent.click(
      within(screen.getByRole('alertdialog')).getByRole('button', {
        name: 'Cancel',
      }),
    )
    await waitFor(() => expect(button).toHaveFocus())
    expect(endpoints.controlTicket).not.toHaveBeenCalled()
  })

  it('sends Reply and hold', async () => {
    vi.mocked(endpoints.replyTicket).mockResolvedValue(BLOCKED)
    renderAt('/tickets/acme/T-3/conversation')
    fireEvent.change(await screen.findByLabelText('Reply'), {
      target: { value: 'Wait for me.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Reply and hold' }))
    await waitFor(() =>
      expect(endpoints.replyTicket).toHaveBeenCalledWith(
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
      renderAt('/tickets/acme/T-3/conversation')
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
      expect(endpoints.listTicketEvents).toHaveBeenCalledWith(
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
    vi.mocked(endpoints.createTicket).mockResolvedValue(
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
    fireEvent.click(
      within(dialog).getByRole('button', { name: 'Create ticket' }),
    )
    await waitFor(() =>
      expect(endpoints.createTicket).toHaveBeenCalledWith('acme', {
        agent_slug: 'mender',
        description: 'Check the build\nFind why it fails.',
        project_ids: ['p-1'],
        title: 'Check the build',
      }),
    )
    await waitFor(() =>
      expect(window.location.pathname).toBe('/tickets/acme/T-9/overview'),
    )
  })
})
