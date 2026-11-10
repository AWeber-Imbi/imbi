import { describe, expect, it, vi } from 'vitest'

import { listSecretProviders, listSecretProviderTypes } from '@/api/endpoints'
import { render, screen, within } from '@/test/utils'

import { ProvidersTab } from '../ProvidersTab'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createSecretProvider: vi.fn(),
  deleteSecretProvider: vi.fn(),
  listSecretProviders: vi.fn(),
  listSecretProviderTypes: vi.fn(),
  testSecretProvider: vi.fn(),
  updateSecretProvider: vi.fn(),
}))

const provider = {
  capabilities: ['health_check'],
  config: {},
  enabled: true,
  health_checked_at: null,
  health_reason: 'unreachable',
  health_status: 'unhealthy',
  id: 'p-1',
  name: 'github',
  type: 'github_app',
}

describe('ProvidersTab', () => {
  it('labels the type and disables Test without a health check', async () => {
    vi.mocked(listSecretProviderTypes).mockResolvedValue([
      { capabilities: [], label: 'GitHub App', type: 'github_app' },
    ])
    vi.mocked(listSecretProviders).mockResolvedValue([
      provider,
      {
        ...provider,
        capabilities: [],
        id: 'p-2',
        name: 'acme',
        type: 'acme_wif',
      },
    ] as never)
    render(<ProvidersTab orgSlug="acme" />)
    const github = (await screen.findByText('GitHub App')).closest('tr')!
    expect(within(github).getByRole('button', { name: 'Test' })).toBeEnabled()
    expect(within(github).getByText('unreachable')).toBeInTheDocument()

    const wif = screen.getByText('Acme Wif').closest('tr')!
    expect(within(wif).getByRole('button', { name: 'Test' })).toBeDisabled()
    expect(within(wif).getByText('No test')).toBeInTheDocument()
    expect(within(wif).queryByText('unreachable')).toBeNull()
  })
})
