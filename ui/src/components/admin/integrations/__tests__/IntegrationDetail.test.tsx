import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  getIntegration,
  listPluginPackages,
  listProjectTypes,
  updateIntegration,
} from '@/api/endpoints'
import { fireEvent, render, screen, waitFor } from '@/test/utils'
import type { Integration } from '@/types'

import { IntegrationDetail } from '../IntegrationDetail'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  deleteIntegration: vi.fn(),
  getIntegration: vi.fn(),
  listCapabilityAssignments: vi.fn(),
  listPluginPackages: vi.fn(),
  listProjectTypes: vi.fn(),
  listWebhooks: vi.fn(),
  replaceCapabilityAssignments: vi.fn(),
  updateIntegration: vi.fn(),
  updateIntegrationCredentials: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

const integration = (status: string) =>
  ({
    capabilities: {},
    credential_fields: [],
    id: 'i-1',
    name: 'GitHub',
    options: {},
    plugin: 'github',
    slug: 'github',
    status,
  }) as unknown as Integration

const renderDetail = (status: string) => {
  vi.mocked(getIntegration).mockResolvedValue(integration(status))
  return render(
    <IntegrationDetail
      onBack={vi.fn()}
      seed={integration(status)}
      slug="github"
    />,
  )
}

describe('IntegrationDetail danger zone', () => {
  beforeEach(() => {
    vi.mocked(listPluginPackages).mockResolvedValue([])
    vi.mocked(listProjectTypes).mockResolvedValue([])
    vi.mocked(updateIntegration).mockResolvedValue({} as never)
  })

  it('disables an active integration', async () => {
    renderDetail('active')
    fireEvent.click(await screen.findByRole('button', { name: 'Disable' }))
    await waitFor(() =>
      expect(updateIntegration).toHaveBeenCalledWith('acme', 'github', {
        status: 'inactive',
      }),
    )
  })

  it('enables an inactive integration', async () => {
    renderDetail('inactive')
    expect(await screen.findByText('Enable integration')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Enable' }))
    await waitFor(() =>
      expect(updateIntegration).toHaveBeenCalledWith('acme', 'github', {
        status: 'active',
      }),
    )
  })
})
