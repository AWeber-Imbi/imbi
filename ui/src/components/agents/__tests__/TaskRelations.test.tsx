import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { fireEvent, render, screen, waitFor, within } from '@/test/utils'
import type { AgentTaskProject, AgentTaskRelated } from '@/types'

import { TaskDetail } from '../TaskDetail'
import { EVENT_POLL_MS } from '../taskQueries'
import {
  AssociatedProjectsTab,
  LinkProjectDialog,
  LinkTaskDialog,
  RelatedTasksTab,
} from '../TaskRelations'
import { agent } from './fixtures'
import { event, task } from './taskFixtures'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  getAgentTask: vi.fn(),
  getAgentTaskRelations: vi.fn(),
  getProjectsSlim: vi.fn(),
  listAgents: vi.fn(),
  listAgentTaskEvents: vi.fn(),
  listAgentTaskProjects: vi.fn(),
  listAgentTasks: vi.fn(),
  setAgentTaskDependency: vi.fn(),
  setAgentTaskProject: vi.fn(),
}))

const auth = { permissions: ['agent:read', 'agent_task:manage'] }

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ user: { is_admin: false, permissions: auth.permissions } }),
}))

function related(
  shortId: string,
  overrides: Partial<AgentTaskRelated> = {},
): AgentTaskRelated {
  return {
    agent_id: 'agt-1',
    created_at: '2026-10-08T12:00:00Z',
    linked_at: '2026-10-08T12:30:00Z',
    linked_by: 'dev@example.com',
    linked_by_kind: 'human',
    outcome: null,
    short_id: shortId,
    status: 'queued',
    title: `Task ${shortId}`,
    ...overrides,
  }
}

const RELATIONS = {
  children: [related('T-6', { linked_at: null, linked_by: null })],
  parent: related('T-4', { linked_at: null, linked_by: null }),
  required_by: [related('T-3', { status: 'running' })],
  requires: [related('T-2', { outcome: 'done_acted', status: 'closed' })],
}

function project(overrides: Partial<AgentTaskProject>): AgentTaskProject {
  return {
    added_at: '2026-10-08T12:30:00Z',
    added_by: 'dev@example.com',
    added_by_kind: 'human',
    available: true,
    name: 'Feed Proxy',
    primary: false,
    project_id: 'p-2',
    project_slug: 'feedproxy',
    ...overrides,
  }
}

const PROJECTS = [
  project({
    added_at: null,
    added_by: null,
    added_by_kind: null,
    name: 'Billing',
    primary: true,
    project_id: 'proj-1',
    project_slug: 'billing',
  }),
  project({}),
  project({
    available: false,
    name: null,
    project_id: 'p-gone',
    project_slug: 'old-slug',
  }),
]

function slimProject(id: string, name: string, team: string) {
  return {
    id,
    name,
    slug: name.toLowerCase().replace(/ /g, '-'),
    team: { name: team, slug: team.toLowerCase() },
  } as unknown as endpoints.ProjectListItem
}

