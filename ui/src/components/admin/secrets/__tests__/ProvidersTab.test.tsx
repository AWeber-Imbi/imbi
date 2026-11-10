import { describe, expect, it, vi } from 'vitest'

import {
  createSecretProvider,
  listSecretProviders,
  listSecretProviderTypes,
} from '@/api/endpoints'
import { fireEvent, render, screen, waitFor, within } from '@/test/utils'

import { ProvidersTab } from '../ProvidersTab'

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { id: 'org-1' } }),
}))

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

  it('draws the configuration from the type schema', async () => {
    vi.mocked(listSecretProviders).mockResolvedValue([])
    vi.mocked(createSecretProvider).mockResolvedValue({} as never)
    vi.mocked(listSecretProviderTypes).mockResolvedValue([
      {
        capabilities: [],
        config_schema: {
          properties: {
            region: { title: 'Region', type: 'string' },
            role_arn: { title: 'Role ARN', type: 'string' },
          },
          required: ['region', 'role_arn'],
        },
        credential_classes: ['static', 'rotated'],
        label: 'AWS Secrets Manager',
        locator_schema: null,
        type: 'aws_secrets_manager',
      },
      {
        capabilities: [],
        config_schema: { properties: {} },
        credential_classes: ['dynamic'],
        label: 'Anthropic',
        locator_schema: null,
        type: 'anthropic_wif',
      },
    ])
    render(<ProvidersTab orgSlug="acme" />)
    fireEvent.click(await screen.findByRole('button', { name: 'New provider' }))
    fireEvent.click(screen.getByRole('combobox', { name: 'Type' }))
    fireEvent.click(await screen.findByRole('option', { name: 'Anthropic' }))
    expect(screen.getByText(/takes no configuration/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('combobox', { name: 'Type' }))
    fireEvent.click(
      await screen.findByRole('option', { name: 'AWS Secrets Manager' }),
    )
    expect(screen.getByText(/imbi:org-1/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText(/Name/), {
      target: { value: 'aws-prod' },
    })
    fireEvent.change(screen.getByLabelText(/Region/), {
      target: { value: 'us-east-1' },
    })
    fireEvent.change(screen.getByLabelText(/Role ARN/), {
      target: { value: 'arn:aws:iam::123456789012:role/imbi' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Create provider' }))
    await waitFor(() =>
      expect(createSecretProvider).toHaveBeenCalledWith('acme', {
        config: {
          region: 'us-east-1',
          role_arn: 'arn:aws:iam::123456789012:role/imbi',
        },
        name: 'aws-prod',
        type: 'aws_secrets_manager',
      }),
    )
  })
})
