import { fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as search from '@/api/search'
import { render, screen } from '@/test/utils'

import { TopBarSearch } from '../TopBarSearch'

const send = vi.fn()

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/search', async (importOriginal) => ({
  ...(await importOriginal<typeof search>()),
  searchOrg: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useSearchEnrichment', () => ({
  useSearchEnrichment: () => new Map(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAssistantChat', () => ({
  newAssistantConversation: vi.fn(),
  useAssistantChat: () => ({ send }),
}))

function hit(node_id: string, node_label: string, name: string) {
  return {
    attribute: 'name',
    chunk_text: name,
    distance: 0.1,
    name,
    node_id,
    node_label,
    project_id: 'p-1',
  }
}

describe('TopBarSearch', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(search.searchOrg).mockResolvedValue([
      hit('d-1', 'Document', 'Account Playbook'),
      hit('p-1', 'Project', 'Account'),
      // A second attribute match of the same node is one row.
      { ...hit('p-1', 'Project', 'Account'), attribute: 'description' },
    ])
  })

  it('groups one row per node, projects first', async () => {
    render(<TopBarSearch />)
    fireEvent.change(screen.getByLabelText('Search Imbi'), {
      target: { value: 'account' },
    })
    await screen.findByText('Account Playbook')
    const options = screen.getAllByRole('option').map((o) => o.textContent)
    expect(options).toHaveLength(3)
    expect(options[0]).toContain('Account')
    expect(options[1]).toContain('Account Playbook')
    expect(options[2]).toContain('Ask Imbi about “account”')
  })

  it('hands the query to the assistant on Tab', async () => {
    render(<TopBarSearch />)
    const input = screen.getByLabelText('Search Imbi')
    fireEvent.change(input, { target: { value: 'account' } })
    await screen.findByText('Account Playbook')
    fireEvent.keyDown(input, { key: 'Tab' })
    await waitFor(() => expect(send).toHaveBeenCalledOnce())
    const [content, display] = send.mock.calls[0]
    expect(display).toBe('account')
    expect(content).toContain('<search_context>')
  })
})