describe('Related tasks', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    auth.permissions = ['agent:read', 'agent_task:manage']
    vi.mocked(endpoints.listAgents).mockResolvedValue([agent()])
    vi.mocked(endpoints.getAgentTaskRelations).mockResolvedValue(RELATIONS)
    vi.mocked(endpoints.setAgentTaskDependency).mockResolvedValue(undefined)
  })

  it('reads each dependency both ways and delegation read only', async () => {
    render(<RelatedTasksTab orgSlug="acme" task={task()} />)
    const list = await screen.findByRole('list', { name: 'Related tasks' })
    const rows = await within(list).findAllByRole('listitem')
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringMatching(/^Requiresblocked byT-2Task T-2MenderCompleted/),
      expect.stringMatching(/^Required byblocksT-3Task T-3MenderRunning/),
      expect.stringMatching(/^ParentdelegationT-4/),
      expect.stringMatching(/^ChilddelegationT-6/),
    ])
    expect(within(rows[0]).getByRole('link')).toHaveAttribute(
      'href',
      '/agents/tasks/T-2',
    )
    // Delegation cannot be removed.
    expect(within(rows[2]).queryByRole('button')).toBeNull()
    expect(within(rows[3]).queryByRole('button')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Remove requires T-2' }))
    await waitFor(() =>
      expect(endpoints.setAgentTaskDependency).toHaveBeenCalledWith(
        'acme',
        'T-1',
        'T-2',
        false,
      ),
    )
    fireEvent.click(
      screen.getByRole('button', { name: 'Remove required by T-3' }),
    )
    await waitFor(() =>
      expect(endpoints.setAgentTaskDependency).toHaveBeenCalledWith(
        'acme',
        'T-3',
        'T-1',
        false,
      ),
    )
  })

  it('hides changes without agent_task:manage', async () => {
    auth.permissions = ['agent:read']
    render(<RelatedTasksTab orgSlug="acme" task={task()} />)
    await screen.findByText('Task T-2')
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('shows an empty state', async () => {
    vi.mocked(endpoints.getAgentTaskRelations).mockResolvedValue({
      children: [],
      parent: null,
      required_by: [],
      requires: [],
    })
    render(<RelatedTasksTab orgSlug="acme" task={task()} />)
    expect(await screen.findByText('No related tasks.')).toBeInTheDocument()
  })

  it(
    'updates live from a relation event',
    async () => {
      const log = [event(1, 'task.created')]
      vi.mocked(endpoints.getAgentTask).mockResolvedValue(task())
      vi.mocked(endpoints.listAgentTaskEvents).mockImplementation(
        async (_org, _id, afterSeq) => log.filter((e) => e.seq > afterSeq),
      )
      vi.mocked(endpoints.getAgentTaskRelations).mockResolvedValue({
        ...RELATIONS,
        required_by: [],
      })
      render(<TaskDetail orgSlug="acme" shortId="T-1" tab="related" />)
      await screen.findByText('Task T-2')
      expect(screen.queryByText('Task T-3')).toBeNull()

      vi.mocked(endpoints.getAgentTaskRelations).mockResolvedValue(RELATIONS)
      log.push(event(2, 'dependency.added', { side: 'prerequisite' }))
      expect(
        await screen.findByText(
          'Task T-3',
          {},
          { timeout: EVENT_POLL_MS + 2000 },
        ),
      ).toBeInTheDocument()
    },
    EVENT_POLL_MS + 5000,
  )
})

describe('Link task dialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.listAgents).mockResolvedValue([agent()])
    vi.mocked(endpoints.setAgentTaskDependency).mockResolvedValue(undefined)
    vi.mocked(endpoints.listAgentTasks).mockResolvedValue([
      task(),
      task({ id: 'id-2', short_id: 'T-2', title: 'Linked already' }),
      task({ id: 'id-5', short_id: 'T-5', title: 'Ship the fix' }),
    ])
  })

  function renderDialog(onClose = vi.fn()) {
    render(
      <LinkTaskDialog
        exclude={new Set(['T-1', 'T-2'])}
        onClose={onClose}
        orgSlug="acme"
        shortId="T-1"
      />,
    )
    return onClose
  }

  it('links the chosen task in the chosen direction', async () => {
    const onClose = renderDialog()
    const list = await screen.findByRole('list', { name: 'Tasks' })
    // This task and linked tasks are not offered.
    expect(await within(list).findAllByRole('button')).toHaveLength(1)
    const link = screen.getByRole('button', { name: /^Link$/ })
    expect(link).toBeDisabled()

    fireEvent.click(within(list).getByRole('button', { name: /T-5/ }))
    expect(
      screen.getByText('T-1 requires T-5 · T-5 blocks T-1'),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio', { name: 'Blocks' }))
    expect(
      screen.getByText('T-5 requires T-1 · T-1 blocks T-5'),
    ).toBeInTheDocument()
    fireEvent.click(link)
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(endpoints.setAgentTaskDependency).toHaveBeenCalledWith(
      'acme',
      'T-5',
      'T-1',
      true,
    )
  })

  it('blocked by is the requires direction', async () => {
    renderDialog()
    fireEvent.click(await screen.findByRole('button', { name: /T-5/ }))
    fireEvent.click(screen.getByRole('radio', { name: 'Blocked by' }))
    fireEvent.click(screen.getByRole('button', { name: /^Link$/ }))
    await waitFor(() =>
      expect(endpoints.setAgentTaskDependency).toHaveBeenCalledWith(
        'acme',
        'T-1',
        'T-5',
        true,
      ),
    )
  })

  it('searches by text', async () => {
    renderDialog()
    await screen.findByRole('button', { name: /T-5/ })
    fireEvent.change(screen.getByLabelText('Search tasks'), {
      target: { value: 'ship' },
    })
    await waitFor(() =>
      expect(endpoints.listAgentTasks).toHaveBeenCalledWith(
        'acme',
        { limit: 20, q: 'ship' },
        expect.anything(),
      ),
    )
  })
})

