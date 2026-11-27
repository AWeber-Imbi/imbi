import { describe, expect, it, vi } from 'vitest'

import { fireEvent, render, screen, waitFor } from '@/test/utils'
import type { MCPServer } from '@/types'

import { McpServerForm } from '../McpServerForm'

const REF = 'secret://production/mcp/token'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  listSecretBindings: vi.fn().mockResolvedValue([
    {
      credential_class: 'static',
      enabled: true,
      reference: 'secret://production/mcp/token',
    },
  ]),
  testMcpServer: vi.fn(),
  testMcpServerConfig: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

const server = (overrides: Partial<MCPServer> = {}): MCPServer => ({
  auth_type: 'static',
  enabled: true,
  has_oauth_client_secret: false,
  has_static_value: false,
  id: 'srv-1',
  ignored_tools: [],
  name: 'GitHub',
  slug: 'github',
  static_header: 'Authorization',
  static_value_ref: REF,
  status: 'healthy',
  timeout: 30,
  url: 'https://mcp.github.com/v1/stream',
  verify_ssl: true,
  ...overrides,
})

describe('McpServerForm secret binding', () => {
  it('shows the binding in place of the stored value', async () => {
    render(
      <McpServerForm onCancel={vi.fn()} onSave={vi.fn()} server={server()} />,
    )
    await waitFor(() => expect(screen.getByText(REF)).toBeInTheDocument())
    // The write-only value field is hidden while a binding is chosen.
    expect(screen.queryByText('Not set')).not.toBeInTheDocument()
  })

  it('sends the binding and no stored value', () => {
    const onSave = vi.fn()
    render(
      <McpServerForm onCancel={vi.fn()} onSave={onSave} server={server()} />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }))
    const { data } = onSave.mock.calls[0][0]
    expect(data.static_value_ref).toBe(REF)
    expect(data).not.toHaveProperty('static_value')
  })

  it('clears a stored value when a binding replaces it', () => {
    const onSave = vi.fn()
    render(
      <McpServerForm
        onCancel={vi.fn()}
        onSave={onSave}
        server={server({ has_static_value: true })}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }))
    expect(onSave.mock.calls[0][0].data.static_value).toBeNull()
  })
})
