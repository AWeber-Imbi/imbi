import { fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { render, screen } from '@/test/utils'
import type { Agent } from '@/types'

import { detectSource, titleFrom } from '../newTask'
import { NewTaskDialog } from '../NewTaskDialog'
import { normalizeLabel } from '../ticketAttributes'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createTicket: vi.fn(),
  getProjectsSlim: vi.fn(),
  listAdminUsers: vi.fn(),
  listAgents: vi.fn(),
  listTicketLabels: vi.fn(() => Promise.resolve([])),
  listTickets: vi.fn(),
  reassignTicket: vi.fn(),
  setTicketParent: vi.fn(),
  suggestTicketSubject: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    user: {
      email: 'me@example.com',
      is_admin: true,
      organizations: [{ organization_slug: 'acme', permissions: [] }],
      permissions: [],
    },
  }),
}))

function agent(slug: string, enabled = true): Agent {
  return {
    description: `${slug} things`,
    enabled,
    name: slug[0].toUpperCase() + slug.slice(1),
    organization: { slug: 'acme' },
    slug,
    version: 3,
  } as Agent
}

const BASE = {
  description: 'Sync the schemas',
  due_date: null,
  labels: [],
  priority: 'normal',
  project_ids: [],
  requires: [],
  roles: {},
  title: 'Sync the schemas',
  type: 'task',
}

