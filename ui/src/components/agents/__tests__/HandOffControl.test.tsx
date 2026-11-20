import { fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { render, screen } from '@/test/utils'
import type { Ticket } from '@/types'

import { HandOffControl } from '../HandOffControl'
import { task } from './taskFixtures'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  handOffTicket: vi.fn(),
  listAgents: vi.fn(),
}))

const auth = vi.hoisted(() => ({ email: 'dev@example.com' }))

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

const person: Ticket = task({
  agent_id: null,
  agent_version: null,
  assignee: 'ops@example.com',
  assignee_kind: 'person',
  service_account_id: null,
  status: 'open',
})

describe('HandOffControl', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    auth.email = 'dev@example.com'
    vi.mocked(endpoints.handOffTicket).mockResolvedValue(person)
  })

  it('hands an agent ticket to a person', async () => {
    render(<HandOffControl orgSlug="acme" task={task()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Hand off ticket' }))
    // An agent ticket goes to a person only.
    expect(screen.queryByRole('radiogroup')).toBeNull()
    fireEvent.change(screen.getByLabelText('Assignee email'), {
      target: { value: ' ops@example.com ' },
    })
    fireEvent.change(screen.getByLabelText('Note'), {
      target: { value: 'Merge it' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Hand off' }))
    await waitFor(() =>
      expect(endpoints.handOffTicket).toHaveBeenCalledWith('acme', 'T-1', {
        assignee: 'ops@example.com',
        assignee_kind: 'person',
        note: 'Merge it',
      }),
    )
  })

  it('is hidden from another person without ticket:manage', () => {
    auth.email = 'someone@example.com'
    render(<HandOffControl orgSlug="acme" task={task()} />)
    expect(screen.queryByRole('button', { name: 'Hand off ticket' })).toBeNull()
  })

  it('shows the assignee the agent choice', () => {
    auth.email = 'ops@example.com'
    render(<HandOffControl orgSlug="acme" task={person} />)
    fireEvent.click(screen.getByRole('button', { name: 'Hand off ticket' }))
    fireEvent.click(screen.getByRole('radio', { name: 'Agent' }))
    expect(screen.getByLabelText('Agent')).toBeTruthy()
  })
})
