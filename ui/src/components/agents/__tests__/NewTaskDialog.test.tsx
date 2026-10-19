import { fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { render, screen } from '@/test/utils'
import type { Agent } from '@/types'

import { detectSource, titleFrom } from '../newTask'
import { NewTaskDialog } from '../NewTaskDialog'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createAgentTask: vi.fn(),
  getProjectsSlim: vi.fn(),
  listAgents: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ user: { is_admin: true, permissions: [] } }),
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
    vi.mocked(endpoints.createAgentTask).mockResolvedValue({
      short_id: 'T-1',
    } as Awaited<ReturnType<typeof endpoints.createAgentTask>>)
  })

  it('says what is missing and lists enabled agents only', async () => {
    render(<NewTaskDialog isOpen onClose={vi.fn()} />)
    expect(
      screen.getByText('Needs a description, an agent and a project.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create task' })).toBeDisabled()
    expect(await screen.findAllByRole('radio')).toHaveLength(2)
    expect(screen.queryByText('Retired')).toBeNull()
  })

  it('keeps the agent of the Run button', () => {
    render(<NewTaskDialog agent={agent('mender')} isOpen onClose={vi.fn()} />)
    expect(screen.getByRole('radio', { name: /Mender/ })).toBeChecked()
    expect(screen.getAllByRole('radio')).toHaveLength(1)
    expect(endpoints.listAgents).not.toHaveBeenCalled()
  })

  it('searches projects and leaves out archived ones', async () => {
    render(<NewTaskDialog isOpen onClose={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Search projects'), {
      target: { value: 'bill' },
    })
    expect(await screen.findByText('billing')).toBeInTheDocument()
    expect(screen.queryByText('old-billing')).toBeNull()
    expect(screen.queryByText('search')).toBeNull()
  })

  it('creates a task from the request', async () => {
    const onClose = vi.fn()
    render(<NewTaskDialog isOpen onClose={onClose} />)
    fireEvent.change(screen.getByLabelText('What should the agent do?'), {
      target: {
        value: 'Fix the crash https://sentry.io/issues/1\nIt fails on save.',
      },
    })
    expect(screen.getByText('Sentry issue')).toBeInTheDocument()
    fireEvent.click(await screen.findByRole('radio', { name: /Forager/ }))
    fireEvent.click(await screen.findByText('search'))
    expect(screen.getByText('Starts as Queued. Esc to cancel.')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Create task' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(endpoints.createAgentTask).toHaveBeenCalledWith('acme', {
      agent_slug: 'forager',
      description:
        'Fix the crash https://sentry.io/issues/1\nIt fails on save.',
      project_id: 'p-3',
      title: 'Fix the crash',
    })
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
