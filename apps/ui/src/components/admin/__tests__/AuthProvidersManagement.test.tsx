import { beforeEach, describe, expect, it, vi } from 'vitest'

import { render, screen, waitFor } from '@/test/utils'
import type { LoginProviderRead } from '@/types'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createAuthProvider: vi.fn(),
  deleteAuthProvider: vi.fn(),
  getLocalAuthConfig: vi.fn(),
  listAuthProviders: vi.fn(),
  updateAuthProvider: vi.fn(),
  updateLocalAuthConfig: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    user: { is_admin: true, permissions: ['auth_providers:write'] },
  }),
}))

const sampleProvider = (
  overrides: Partial<LoginProviderRead> = {},
): LoginProviderRead => ({
  allowed_domains: [],
  authorization_endpoint: null,
  callback_url: 'https://example.com/auth/oauth/google-prod/callback',
  client_id: 'abc',
  description: null,
  has_secret: true,
  issuer_url: null,
  name: 'Google Prod',
  oauth_app_type: 'google',
  organization_name: 'AWeber',
  organization_slug: 'aweber',
  revoke_endpoint: null,
  scopes: [],
  slug: 'google-prod',
  status: 'active',
  third_party_service_name: 'Google Identity',
  third_party_service_slug: 'google-identity',
  token_endpoint: null,
  usage: 'login',
  ...overrides,
})

describe('AuthProvidersManagement', () => {
  beforeEach(async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.getLocalAuthConfig).mockResolvedValue({
      enabled: true,
      updated_at: '2026-04-01T00:00:00Z',
    })
  })

  it('renders the local auth card', async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.listAuthProviders).mockResolvedValue([])
    const { AuthProvidersManagement } =
      await import('../AuthProvidersManagement')
    render(<AuthProvidersManagement />)
    await waitFor(() =>
      expect(screen.getByText('Local Authentication')).toBeInTheDocument(),
    )
  })

  it('renders a login provider card with edit and delete actions', async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.listAuthProviders).mockResolvedValue([
      sampleProvider({ usage: 'login' }),
    ])
    const { AuthProvidersManagement } =
      await import('../AuthProvidersManagement')
    render(<AuthProvidersManagement />)
    await waitFor(() =>
      expect(screen.getByText('Google Prod')).toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: /edit/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /delete/i })).toBeInTheDocument()
    expect(screen.queryByText(/enable integration/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/demote to login/i)).not.toBeInTheDocument()
  })

  it('renders a both row with the same action set', async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.listAuthProviders).mockResolvedValue([
      sampleProvider({ usage: 'both' }),
    ])
    const { AuthProvidersManagement } =
      await import('../AuthProvidersManagement')
    render(<AuthProvidersManagement />)
    await waitFor(() =>
      expect(screen.getByText('Google Prod')).toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: /edit/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /delete/i })).toBeInTheDocument()
    expect(
      screen.queryByText(/delete: demote integration first/i),
    ).not.toBeInTheDocument()
  })
})
