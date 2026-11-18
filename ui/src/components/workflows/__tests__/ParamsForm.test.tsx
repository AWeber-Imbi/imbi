import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { fireEvent, render, screen } from '@/test/utils'

import { ParamsForm } from '../ParamsForm'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  listOrganizationMembers: vi.fn(),
  listTeams: vi.fn(),
}))

const MEMBER = {
  display_name: 'Ada Lovelace',
  email: 'ada@example.com',
  id: 'u1',
  is_active: true,
  role: 'member',
}

function renderRecipients(...ids: string[]) {
  const onChange = vi.fn()
  render(
    <ParamsForm
      fields={[{ kind: 'recipients', label: 'To', name: 'to', required: true }]}
      idPrefix="email"
      onChange={onChange}
      onRemoveItem={vi.fn()}
      orgSlug="acme"
      params={{ to: ids.map((id) => ({ id, kind: 'user' })) }}
      references={[]}
      webhookProject={false}
    />,
  )
  return onChange
}

describe('ParamsForm recipients', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.listTeams).mockResolvedValue([])
    vi.mocked(endpoints.listOrganizationMembers).mockResolvedValue([
      MEMBER,
      {
        ...MEMBER,
        display_name: 'Gone User',
        email: 'gone@example.com',
        id: 'u2',
        is_active: false,
      },
    ])
  })

  it('offers only active members', async () => {
    renderRecipients('')

    fireEvent.click(await screen.findByText('Choose a user…'))

    expect(
      await screen.findByRole('option', { name: /Ada Lovelace/ }),
    ).toBeVisible()
    expect(screen.queryByRole('option', { name: /Gone User/ })).toBeNull()
  })

  it('picks a member', async () => {
    const onChange = renderRecipients('')

    fireEvent.click(await screen.findByText('Choose a user…'))
    fireEvent.click(
      await screen.findByRole('option', {
        name: /Ada Lovelace <ada@example.com>/,
      }),
    )

    expect(onChange).toHaveBeenCalledWith('to', [{ id: 'u1', kind: 'user' }])
  })

  it('shows the id of a user that is not a member', async () => {
    renderRecipients('u9')

    expect(await screen.findByText('u9')).toBeVisible()
  })

  it('switches to a reference', async () => {
    const onChange = renderRecipients('u1')

    fireEvent.click(await screen.findByText('Ada Lovelace <ada@example.com>'))
    fireEvent.click(
      await screen.findByRole('option', { name: /Use a reference/ }),
    )

    expect(onChange).toHaveBeenCalledWith('to', [{ id: '', kind: 'user' }])
    expect(screen.getByRole('button', { name: 'Pick a user' })).toBeVisible()
  })

  it('opens a reference in the text input', () => {
    renderRecipients('{{ trigger.user }}')

    expect(screen.getByDisplayValue('{{ trigger.user }}')).toBeVisible()
  })

  it('keeps each row in its own mode when a row above is removed', async () => {
    renderRecipients('{{ trigger.user }}', 'u1')

    fireEvent.click(screen.getByRole('button', { name: 'Remove recipient 1' }))

    expect(
      await screen.findByText('Ada Lovelace <ada@example.com>'),
    ).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Pick a user' })).toBeNull()
  })
})
