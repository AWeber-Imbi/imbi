import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { IntegrationsCard } from '@/components/IntegrationsCard'
import { render, screen } from '@/test/utils'

vi.mock('@/api/endpoints', () => ({
  createProjectService: vi.fn(),
  deleteProjectService: vi.fn(),
  listProjectServices: vi.fn(),
  listThirdPartyServices: vi.fn(),
}))

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}))

describe('IntegrationsCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.listThirdPartyServices).mockResolvedValue([])
  })

  it('renders a row per connected service with its URLs', async () => {
    vi.mocked(endpoints.listProjectServices).mockResolvedValue([
      {
        canonical_url: 'https://api.aweber.ghe.com/repositories/138841',
        dashboard_url: 'https://aweber.ghe.com/org/webform',
        identifier: '138841',
        third_party_service_name: 'GitHub',
        third_party_service_slug: 'github',
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
      await screen.findByText(/not connected to any third-party services/i),
    ).toBeInTheDocument()
  })

  it('renders a dash when a URL is absent', async () => {
    vi.mocked(endpoints.listProjectServices).mockResolvedValue([
      {
        canonical_url: null,
        dashboard_url: null,
        identifier: 'cc:webform',
        third_party_service_name: 'SonarQube',
        third_party_service_slug: 'sonarqube',
      },
    ])

    render(<IntegrationsCard orgSlug="aweber" projectId="p1" />)

    expect(await screen.findByText('SonarQube')).toBeInTheDocument()
    // both canonical + dashboard cells render the em-dash placeholder
    expect(screen.getAllByText('—')).toHaveLength(2)
  })
})
