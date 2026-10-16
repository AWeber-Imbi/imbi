import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  linkMcpServerCredential,
  listAgents,
  listSecretProviders,
} from '@/api/endpoints'
import { fireEvent, render, screen, waitFor } from '@/test/utils'
import type { MCPServer } from '@/types'

import { McpServerForm } from '../McpServerForm'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  linkMcpServerCredential: vi.fn(),
  listAgents: vi.fn(),
  listSecretProviders: vi.fn(),
  testMcpServer: vi.fn(),
  testMcpServerConfig: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

const auth = vi.hoisted(() => ({ user: { is_admin: true } }))
// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => auth }))

const server: MCPServer = {
  auth_type: 'none',
  credential_ref: null,
  enabled: true,
  has_oauth_client_secret: false,
  has_static_value: false,
  id: 'srv-1',
  ignored_tools: [],
  name: 'GitHub',
  slug: 'github',
  url: 'https://mcp.github.com/v1/stream',
}

const renderForm = (onSave = vi.fn(), saved: MCPServer = server) => {
  render(<McpServerForm onCancel={vi.fn()} onSave={onSave} server={saved} />)
  return onSave
}

describe('McpServerForm credential reference', () => {
  beforeEach(() => {
    auth.user = { is_admin: true }
    vi.mocked(listSecretProviders).mockResolvedValue([
      { id: 'prov-1', name: 'AWS' } as never,
    ])
    vi.mocked(listAgents).mockResolvedValue([
      { id: 'agent-1', name: 'Release bot' } as never,
    ])
  })

  it('lets an admin set the reference on save', () => {
    const onSave = renderForm()
    fireEvent.change(screen.getByPlaceholderText('secret://mcp/github#token'), {
      target: { value: 'secret://mcp/github#token' },
    })
    fireEvent.click(screen.getByRole('button', { name: /save/i }))
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          credential_ref: 'secret://mcp/github#token',
        }),
      }),
    )
  })

  it('omits an unchanged reference on save', () => {
    const onSave = renderForm(vi.fn(), {
      ...server,
      credential_ref: 'secret://mcp/github#token',
    })
    fireEvent.click(screen.getByRole('button', { name: /save/i }))
    expect(onSave.mock.calls[0][0].data).not.toHaveProperty('credential_ref')
  })

  it('fills the link dialog from the reference in the form', async () => {
    renderForm()
    fireEvent.change(screen.getByPlaceholderText('secret://mcp/github#token'), {
      target: { value: 'secret://mcp/gh#pat' },
    })
    fireEvent.click(
      screen.getByRole('button', { name: 'Link credential for agents' }),
    )
    expect(await screen.findByLabelText(/Reference/)).toHaveValue(
      'secret://mcp/gh',
    )
    expect(screen.getByLabelText(/^Field/)).toHaveValue('pat')
  })

  it('blocks the link until the agents load', async () => {
    vi.mocked(listAgents).mockRejectedValue(new Error('down'))
    renderForm()
    fireEvent.click(
      screen.getByRole('button', { name: 'Link credential for agents' }),
    )
    expect(
      await screen.findByText('Could not load the agents.'),
    ).toBeInTheDocument()
    // Fill every required field, so that only the agents block Save.
    fireEvent.change(screen.getByLabelText(/Reference/), {
      target: { value: 'secret://mcp/github' },
    })
    fireEvent.click(screen.getByRole('combobox', { name: 'Provider' }))
    fireEvent.click(await screen.findByRole('option', { name: 'AWS' }))
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('shows the reference read-only to a non-admin and omits it', () => {
    auth.user = { is_admin: false }
    const onSave = renderForm()
    expect(
      screen.getByPlaceholderText('secret://mcp/github#token'),
    ).toBeDisabled()
    expect(
      screen.queryByRole('button', { name: /link credential/i }),
    ).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /save/i }))
    expect(onSave.mock.calls[0][0].data).not.toHaveProperty('credential_ref')
  })

  it('links the credential for agents in the organization', async () => {
    vi.mocked(linkMcpServerCredential).mockResolvedValue({
      server: { ...server, credential_ref: 'secret://mcp/github#token' },
    } as never)
    renderForm()
    fireEvent.click(
      screen.getByRole('button', { name: 'Link credential for agents' }),
    )
    fireEvent.change(await screen.findByLabelText(/Reference/), {
      target: { value: 'secret://mcp/github' },
    })
    fireEvent.change(screen.getByLabelText(/^Field/), {
      target: { value: 'token' },
    })
    fireEvent.click(screen.getByRole('combobox', { name: 'Provider' }))
    fireEvent.click(await screen.findByRole('option', { name: 'AWS' }))
    fireEvent.change(screen.getByLabelText(/Locator/), {
      target: { value: '{"secret_id": "mcp/github"}' },
    })
    fireEvent.click(await screen.findByLabelText('Release bot'))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(linkMcpServerCredential).toHaveBeenCalledWith('srv-1', {
        agent_ids: ['agent-1'],
        field: 'token',
        locator: { secret_id: 'mcp/github' },
        max_ttl_seconds: 900,
        organization: 'acme',
        provider_id: 'prov-1',
        reference: 'secret://mcp/github',
      }),
    )
    await waitFor(() =>
      expect(
        screen.getByPlaceholderText('secret://mcp/github#token'),
      ).toHaveValue('secret://mcp/github#token'),
    )
  })
})
