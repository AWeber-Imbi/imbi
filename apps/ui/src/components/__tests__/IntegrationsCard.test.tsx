import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { IntegrationsCard } from '@/components/IntegrationsCard'
import { render, screen } from '@/test/utils'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createProjectService: vi.fn(),
  deleteProjectService: vi.fn(),
  listIntegrations: vi.fn(),
  listProjectServices: vi.fn(),
}))

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}))

describe('IntegrationsCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.listIntegrations).mockResolvedValue([])
  })

  it('renders a row per connected service with its URLs', async () => {
    vi.mocked(endpoints.listProjectServices).mockResolvedValue([
      {
        canonical_url: 'https://api.aweber.ghe.com/repositories/138841',
        dashboard_url: 'https://aweber.ghe.com/org/webform',
        identifier: '138841',
        integration_name: 'GitHub',
        integration_slug: 'github',
      },
    ])

    render(<IntegrationsCard orgSlug="aweber" projectId="p1" />)

    expect(await screen.findByText('GitHub')).toBeInTheDocument()
    expect(screen.getByText('138841')).toBeInTheDocument()
    expect(
      screen.getByText('https://api.aweber.ghe.com/repositories/138841'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('https://aweber.ghe.com/org/webform'),
    ).toBeInTheDocument()
  })

  it('shows an empty state when the project exists in no services', async () => {
    vi.mocked(endpoints.listProjectServices).mockResolvedValue([])

    render(<IntegrationsCard orgSlug="aweber" projectId="p1" />)

    expect(
      await screen.findByText(/not connected to any integrations/i),
    ).toBeInTheDocument()
  })

  it('renders a dash when a URL is absent', async () => {
    vi.mocked(endpoints.listProjectServices).mockResolvedValue([
      {
        canonical_url: null,
        dashboard_url: null,
        identifier: 'cc:webform',
        integration_name: 'SonarQube',
        integration_slug: 'sonarqube',
      },
    ])

    render(<IntegrationsCard orgSlug="aweber" projectId="p1" />)

    expect(await screen.findByText('SonarQube')).toBeInTheDocument()
    // both canonical + dashboard cells render the em-dash placeholder
    expect(screen.getAllByText('—')).toHaveLength(2)
  })
})
