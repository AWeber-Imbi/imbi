import { Route, Routes } from 'react-router-dom'

import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { render, screen, within } from '@/test/utils'

import { AgentsArea } from '../AgentsArea'
import { agent, usage } from './fixtures'
import { task } from './taskFixtures'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  countWaitingAgentTasks: vi.fn(),
  getAgentUsage: vi.fn(),
  listAdminUsers: vi.fn(),
  listAgents: vi.fn(),
  listAgentTasks: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/ThemeContext', () => ({
  useTheme: () => ({ isDarkMode: false }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ user: { is_admin: true, permissions: [] } }),
}))

const HOUR = 3_600_000

/** An ISO time `hours` before now. */
const ago = (hours: number) => new Date(Date.now() - hours * HOUR).toISOString()

const OPEN = [
  task({ id: 'T-10', short_id: 'T-10', status: 'running', title: 'Busy' }),
  task({ id: 'T-11', short_id: 'T-11', status: 'queued', title: 'Next' }),
  task({
    blocked_since: ago(3),
    id: 'T-3',
    owner: 'dev@example.com',
    short_id: 'T-3',
    status: 'blocked',
    title: 'Apply the fix',
  }),
  task({
    blocked_since: ago(30),
    id: 'T-2',
    owner: 'pat@example.com',
    short_id: 'T-2',
    status: 'paused',
    title: 'Waiting longest',
  }),
  task({
    blocked_since: ago(1),
    id: 'T-4',
    owner: 'dev@example.com',
    short_id: 'T-4',
    status: 'blocked',
    title: 'Pick a scope',
  }),
]

const closed = (shortId: string, outcome: string, hours: number) =>
  task({
    closed_at: ago(hours),
    id: shortId,
    outcome,
    short_id: shortId,
    status: 'closed',
    title: `${shortId} ${outcome}`,
  })

const RECENT = [
  closed('T-9', 'failed_external', 5),
  closed('T-8', 'done_acted', 1),
  closed('T-7', 'exceeded_ceiling', 2),
  closed('T-6', 'failed_at_gate', 24 * 8),
]

/** The text of each link in a section. */
async function links(name: string) {
  const section = await screen.findByRole('region', { name })
  return within(section)
    .getAllByRole('link')
    .map((a) => a.textContent)
}

function renderAt(path: string) {
  window.history.pushState({}, '', path)
  return render(
    <Routes>
      <Route
        element={<AgentsArea />}
        path="/agents/:section?/:slug?/:action?"
      />
    </Routes>,
  )
}

describe('Dashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.listAdminUsers).mockResolvedValue([])
    vi.mocked(endpoints.listAgents).mockResolvedValue([
      agent(),
      agent({ id: 'agt-2', name: 'Herald', slug: 'herald' }),
    ])
    vi.mocked(endpoints.countWaitingAgentTasks).mockResolvedValue({ count: 3 })
    vi.mocked(endpoints.listAgentTasks).mockImplementation(
      async (_org, params) => (params.status ? OPEN : RECENT),
    )
    vi.mocked(endpoints.getAgentUsage).mockResolvedValue(
      usage({
        agents: [
          { ...usage().agents[0], tasks: 5 },
          { ...usage().agents[0], agent_id: 'agt-2', tasks: 20 },
        ],
      }),
    )
  })

  it('shows the stat tiles', async () => {
    renderAt('/agents/dashboard')
    // The tiles come first; a section can share a tile's label.
    const tile = async (label: string) =>
      (await screen.findAllByText(label))[0].closest('a')?.textContent
    expect(await tile('Running')).toContain('1now')
    expect(await tile('Waiting on people')).toContain('3oldest 1d 6h')
    expect(await tile('Queued')).toContain('1now')
    expect(await tile('Runs')).toContain('25')
    expect(await tile('Spend this month')).toContain('$340.00')
    expect(
      screen.getByRole('img', { name: 'Runs per day' }),
    ).toBeInTheDocument()
  })

  it('orders Needs attention: oldest block, newest failure, then caps', async () => {
    renderAt('/agents/dashboard')
    expect(await links('Needs attention')).toEqual([
      expect.stringContaining('Waiting longest'),
      expect.stringContaining('Apply the fix'),
      expect.stringContaining('Pick a scope'),
      expect.stringContaining('T-7 exceeded_ceiling'),
      expect.stringContaining('T-9 failed_external'),
      expect.stringContaining('Mender is at 85% of its monthly cost cap'),
    ])
    expect(screen.getByText('6 open')).toBeInTheDocument()
  })

  it('ranks the busiest agents by runs', async () => {
    renderAt('/agents/dashboard')
    const section = await screen.findByRole('region', {
      name: 'Busiest agents',
    })
    expect(
      within(section)
        .getAllByRole('listitem')
        .map((li) => li.textContent),
    ).toEqual(['Herald20', 'Mender5'])
  })

  it('groups Waiting on people by owner, longest wait first', async () => {
    renderAt('/agents/dashboard')
    const section = await screen.findByRole('region', {
      name: 'Waiting on people',
    })
    const rows = within(section).getAllByRole('row').slice(1)
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringMatching(/pat.*1.*1d 6h.*1d 6h/),
      expect.stringMatching(/dev.*2.*3h.*2h/),
    ])
    expect(
      within(section).getByText('Median wait').nextSibling,
    ).toHaveTextContent('3h')
  })

  it('lists recent runs newest first', async () => {
    renderAt('/agents/dashboard')
    const rows = await links('Recent runs')
    expect(rows.slice(1)).toEqual([
      expect.stringContaining('T-9'),
      expect.stringContaining('T-8'),
      expect.stringContaining('T-7'),
      expect.stringContaining('T-6'),
    ])
    expect(rows[1]).toContain('Failed')
    expect(rows[2]).toContain('Completed')
  })

  it('shows empty states', async () => {
    vi.mocked(endpoints.listAgents).mockResolvedValue([])
    vi.mocked(endpoints.countWaitingAgentTasks).mockResolvedValue({ count: 0 })
    vi.mocked(endpoints.listAgentTasks).mockResolvedValue([])
    vi.mocked(endpoints.getAgentUsage).mockResolvedValue(
      usage({ agents: [], days: [], month_to_date: {} }),
    )
    renderAt('/agents/dashboard')
    expect(
      await screen.findByText(
        'Nothing needs attention. 0 runs in the last 30 days.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('No runs in the last 30 days.')).toBeInTheDocument()
    expect(
      screen.getByText('Nobody is waiting on a request.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('No tasks yet. Start one with Run on an agent.'),
    ).toBeInTheDocument()
    expect(screen.getByText('nobody waiting')).toBeInTheDocument()
  })
})