async function create(onClose: () => void) {
  fireEvent.click(screen.getByRole('button', { name: 'Create ticket' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
}

function describeWork(text: string) {
  fireEvent.change(screen.getByLabelText(/Describe the work/), {
    target: { value: text },
  })
}

async function pickAgent(name: string) {
  fireEvent.click(screen.getByRole('button', { name: /Assign to/ }))
  fireEvent.click(await screen.findByRole('option', { name: new RegExp(name) }))
}

describe('NewTaskDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.listAgents).mockResolvedValue([
      agent('mender'),
      agent('forager'),
      agent('retired', false),
    ])
    vi.mocked(endpoints.getProjectsSlim).mockResolvedValue([
      { archived: false, id: 'p-1', project_types: [], slug: 'billing' },
      { archived: true, id: 'p-2', project_types: [], slug: 'old-billing' },
      { archived: false, id: 'p-3', project_types: [], slug: 'search' },
    ] as unknown as Awaited<ReturnType<typeof endpoints.getProjectsSlim>>)
    vi.mocked(endpoints.listAdminUsers).mockResolvedValue([
      { display_name: 'Ops Person', email: 'ops@example.com' },
    ] as unknown as Awaited<ReturnType<typeof endpoints.listAdminUsers>>)
    vi.mocked(endpoints.listTickets).mockResolvedValue([
      { short_id: 'T-3', status: 'open', title: 'Rotate certs' },
    ] as unknown as Awaited<ReturnType<typeof endpoints.listTickets>>)
    vi.mocked(endpoints.suggestTicketSubject).mockResolvedValue({
      degraded: true,
      subject: 'ignored',
    })
    vi.mocked(endpoints.createTicket).mockResolvedValue({
      short_id: 'T-1',
    } as Awaited<ReturnType<typeof endpoints.createTicket>>)
  })

  it('says what is missing and lists enabled agents only', async () => {
    render(<NewTaskDialog isOpen onClose={vi.fn()} />)
    expect(
      screen.getByText('Needs a description and an assignee.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create ticket' })).toBeDisabled()
    await waitFor(() => expect(endpoints.listAgents).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: /Assign to/ }))
    expect(await screen.findAllByRole('option')).toHaveLength(2)
    expect(screen.queryByText('Retired')).toBeNull()
  })

  it('keeps the agent of the Run button', () => {
    render(<NewTaskDialog agent={agent('mender')} isOpen onClose={vi.fn()} />)
    expect(screen.getByRole('button', { name: /Assign to/ })).toHaveTextContent(
      'Mender',
    )
    expect(screen.queryByRole('radio', { name: 'Person' })).toBeNull()
    expect(endpoints.listAgents).not.toHaveBeenCalled()
  })

  it('searches projects and leaves out archived ones', async () => {
    render(<NewTaskDialog isOpen onClose={vi.fn()} />)
    const search = screen.getByLabelText('Projects')
    fireEvent.focus(search)
    fireEvent.change(search, { target: { value: 'bill' } })
    expect(await screen.findByText('billing')).toBeInTheDocument()
    expect(screen.queryByText('old-billing')).toBeNull()
    expect(screen.queryByText('search')).toBeNull()
  })

  it('creates an agent ticket with its attributes', async () => {
    const onClose = vi.fn()
    render(<NewTaskDialog isOpen onClose={onClose} />)
    describeWork('Fix the crash https://sentry.io/issues/1\nIt fails on save.')
    expect(screen.getByText('Sentry issue')).toBeInTheDocument()
    expect(screen.getByLabelText('Subject')).toHaveValue('Fix the crash')
    expect(screen.getByText('Auto')).toBeInTheDocument()
    await pickAgent('Forager')
    expect(screen.getByText('Runs now with Forager')).toBeInTheDocument()
    const projects = screen.getByLabelText('Projects')
    fireEvent.focus(projects)
    fireEvent.mouseDown(await screen.findByText('search'))
    fireEvent.click(screen.getByRole('radio', { name: 'Bug' }))
    fireEvent.click(screen.getByRole('radio', { name: 'Urgent' }))
    fireEvent.change(screen.getByLabelText('Due'), {
      target: { value: '2026-12-01' },
    })
    const labels = screen.getByLabelText('Labels')
    fireEvent.change(labels, { target: { value: 'API ' } })
    fireEvent.keyDown(labels, { key: 'Enter' })
    expect(
      screen.getByRole('button', { name: 'Remove label api' }),
    ).toBeInTheDocument()
    await create(onClose)
    expect(endpoints.createTicket).toHaveBeenCalledWith('acme', {
      ...BASE,
      agent_slug: 'forager',
      assignee_kind: 'agent',
      description:
        'Fix the crash https://sentry.io/issues/1\nIt fails on save.',
      due_date: '2026-12-01',
      labels: ['api'],
      priority: 'urgent',
      project_ids: ['p-3'],
      title: 'Fix the crash',
      type: 'bug',
    })
  })

  it('uses the subject that the model writes', async () => {
    vi.mocked(endpoints.suggestTicketSubject).mockResolvedValue({
      degraded: false,
      subject: 'Handle a null owner team',
    })
    const onClose = vi.fn()
    render(<NewTaskDialog agent={agent('mender')} isOpen onClose={onClose} />)
    describeWork('The deployments list returns a 500 with no owner team.')
    await waitFor(
      () =>
        expect(screen.getByLabelText('Subject')).toHaveValue(
          'Handle a null owner team',
        ),
      { timeout: 2000 },
    )
    expect(screen.getByText('AI')).toBeInTheDocument()
    expect(endpoints.suggestTicketSubject).toHaveBeenCalledWith(
      'acme',
      'The deployments list returns a 500 with no owner team.',
      expect.anything(),
    )
    await create(onClose)
    expect(endpoints.createTicket).toHaveBeenCalledWith(
      'acme',
      expect.objectContaining({ title: 'Handle a null owner team' }),
    )
  })

  it('keeps a subject that the person typed', async () => {
    const onClose = vi.fn()
    render(<NewTaskDialog agent={agent('mender')} isOpen onClose={onClose} />)
    describeWork('Sync the schemas')
    fireEvent.change(screen.getByLabelText('Subject'), {
      target: { value: 'Schema sync' },
    })
    expect(screen.queryByText('Auto')).toBeNull()
    await create(onClose)
    expect(endpoints.createTicket).toHaveBeenCalledWith('acme', {
      ...BASE,
      agent_slug: 'mender',
      assignee_kind: 'agent',
      title: 'Schema sync',
    })
  })

  it('creates a held person ticket with a role', async () => {
    const onClose = vi.fn()
    render(<NewTaskDialog isOpen onClose={onClose} />)
    describeWork('Rotate the deploy key')
    fireEvent.click(screen.getByRole('radio', { name: 'Person' }))
    fireEvent.click(screen.getByRole('button', { name: 'Assignee' }))
    fireEvent.click(await screen.findByRole('option', { name: /Ops Person/ }))
    expect(screen.getByText('Assigns to Ops Person')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Roles/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Add role' }))
    fireEvent.change(screen.getByLabelText('Role 1 name'), {
      target: { value: 'Code Reviewer' },
    })
    fireEvent.click(
      screen.getByRole('button', { name: 'Person in role Code Reviewer' }),
    )
    fireEvent.click(await screen.findByRole('option', { name: /Ops Person/ }))

    fireEvent.click(screen.getByRole('button', { name: /Relations/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Add prerequisite' }))
    fireEvent.click(await screen.findByRole('option', { name: /T-3/ }))
    expect(screen.getByRole('status')).toHaveTextContent(
      'Starts held: waits on T-3.',
    )
    await create(onClose)
    expect(endpoints.createTicket).toHaveBeenCalledWith('acme', {
      ...BASE,
      assignee: 'ops@example.com',
      assignee_kind: 'person',
      description: 'Rotate the deploy key',
      requires: [{ gates: true, short_id: 'T-3' }],
      roles: { 'code-reviewer': 'ops@example.com' },
      title: 'Rotate the deploy key',
    })
  })
})

describe('normalizeLabel', () => {
  it('folds case, spaces, underscores, and edge punctuation', () => {
    expect(normalizeLabel('API')).toBe('api')
    expect(normalizeLabel('api-')).toBe('api')
    expect(normalizeLabel('  Front_End  Work ')).toBe('front-end-work')
    expect(normalizeLabel('a--b')).toBe('a-b')
    expect(normalizeLabel('!!!')).toBe('')
  })
})

describe('titleFrom', () => {
  it('takes the first line without links, or names the source', () => {
    expect(titleFrom('  Do it https://x.y/z \nmore')).toBe('Do it')
    expect(titleFrom('https://ghe.example.com/a/b/pull/7')).toBe(
      'Work from pull request',
    )
    expect(titleFrom('x'.repeat(200))).toHaveLength(96)
  })
})

describe('detectSource', () => {
  it('names the kind of link', () => {
    expect(detectSource('no link')).toBeNull()
    expect(detectSource('https://acme.slack.com/archives/C1/p2')?.label).toBe(
      'Slack thread',
    )
    expect(detectSource('https://example.com')?.label).toBe('Link')
  })
})
