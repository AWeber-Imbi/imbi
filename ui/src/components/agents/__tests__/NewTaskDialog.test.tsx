import { fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import * as endpoints from '@/api/endpoints'
import { render, screen } from '@/test/utils'
import type { Agent } from '@/types'

import { detectSource, titleFrom } from '../newTask'
import { NewTaskDialog } from '../NewTaskDialog'
import { normalizeLabel, roleErrors } from '../ticketAttributes'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createTicket: vi.fn(),
  getProjectsSlim: vi.fn(),
  getTicketSchema: vi.fn(),
  listAgents: vi.fn(),
  listOrganizationMembers: vi.fn(),
  listTeams: vi.fn(() => Promise.resolve([])),
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
  custom_fields: {},
  description: 'Sync the schemas',
  due_date: null,
  labels: [],
  priority: 'normal',
  project_ids: [],
  requires: [],
  roles: {},
  team: null,
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

function wheelGoesThrough(option: HTMLElement) {
  const list = option.closest('[cmdk-list]') as HTMLElement
  list.style.overflowY = 'auto'
  Object.defineProperty(list, 'scrollHeight', { value: 400 })
  Object.defineProperty(list, 'clientHeight', { value: 100 })
  return fireEvent.wheel(option, { deltaY: 40 })
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
    vi.mocked(endpoints.listOrganizationMembers).mockResolvedValue([
      { display_name: 'Ops Person', email: 'ops@example.com', is_active: true },
      {
        display_name: 'Gone Person',
        email: 'gone@example.com',
        is_active: false,
      },
    ] as unknown as Awaited<
      ReturnType<typeof endpoints.listOrganizationMembers>
    >)
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
    vi.mocked(endpoints.getTicketSchema).mockResolvedValue({ sections: [] })
  })

  it('asks for a required custom field and sends it', async () => {
    vi.mocked(endpoints.getTicketSchema).mockResolvedValue({
      sections: [
        {
          name: 'Incident',
          properties: {
            region: { default: 'us-east-1', type: 'string' },
            severity: { enum: ['sev1', 'sev2'], title: 'Severity' },
          },
          required: ['region', 'severity'],
          slug: 'incident',
        },
      ],
    })
    const onClose = vi.fn()
    render(<NewTaskDialog agent={agent('mender')} isOpen onClose={onClose} />)
    describeWork('Sync the schemas')
    await screen.findByText('Severity')
    // A required field with a default is not asked for.
    expect(screen.queryByText('Region')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Create ticket' }))
    expect(await screen.findByText(/required/i)).toBeInTheDocument()
    expect(endpoints.createTicket).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('combobox', { name: /Severity/ }))
    fireEvent.click(await screen.findByRole('option', { name: 'sev2' }))
    // A chosen value clears the error of the last submit.
    expect(screen.queryByText(/required property/i)).toBeNull()
    await create(onClose)
    expect(endpoints.createTicket).toHaveBeenCalledWith('acme', {
      ...BASE,
      agent_slug: 'mender',
      assignee_kind: 'agent',
      custom_fields: { severity: 'sev2' },
    })
  })

  it('shows the missing fields of a 422', async () => {
    vi.mocked(endpoints.createTicket).mockRejectedValue(
      new ApiError(422, 'Unprocessable Entity', {
        detail: {
          error: 'custom_fields_invalid',
          invalid: [],
          message: 'The ticket is missing required custom fields',
          missing: [{ field: 'owner_group', title: 'Owner group' }],
        },
      }),
    )
    render(<NewTaskDialog agent={agent('mender')} isOpen onClose={vi.fn()} />)
    describeWork('Sync the schemas')
    fireEvent.click(screen.getByRole('button', { name: 'Create ticket' }))
    expect(
      await screen.findByText('The ticket is missing required custom fields'),
    ).toBeInTheDocument()
    expect(screen.getByText('Owner group')).toBeInTheDocument()
    expect(screen.getByText('Required')).toBeInTheDocument()
  })

  it('keeps a pending create when the priority changes', async () => {
    vi.mocked(endpoints.createTicket).mockReturnValue(new Promise(() => {}))
    render(<NewTaskDialog agent={agent('mender')} isOpen onClose={vi.fn()} />)
    describeWork('Sync the schemas')
    const button = screen.getByRole('button', { name: 'Create ticket' })
    fireEvent.click(button)
    await waitFor(() => expect(button).toBeDisabled())
    fireEvent.click(screen.getByRole('radio', { name: 'Urgent' }))
    expect(button).toBeDisabled()
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
    fireEvent.click(screen.getByRole('button', { name: 'Projects' }))
    fireEvent.change(await screen.findByPlaceholderText('Search projects'), {
      target: { value: 'bill' },
    })
    expect(screen.getByRole('option', { name: 'billing' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /old-billing/ })).toBeNull()
    expect(screen.queryByRole('option', { name: /search/ })).toBeNull()
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
    fireEvent.click(screen.getByRole('button', { name: 'Projects' }))
    fireEvent.click(await screen.findByRole('option', { name: 'search' }))
    fireEvent.keyDown(screen.getByPlaceholderText('Search projects'), {
      key: 'Escape',
    })
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

  it.each([
    ['agent', [/Assign to/], /Forager/],
    ['person', ['Person', 'Assignee'], /Ops Person/],
    ['prerequisite', [/Relations/, 'Add prerequisite'], /T-3/],
    ['project', ['Projects'], /billing/],
  ] as const)(
    'lets the wheel scroll the %s picker',
    async (_, clicks, option) => {
      render(<NewTaskDialog isOpen onClose={vi.fn()} />)
      for (const name of clicks) {
        const role = name === 'Person' ? 'radio' : 'button'
        fireEvent.click(screen.getByRole(role, { name }))
      }
      const item = await screen.findByRole('option', { name: option })
      expect(wheelGoesThrough(item)).toBe(true)
    },
  )
})

describe('roleErrors', () => {
  it('flags incomplete, long, and repeated roles', () => {
    const ops = 'ops@example.com'
    expect(
      roleErrors([
        { email: '', name: '' },
        { email: ops, name: 'qa' },
        { email: '', name: 'reviewer' },
        { email: ops, name: '' },
        { email: ops, name: 'x'.repeat(51) },
        { email: ops, name: 'Approver' },
        { email: ops, name: 'approver' },
      ]),
    ).toEqual([
      undefined,
      undefined,
      'Choose a person.',
      'Enter a role name.',
      'A role name can have 50 characters at most.',
      'Another row is also the role approver.',
      'Another row is also the role approver.',
    ])
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