describe('Associated projects', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    auth.permissions = ['agent:read', 'agent_task:manage']
    vi.mocked(endpoints.listAgentTaskProjects).mockResolvedValue(PROJECTS)
    vi.mocked(endpoints.setAgentTaskProject).mockResolvedValue(undefined)
  })

  it('shows the primary and a deleted project, and removes one', async () => {
    render(<AssociatedProjectsTab orgSlug="acme" task={task()} />)
    const list = await screen.findByRole('list', {
      name: 'Associated projects',
    })
    const [primary, second, gone] = await within(list).findAllByRole('listitem')
    expect(within(primary).getByText('Primary')).toBeInTheDocument()
    expect(within(primary).queryByRole('button')).toBeNull()
    expect(within(second).getByRole('link')).toHaveAttribute(
      'href',
      '/projects/p-2',
    )
    // A deleted project: its slug snapshot, no link.
    expect(within(gone).getByText('No longer available')).toBeInTheDocument()
    expect(within(gone).getAllByText('old-slug')).not.toHaveLength(0)
    expect(within(gone).queryByRole('link')).toBeNull()

    fireEvent.click(
      screen.getByRole('button', { name: 'Remove project old-slug' }),
    )
    await waitFor(() =>
      expect(endpoints.setAgentTaskProject).toHaveBeenCalledWith(
        'acme',
        'T-1',
        'p-gone',
        false,
      ),
    )
  })

  it('cannot change an archived task', async () => {
    render(
      <AssociatedProjectsTab
        orgSlug="acme"
        task={task({ log_archived_at: '2026-10-09T00:00:00Z' })}
      />,
    )
    await screen.findByText('Feed Proxy')
    expect(screen.queryByRole('button')).toBeNull()
  })
})

describe('Link project dialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.setAgentTaskProject).mockResolvedValue(undefined)
    vi.mocked(endpoints.getProjectsSlim).mockResolvedValue([
      slimProject('proj-1', 'Billing', 'Payments'),
      slimProject('p-3', 'Subscriber API', 'Platform'),
      slimProject('p-4', 'Rundeck', 'SRE'),
    ])
  })

  it('links a project that is not linked yet', async () => {
    const onClose = vi.fn()
    render(
      <LinkProjectDialog
        exclude={new Set(['proj-1'])}
        onClose={onClose}
        orgSlug="acme"
        shortId="T-1"
      />,
    )
    const list = await screen.findByRole('list', { name: 'Projects' })
    await within(list).findByText('Rundeck')
    expect(within(list).queryByText('Billing')).toBeNull()
    fireEvent.change(screen.getByLabelText('Search projects'), {
      target: { value: 'platform' },
    })
    expect(within(list).queryByText('Rundeck')).toBeNull()
    const link = screen.getByRole('button', { name: /^Link project$/ })
    expect(link).toBeDisabled()
    fireEvent.click(within(list).getByRole('button', { name: /Subscriber/ }))
    expect(screen.getByText('Linking Subscriber API')).toBeInTheDocument()
    fireEvent.click(link)
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(endpoints.setAgentTaskProject).toHaveBeenCalledWith(
      'acme',
      'T-1',
      'p-3',
      true,
    )
  })
})
