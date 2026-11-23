import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { agent, usage } from '@/components/agents/__tests__/fixtures'
import { fireEvent, render, screen } from '@/test/utils'

import { AgentUsageReport } from '../AgentUsageReport'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  getAgentUsage: vi.fn(),
  listAgents: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

const auth = vi.hoisted(() => ({
  user: {
    is_admin: true,
    organizations: [{ organization_slug: 'acme', permissions: [] as string[] }],
    permissions: [] as string[],
  },
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => auth }))

describe('AgentUsageReport', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    auth.user = {
      is_admin: true,
      organizations: [{ organization_slug: 'acme', permissions: [] }],
      permissions: [],
    }
    vi.mocked(endpoints.listAgents).mockResolvedValue([agent()])
    vi.mocked(endpoints.getAgentUsage).mockResolvedValue(usage())
  })

  it('shows totals, the agent table, and cap warnings', async () => {
    render(<AgentUsageReport />)
    expect(await screen.findByText('Usage by agent')).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Mender spent $340.00 of $400.00 this month (85%).',
    )
    // Tokens in counts cache reads: 1,000 + 3,000.
    const total = screen.getByText('Total').closest('tr')!
    expect(total).toHaveTextContent('4,000')
    expect(total).toHaveTextContent('75%')
    expect(total).toHaveTextContent('$12.50')
    expect(
      screen.getByRole('img', { name: 'Cost per day by agent' }),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio', { name: 'Token usage' }))
    expect(
      screen.getByRole('img', { name: 'Tokens per day by agent' }),
    ).toBeInTheDocument()
  })

  it('names an agent that no longer exists as deleted', async () => {
    vi.mocked(endpoints.listAgents).mockResolvedValue([])
    render(<AgentUsageReport />)
    expect(
      (await screen.findAllByText('Deleted agt-1')).length,
    ).toBeGreaterThan(0)
  })

  it('says only how many reports had no price', async () => {
    vi.mocked(endpoints.getAgentUsage).mockResolvedValue(
      usage({ unpriced_reports: 2 }),
    )
    render(<AgentUsageReport />)
    expect(
      await screen.findByText('2 usage reports had no price and count as $0.'),
    ).toBeInTheDocument()
  })

  it('hides the unpriced line when every report had a price', async () => {
    render(<AgentUsageReport />)
    await screen.findByText('Usage by agent')
    expect(screen.queryByText(/had no price/)).not.toBeInTheDocument()
  })

  it('says so when the user may not read tickets', () => {
    auth.user = {
      is_admin: false,
      organizations: [
        { organization_slug: 'acme', permissions: ['agent:read'] },
      ],
      permissions: ['agent:read'],
    }
    render(<AgentUsageReport />)
    expect(screen.getByText(/ticket:read/)).toBeInTheDocument()
    expect(endpoints.getAgentUsage).not.toHaveBeenCalled()
  })
})
