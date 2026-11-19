import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { render, screen, within } from '@/test/utils'

import { WaitingOnMe } from '../WaitingOnMe'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({ countWaitingTickets: vi.fn() }))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    user: {
      is_admin: true,
      organizations: [{ organization_slug: 'acme', permissions: [] }],
      permissions: [],
    },
  }),
}))

const TICKET = {
  agent_id: null,
  assignee: 'dev@example.com',
  assignee_kind: 'person' as const,
  created_at: '2026-10-08T12:00:00Z',
  owner: 'dev@example.com',
  priority: 'normal' as const,
  updated_at: '2026-10-08T12:00:00Z',
}

describe('WaitingOnMe', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('lists the three groups', async () => {
    vi.mocked(endpoints.countWaitingTickets).mockResolvedValue({
      assigned: [
        { ...TICKET, short_id: 'T-2', status: 'open', title: 'Rotate' },
      ],
      count: 3,
      held: [
        {
          ...TICKET,
          failed: ['T-5'],
          short_id: 'T-6',
          status: 'held',
          title: 'Deploy',
        },
      ],
      requests: [
        {
          id: 'r1',
          kind: 'feedback',
          opened_at: '2026-10-08T12:00:00Z',
          short_id: 'T-1',
          ticket_title: 'Fix the build',
          title: 'Which branch?',
        },
      ],
    })
    render(<WaitingOnMe />)
    const questions = await screen.findByRole('region', {
      name: 'Questions on your tickets',
    })
    expect(within(questions).getByRole('link').getAttribute('href')).toBe(
      '/tickets/acme/T-1',
    )
    expect(within(questions).getByText('Which branch?')).toBeTruthy()
    const assigned = screen.getByRole('region', { name: 'Assigned to you' })
    expect(within(assigned).getByText('Rotate')).toBeTruthy()
    const held = screen.getByRole('region', {
      name: 'Held: a prerequisite failed',
    })
    expect(within(held).getByText('Failed: T-5')).toBeTruthy()
  })

  it('shows empty groups for a previous-release API', async () => {
    vi.mocked(endpoints.countWaitingTickets).mockResolvedValue({ count: 2 })
    render(<WaitingOnMe />)
    expect(await screen.findByText('No questions wait on you.')).toBeTruthy()
    expect(screen.getByText('No tickets are assigned to you.')).toBeTruthy()
  })
})
