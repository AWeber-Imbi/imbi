import { fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { render, screen } from '@/test/utils'
import type { Ticket } from '@/types'

import { PersonStatusControls } from '../PersonStatusControls'
import { task } from './taskFixtures'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({ setTicketStatus: vi.fn() }))

const auth = vi.hoisted(() => ({ email: 'ops@example.com' }))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    user: {
      email: auth.email,
      is_admin: false,
      organizations: [{ organization_slug: 'acme', permissions: [] }],
      permissions: [],
    },
  }),
}))

function person(status: Ticket['status']): Ticket {
  return task({
    agent_id: null,
    agent_version: null,
    assignee: 'ops@example.com',
    assignee_kind: 'person',
    service_account_id: null,
    status,
  })
}

describe('PersonStatusControls', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    auth.email = 'ops@example.com'
    vi.mocked(endpoints.setTicketStatus).mockResolvedValue(person('open'))
  })

  it('lets the assignee start an open ticket', async () => {
    render(<PersonStatusControls orgSlug="acme" task={person('open')} />)
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await waitFor(() =>
      expect(endpoints.setTicketStatus).toHaveBeenCalledWith('acme', 'T-1', {
        status: 'in_progress',
      }),
    )
  })

  it('blocks with a reason', async () => {
    render(<PersonStatusControls orgSlug="acme" task={person('in_progress')} />)
    expect(screen.queryByRole('button', { name: 'Start' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Block' }))
    fireEvent.change(screen.getByLabelText('Why is it blocked?'), {
      target: { value: 'Waiting on ops' },
    })
    fireEvent.submit(screen.getByLabelText('Why is it blocked?'))
    await waitFor(() =>
      expect(endpoints.setTicketStatus).toHaveBeenCalledWith('acme', 'T-1', {
        reason: 'Waiting on ops',
        status: 'blocked',
      }),
    )
  })

  it('closes a held ticket with an outcome', async () => {
    render(<PersonStatusControls orgSlug="acme" task={person('held')} />)
    expect(screen.queryByRole('button', { name: 'Block' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    fireEvent.change(screen.getByLabelText('Outcome'), {
      target: { value: 'cancelled_by_human' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Close ticket' }))
    await waitFor(() =>
      expect(endpoints.setTicketStatus).toHaveBeenCalledWith('acme', 'T-1', {
        outcome: 'cancelled_by_human',
        reason: null,
        status: 'closed',
      }),
    )
  })

  it('is hidden from another person without ticket:manage', () => {
    auth.email = 'someone@example.com'
    render(<PersonStatusControls orgSlug="acme" task={person('open')} />)
    expect(screen.queryByRole('button', { name: 'Start' })).toBeNull()
  })
})
