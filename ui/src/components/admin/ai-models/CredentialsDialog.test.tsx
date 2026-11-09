import { describe, expect, it, vi } from 'vitest'

import { listTokenExchangers } from '@/api/endpoints'
import { fireEvent, render, screen, waitFor } from '@/test/utils'
import type { AIProvider } from '@/types'

import { CredentialsDialog } from './CredentialsDialog'

vi.mock('@/api/endpoints', () => ({
  listTokenExchangers: vi.fn().mockResolvedValue([
    {
      label: 'Anthropic',
      target_help: '{"service_account_id": "..."}, from the Console.',
      vendor: 'anthropic',
    },
  ]),
}))

vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({
    organizations: [{ id: 'org-1', name: 'Acme', slug: 'acme' }],
    selectedOrganization: { id: 'org-1', name: 'Acme', slug: 'acme' },
  }),
}))

const provider: AIProvider = {
  auth_kind: 'none',
  base_url: null,
  credential_hint: null,
  credential_updated_at: null,
  description: null,
  driver: 'anthropic',
  enabled: true,
  enabled_model_count: 0,
  has_credentials: false,
  id: 'prov-1',
  is_builtin_driver: true,
  model_count: 0,
  name: 'Anthropic',
  project_id: null,
  region: null,
  slug: 'anthropic',
}

const handlers = () => ({
  onClose: vi.fn(),
  onRemove: vi.fn(),
  onRemoveWorkloadIdentity: vi.fn(),
  onSave: vi.fn(),
  onSaveWorkloadIdentity: vi.fn(),
})

describe('CredentialsDialog workload identity', () => {
  it('sets workload identity for the selected organization', async () => {
    const on = handlers()
    render(
      <CredentialsDialog {...on} isPending={false} open provider={provider} />,
    )
    const use = await screen.findByRole('button', {
      name: 'Use workload identity',
    })
    expect(use).toBeDisabled()
    expect(screen.getByText(/from the Console\./)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Workload identity target'), {
      target: { value: '{"service_account_id": "svc-1"}' },
    })
    fireEvent.click(use)
    expect(on.onSaveWorkloadIdentity).toHaveBeenCalledWith({
      organization: 'acme',
      target: { service_account_id: 'svc-1' },
    })
  })

  it('shows and removes workload identity', () => {
    const on = handlers()
    render(
      <CredentialsDialog
        {...on}
        isPending={false}
        open
        provider={{
          ...provider,
          auth_kind: 'workload_identity',
          workload_identity: {
            organization_id: 'org-1',
            target: { service_account_id: 'svc-1' },
          },
        }}
      />,
    )
    expect(screen.getByText(/identity source of\s+Acme/)).toBeInTheDocument()
    expect(screen.queryByLabelText('API key')).toBeNull()
    fireEvent.click(
      screen.getByRole('button', { name: 'Stop using workload identity' }),
    )
    expect(on.onRemoveWorkloadIdentity).toHaveBeenCalled()
  })

  it('offers no workload identity without an installed exchanger', async () => {
    render(
      <CredentialsDialog
        {...handlers()}
        isPending={false}
        open
        provider={{ ...provider, driver: 'openai' }}
      />,
    )
    await waitFor(() => expect(listTokenExchangers).toHaveBeenCalled())
    expect(
      screen.queryByRole('button', { name: 'Use workload identity' }),
    ).toBeNull()
  })

  it('offers no workload identity for a provider with a key', () => {
    render(
      <CredentialsDialog
        {...handlers()}
        isPending={false}
        open
        provider={{ ...provider, auth_kind: 'api_key', has_credentials: true }}
      />,
    )
    expect(
      screen.queryByRole('button', { name: 'Use workload identity' }),
    ).toBeNull()
  })
})
