import { beforeEach, describe, expect, it, vi } from 'vitest'

import { render, screen, waitFor } from '@/test/utils'
import type { Integration, PluginPackage } from '@/types'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createLoginProvider: vi.fn(),
  getLocalAuthConfig: vi.fn(),
  listLoginProviders: vi.fn(),
  listPluginPackages: vi.fn(),
  setLoginProviderUsedAsLogin: vi.fn(),
  updateLocalAuthConfig: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    user: { is_admin: true, permissions: ['auth_providers:write'] },
  }),
}))

const loginPlugin = (overrides: Partial<PluginPackage> = {}): PluginPackage =>
  ({
    capabilities: [{ hints: { login_capable: true }, kind: 'identity' }],
    enabled: true,
    slug: 'github',
    ...overrides,
  }) as unknown as PluginPackage

const integration = (overrides: Partial<Integration> = {}): Integration =>
  ({
    capabilities: {},
    credential_fields: [],
    identifiers: {},
    links: {},
    name: 'GHEC',
    options: {},
    plugin: 'github',
    slug: 'ghec',
    status: 'active',
    used_as_login: false,
    ...overrides,
  }) as unknown as Integration

describe('AuthProvidersManagement', () => {
  beforeEach(async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.getLocalAuthConfig).mockResolvedValue({
      enabled: true,
      updated_at: '2026-04-01T00:00:00Z',
    })
    vi.mocked(endpoints.listPluginPackages).mockResolvedValue([loginPlugin()])
    vi.mocked(endpoints.listLoginProviders).mockResolvedValue([])
  })

  it('renders the local auth card', async () => {
    const { AuthProvidersManagement } =
      await import('../AuthProvidersManagement')
    render(<AuthProvidersManagement />)
    await waitFor(() =>
      expect(screen.getByText('Local Authentication')).toBeInTheDocument(),
    )
  })

  it('lists global login providers', async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.listLoginProviders).mockResolvedValue([
      integration({ used_as_login: true }),
    ])
    const { AuthProvidersManagement } =
      await import('../AuthProvidersManagement')
    render(<AuthProvidersManagement />)
    await waitFor(() => expect(screen.getByText('GHEC')).toBeInTheDocument())
    expect(screen.getByText('Used for sign-in')).toBeInTheDocument()
  })

  it('shows an empty state when no plugin is login-capable', async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.listPluginPackages).mockResolvedValue([
      loginPlugin({ capabilities: [], slug: 'jira' }),
    ])
    vi.mocked(endpoints.listLoginProviders).mockResolvedValue([])
    const { AuthProvidersManagement } =
      await import('../AuthProvidersManagement')
    render(<AuthProvidersManagement />)
    await waitFor(() =>
      expect(
        screen.getByText(/No login-capable plugins are enabled/i),
      ).toBeInTheDocument(),
    )
  })

  it('offers inline provider creation for enabled login-capable plugins', async () => {
    const { AuthProvidersManagement } =
      await import('../AuthProvidersManagement')
    render(<AuthProvidersManagement />)
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /add auth provider/i }),
      ).toBeInTheDocument(),
    )
  })
})
