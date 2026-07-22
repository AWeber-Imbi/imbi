import { describe, expect, it, vi } from 'vitest'

import { render, screen, waitFor } from '@/test/utils'
import type { MCPServer } from '@/types'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createMcpServer: vi.fn(),
  deleteMcpServer: vi.fn(),
  listMcpServers: vi.fn(),
  testMcpServer: vi.fn(),
  testMcpServerConfig: vi.fn(),
  updateMcpServer: vi.fn(),
}))

const sampleServer = (overrides: Partial<MCPServer> = {}): MCPServer => ({
  auth_type: 'oauth_client_credentials',
  created_at: '2026-01-01T00:00:00Z',
  description: 'Read-only GitHub access.',
  enabled: true,
  has_oauth_client_secret: true,
  has_static_value: false,
  id: 'srv-1',
  ignored_tools: [],
  name: 'GitHub',
  slug: 'github',
  status: 'healthy',
  timeout: 30,
  tools_discovered: 18,
  url: 'https://mcp.github.com/v1/stream',
  verify_ssl: true,
  ...overrides,
})

describe('AssistantManagement', () => {
  it('lists configured servers with status and the sub-tabs', async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.listMcpServers).mockResolvedValue([sampleServer()])
    const { AssistantManagement } = await import('../AssistantManagement')
    render(<AssistantManagement />)

    await waitFor(() => expect(screen.getByText('GitHub')).toBeInTheDocument())
    expect(screen.getByText('MCP Servers')).toBeInTheDocument()
    expect(screen.getByText('System Prompts')).toBeInTheDocument()
    expect(screen.getByText('Healthy')).toBeInTheDocument()
    expect(screen.getByText('mcp.github.com/v1/stream')).toBeInTheDocument()
    expect(
      screen.getByRole('switch', { name: /disable github/i }),
    ).toBeInTheDocument()
  })

  it('renders an empty state when no servers are configured', async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.listMcpServers).mockResolvedValue([])
    const { AssistantManagement } = await import('../AssistantManagement')
    render(<AssistantManagement />)

    await waitFor(() =>
      expect(screen.getByText('No MCP servers configured')).toBeInTheDocument(),
    )
  })

  it('reflects disabled servers in the status pill', async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.listMcpServers).mockResolvedValue([
      sampleServer({ enabled: false, status: 'healthy' }),
    ])
    const { AssistantManagement } = await import('../AssistantManagement')
    render(<AssistantManagement />)

    // "Disabled" also labels a filter chip (a <button>); scope to the
    // status pill, which is a <div>.
    await waitFor(() =>
      expect(
        screen.getByText('Disabled', { selector: 'div' }),
      ).toBeInTheDocument(),
    )
  })
})
