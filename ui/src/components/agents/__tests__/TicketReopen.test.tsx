import { fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { render, screen } from '@/test/utils'
import type { Ticket } from '@/types'

import { TicketReopen } from '../TicketReopen'
import { task } from './taskFixtures'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({ reopenTicket: vi.fn() }))

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

function closed(changes: Partial<Ticket> = {}): Ticket {
  return task({ owner: 'ops@example.com', status: 'closed', ...changes })
}

describe('TicketReopen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    auth.email = 'ops@example.com'
    vi.mocked(endpoints.reopenTicket).mockResolvedValue(
      closed({ status: 'queued' }),
    )
  })

  it('reopens a closed ticket with a reason', async () => {
    render(<TicketReopen orgSlug="acme" task={closed()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Reopen' }))
    const submit = screen.getByRole('button', { name: 'Reopen ticket' })
    expect(submit).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Why reopen?'), {
      target: { value: ' Still broken ' },
    })
    fireEvent.click(submit)
    await waitFor(() =>
      expect(endpoints.reopenTicket).toHaveBeenCalledWith('acme', 'T-1', {
        reason: 'Still broken',
      }),
    )
  })

  it('is hidden on an open ticket', () => {
    render(<TicketReopen orgSlug="acme" task={closed({ status: 'queued' })} />)
    expect(screen.queryByRole('button', { name: 'Reopen' })).toBeNull()
  })

  it('is hidden from a person who is not involved', () => {
    auth.email = 'someone@example.com'
    render(<TicketReopen orgSlug="acme" task={closed()} />)
    expect(screen.queryByRole('button', { name: 'Reopen' })).toBeNull()
  })

  it('shows to the assignee', () => {
    auth.email = 'person@example.com'
    render(
      <TicketReopen
        orgSlug="acme"
        task={closed({
          assignee: 'Person@example.com',
          assignee_kind: 'person',
        })}
      />,
    )
    expect(screen.getByRole('button', { name: 'Reopen' })).toBeInTheDocument()
  })
})
