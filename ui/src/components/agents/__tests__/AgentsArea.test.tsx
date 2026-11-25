import { Route, Routes } from 'react-router-dom'

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import * as endpoints from '@/api/endpoints'
import { fireEvent, render, screen, waitFor, within } from '@/test/utils'

import { AgentsArea } from '../AgentsArea'
import { agent, catalog, promptVersion, usage } from './fixtures'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createAgent: vi.fn(),
  createPrompt: vi.fn(),
  createPromptVersion: vi.fn(),
  createTag: vi.fn(),
  deleteAgent: vi.fn(),
  deleteUpload: vi.fn(),
  getAgentPlatformConfig: vi.fn(),
  getAgentToolCatalog: vi.fn(),
  getAgentUsage: vi.fn(),
  getUploadThumbnailUrl: vi.fn(),
  listAgentMarketplaces: vi.fn(),
  listAgents: vi.fn(),
  listAgentVersions: vi.fn(),
  listAIModels: vi.fn(),
  listEnvironments: vi.fn(),
  listTags: vi.fn(),
  listTeams: vi.fn(),
  listTickets: vi.fn(),
  listWorkflows: vi.fn(),
  listWorkflowStepTypes: vi.fn(),
  patchAgent: vi.fn(),
  resolvePrompt: vi.fn(),
  restoreAgentVersion: vi.fn(),
  setPromptLabel: vi.fn(),
  updateAgent: vi.fn(),
  uploadFile: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/ThemeContext', () => ({
  useTheme: () => ({ isDarkMode: false }),
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

describe('AgentsArea', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    auth.user = {
      is_admin: true,
      organizations: [{ organization_slug: 'acme', permissions: [] }],
      permissions: [],
    }
    vi.mocked(endpoints.listAgents).mockResolvedValue([
      agent(),
      agent({
        enabled: false,
        id: 'agt-2',
        name: 'Herald',
        prompt_ref: null,
        slug: 'herald',
        tags: [],
      }),
    ])
    vi.mocked(endpoints.resolvePrompt).mockResolvedValue({
      label: 'stable',
      ref: 'agents/mender@stable',
      version: promptVersion(),
    })
    vi.mocked(endpoints.listTeams).mockResolvedValue([])
    vi.mocked(endpoints.listTags).mockResolvedValue([])
    vi.mocked(endpoints.listAIModels).mockResolvedValue([])
    vi.mocked(endpoints.listAgentVersions).mockResolvedValue([])
    vi.mocked(endpoints.getAgentToolCatalog).mockResolvedValue(catalog())
    vi.mocked(endpoints.listEnvironments).mockResolvedValue([])
    vi.mocked(endpoints.getAgentUsage).mockResolvedValue(usage())
  })

  it('shows the workflows page and the agent count', async () => {
    vi.mocked(endpoints.listWorkflows).mockResolvedValue([])
    vi.mocked(endpoints.listWorkflowStepTypes).mockResolvedValue([])
    renderAt('/agents/workflows')
    expect(await screen.findByText('No workflows yet.')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('2')).toBeInTheDocument())
  })

  it('shows Runners and Egress Destinations to an administrator', async () => {
    vi.mocked(endpoints.listWorkflows).mockResolvedValue([])
    vi.mocked(endpoints.listWorkflowStepTypes).mockResolvedValue([])
    renderAt('/agents/workflows')
    const nav = await screen.findByRole('navigation', { name: 'Agents' })
    expect(nav).toHaveTextContent('Runners')
    expect(nav).toHaveTextContent('Egress Destinations')
  })

  it('hides Egress Destinations from a runner reader', async () => {
    auth.user = {
      is_admin: false,
      organizations: [
        { organization_slug: 'acme', permissions: ['harness_pool:read'] },
      ],
      permissions: ['harness_pool:read'],
    }
    vi.mocked(endpoints.listWorkflows).mockResolvedValue([])
    vi.mocked(endpoints.listWorkflowStepTypes).mockResolvedValue([])
    renderAt('/agents/egress')
    await waitFor(() =>
      expect(window.location.pathname).toBe('/agents/dashboard'),
    )
    const nav = screen.getByRole('navigation', { name: 'Agents' })
    expect(nav).toHaveTextContent('Runners')
    expect(nav).not.toHaveTextContent('Egress Destinations')
    expect(nav).not.toHaveTextContent('AI Models')
    expect(nav).not.toHaveTextContent('Secrets')
  })

  it('lists the Settings pages in alphabetical order', async () => {
    vi.mocked(endpoints.listWorkflows).mockResolvedValue([])
    vi.mocked(endpoints.listWorkflowStepTypes).mockResolvedValue([])
    renderAt('/agents/workflows')
    const nav = await screen.findByRole('navigation', { name: 'Agents' })
    const labels = within(nav)
      .getAllByRole('link')
      .map((link) => link.getAttribute('title'))
    expect(labels).toEqual([
      'Dashboard',
      'Agents',
      'AI Models',
      'Egress Destinations',
      'Platform',
      'Runners',
      'Secrets',
      'Workflows',
    ])
  })

  it('toggles enabled from the list without opening the agent', async () => {
    vi.mocked(endpoints.patchAgent).mockResolvedValue(agent())
    renderAt('/agents/manage')
    const toggle = await screen.findByRole('switch', { name: 'Enable Herald' })
    fireEvent.click(toggle)
    await waitFor(() =>
      expect(endpoints.patchAgent).toHaveBeenCalledWith('acme', 'herald', [
        { op: 'replace', path: '/enabled', value: true },
      ]),
    )
    expect(window.location.pathname).toBe('/agents/manage')
  })

  it('hides write controls without agent permissions', async () => {
    auth.user = {
      is_admin: false,
      organizations: [
        { organization_slug: 'acme', permissions: ['agent:read'] },
      ],
      permissions: ['agent:read'],
    }
    renderAt('/agents/manage')
    await screen.findByText('Herald')
    expect(screen.queryByRole('switch')).not.toBeInTheDocument()
    expect(screen.queryByText('New Agent')).not.toBeInTheDocument()
  })

  it('shows the model from the stable prompt on the detail page', async () => {
    renderAt('/agents/manage/mender')
    await screen.findByText('claude-sonnet')
    expect(screen.getByText('v3')).toBeInTheDocument()
    expect(
      await screen.findByText('$340.00 of $400.00', { exact: false }),
    ).toBeInTheDocument()
    expect(screen.getByText('30m')).toBeInTheDocument()
    fireEvent.mouseDown(screen.getByRole('tab', { name: 'System prompt' }))
    expect(await screen.findByText('You fix bugs.')).toBeInTheDocument()
  })

  it('lists the tickets of the agent on the History tab', async () => {
    vi.mocked(endpoints.listTickets).mockResolvedValue([
      {
        closed_at: '2026-11-20T10:09:12Z',
        cost_total: '0.19',
        id: 't-1',
        origin: { kind: 'schedule' },
        outcome: 'done_acted',
        run_started_at: '2026-11-20T10:00:00Z',
        short_id: 'TKT-42',
        status: 'closed',
        title: 'Fix the flaky test',
      },
    ] as unknown as Awaited<ReturnType<typeof endpoints.listTickets>>)
    renderAt('/agents/manage/mender')
    fireEvent.mouseDown(await screen.findByRole('tab', { name: 'History' }))
    const link = await screen.findByRole('link', { name: 'TKT-42' })
    expect(link).toHaveAttribute('href', '/tickets/acme/TKT-42')
    expect(endpoints.listTickets).toHaveBeenCalledWith(
      'acme',
      { agent_id: ['agt-1'], limit: 100 },
      expect.anything(),
    )
    const row = link.closest('tr') as HTMLElement
    expect(within(row).getByText('Fix the flaky test')).toBeInTheDocument()
    expect(within(row).getByText('Completed')).toBeInTheDocument()
    expect(within(row).getByText('9m 12s')).toBeInTheDocument()
    expect(within(row).getByText('$0.19')).toBeInTheDocument()
    expect(within(row).getByText('Schedule')).toBeInTheDocument()
  })

  it('shows runs, cost, and the cap warning on the detail page', async () => {
    renderAt('/agents/manage/mender')
    expect(await screen.findByText('85% of cap')).toBeInTheDocument()
    expect(endpoints.getAgentUsage).toHaveBeenCalledWith(
      'acme',
      { agent_id: 'agt-1' },
      expect.anything(),
    )
    const runs = screen.getByText('Runs (30 days)').nextElementSibling
    expect(runs).toHaveTextContent('5')
    expect(screen.getByText('Cost over time')).toBeInTheDocument()
    expect(
      screen.getByRole('img', { name: 'Cost and runs per day' }),
    ).toBeInTheDocument()
    // Avg / run is $12.50 / 5 tasks.
    expect(screen.getByText('$2.50')).toBeInTheDocument()
  })

  it('shows runs, cost, and average per run in the agent list', async () => {
    renderAt('/agents/manage')
    const mender = (await screen.findByText('Mender')).closest('tr')!
    await waitFor(() => expect(mender).toHaveTextContent('$12.50'))
    expect(mender).toHaveTextContent('$2.50')
    const herald = screen.getByText('Herald').closest('tr')!
    expect(herald).toHaveTextContent('$0.00')
    expect(herald).toHaveTextContent('—')
  })

  it('sorts the agent list by a column header', async () => {
    renderAt('/agents/manage')
    await screen.findByText('Mender')
    const names = () =>
      screen
        .getAllByRole('row')
        .slice(1)
        .map((r) => r.textContent ?? '')
        .map((t) => (t.includes('Mender') ? 'Mender' : 'Herald'))
    expect(names()).toEqual(['Mender', 'Herald'])
    fireEvent.click(screen.getByRole('button', { name: 'Name' }))
    expect(names()).toEqual(['Herald', 'Mender'])
    fireEvent.click(
      screen.getByRole('button', { name: 'Name, sorted ascending' }),
    )
    expect(names()).toEqual(['Mender', 'Herald'])
    expect(
      screen.getByRole('button', { name: 'Name, sorted descending' }),
    ).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getAllByRole('row')[1]).toHaveTextContent('$12.50'),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Cost 30d' }))
    expect(names()).toEqual(['Herald', 'Mender'])
  })

  it('sends the old Usage page to the Agent Usage report', async () => {
    renderAt('/agents/usage')
    await waitFor(() =>
      expect(window.location.pathname).toBe('/reports/agent-usage'),
    )
  })

  it('saves a prompt change: version, then label, then agent', async () => {
    const order: string[] = []
    vi.mocked(endpoints.createPromptVersion).mockImplementation(async () => {
      order.push('version')
      return promptVersion({ n: 3 })
    })
    vi.mocked(endpoints.setPromptLabel).mockImplementation(async () => {
      order.push('label')
      return {} as never
    })
    vi.mocked(endpoints.updateAgent).mockImplementation(async () => {
      order.push('agent')
      return agent()
    })
    renderAt('/agents/manage/mender/edit')
    await screen.findByText('Edit Mender')
    fireEvent.click(screen.getByRole('tab', { name: 'System prompt' }))
    fireEvent.change(screen.getByLabelText('System prompt'), {
      target: { value: 'You fix bugs carefully.' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Save Changes/ }))
    await waitFor(() =>
      expect(window.location.pathname).toBe('/agents/manage/mender'),
    )
    expect(order).toEqual(['version', 'label', 'agent'])
    expect(vi.mocked(endpoints.setPromptLabel).mock.calls[0]).toEqual([
      'agents',
      'acme.mender',
      'stable',
      3,
    ])
  })

  it('shows the failed step and does not write the agent', async () => {
    vi.mocked(endpoints.createPromptVersion).mockResolvedValue(
      promptVersion({ n: 3 }),
    )
    vi.mocked(endpoints.setPromptLabel).mockRejectedValue(
      new ApiError(403, 'Forbidden', { detail: 'Permission denied' }),
    )
    renderAt('/agents/manage/mender/edit')
    await screen.findByText('Edit Mender')
    fireEvent.click(screen.getByRole('tab', { name: 'System prompt' }))
    fireEvent.change(screen.getByLabelText('System prompt'), {
      target: { value: 'Changed' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Save Changes/ }))
    expect(await screen.findByText('Save failed')).toBeInTheDocument()
    expect(
      screen.getByText(/Saved prompt version 3, but could not move the stable/),
    ).toBeInTheDocument()
    expect(endpoints.updateAgent).not.toHaveBeenCalled()
    expect(window.location.pathname).toBe('/agents/manage/mender/edit')
  })

  it('shows the prompt version of each agent version', async () => {
    const snapshot = { name: 'Mender', slug: 'mender', team: 'platform' }
    vi.mocked(endpoints.listAgentVersions).mockResolvedValue([
      {
        created_at: '2026-10-02T12:00:00Z',
        created_by: 'gavin@example.com',
        n: 3,
        snapshot: { ...snapshot, prompt_version: 7 },
        summary: 'prompt v7',
      },
      {
        created_at: '2026-10-01T12:00:00Z',
        created_by: 'gavin@example.com',
        n: 2,
        snapshot: {
          ...snapshot,
          prompt_ref: 'agents/mender',
          prompt_version: 4,
        },
        summary: 'Changed name',
      },
    ])
    renderAt('/agents/manage/mender/edit')
    await screen.findByText('Edit Mender')
    fireEvent.click(screen.getByRole('tab', { name: 'Version history' }))
    expect(await screen.findByText(/· prompt v4$/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Restore' }))
    expect(
      await screen.findByText(
        /come back too\. Moves agents\/mender@stable to prompt v4\./,
      ),
    ).toBeInTheDocument()
  })

  it('names no label move when the version has no prompt version', async () => {
    const snapshot = { name: 'Mender', slug: 'mender', team: 'platform' }
    vi.mocked(endpoints.listAgentVersions).mockResolvedValue([
      {
        created_at: '2026-10-01T12:00:00Z',
        created_by: 'gavin@example.com',
        n: 2,
        snapshot: { ...snapshot, prompt_ref: 'agents/mender@stable' },
        summary: 'Changed name',
      },
    ])
    renderAt('/agents/manage/mender/edit')
    await screen.findByText('Edit Mender')
    fireEvent.click(screen.getByRole('tab', { name: 'Version history' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Restore' }))
    expect(
      await screen.findByText(/configuration of v2\. Unsaved edits/),
    ).toBeInTheDocument()
    expect(screen.queryByText(/Moves /)).not.toBeInTheDocument()
  })

  it('blocks a save with no name and no team', async () => {
    renderAt('/agents/manage/new')
    await screen.findByText('New Agent')
    fireEvent.click(screen.getByRole('button', { name: /Create Agent/ }))
    expect(
      await screen.findByText('Agent name is required'),
    ).toBeInTheDocument()
    expect(screen.getByText('Owner team is required')).toBeInTheDocument()
    expect(endpoints.createAgent).not.toHaveBeenCalled()
  })

  it('counts the built-in tools in the detail page total', async () => {
    vi.mocked(endpoints.getAgentToolCatalog).mockResolvedValue({
      ...catalog(),
      builtin_tools: [
        {
          capability: 'read',
          description: 'Load a skill.',
          key: 'builtin.Skill',
          name: 'Skill',
        },
      ],
    })
    vi.mocked(endpoints.listAgents).mockResolvedValue([
      agent({
        tools: {
          'builtin.Skill': { approval: false },
          'imbi.list_projects': { approval: false },
        },
      }),
    ])
    renderAt('/agents/manage/mender')
    expect(await screen.findByText('2 of 5 enabled')).toBeInTheDocument()
  })

  it('shows the enabled tools by prefix on the detail page', async () => {
    vi.mocked(endpoints.listAgents).mockResolvedValue([
      agent({
        tools: {
          'imbi.delete_project': { approval: true },
          'imbi.list_projects': { approval: false },
          'zoekt.search': { approval: false },
        },
      }),
    ])
    renderAt('/agents/manage/mender')
    expect(await screen.findByText('3 of 4 enabled')).toBeInTheDocument()
    expect(screen.getByText('Tools and MCP access')).toBeInTheDocument()
    expect(
      screen.getByText('delete_project, list_projects'),
    ).toBeInTheDocument()
    expect(screen.getByText('imbi')).toBeInTheDocument()
    expect(screen.getByText('zoekt')).toBeInTheDocument()
    expect(screen.getByText('search')).toBeInTheDocument()
  })

  it('shows the plugins and their MCP servers on the detail page', async () => {
    vi.mocked(endpoints.listAgents).mockResolvedValue([
      agent({
        settings: {
          ...agent().settings!,
          plugins: [
            {
              marketplace: 'aweber',
              plugin: 'posthog-mcp',
              sha: 'e7c67c3aaaaaaaa',
            },
          ],
        },
      }),
    ])
    vi.mocked(endpoints.listAgentMarketplaces).mockResolvedValue([
      {
        plugins: [
          {
            mcp_servers: [{ headers: {}, name: 'posthog', type: 'http' }],
            name: 'posthog-mcp',
          },
        ],
        slug: 'aweber',
      },
    ] as never)
    renderAt('/agents/manage/mender')
    expect(
      await screen.findByText('1 plugin · 0 of 4 enabled'),
    ).toBeInTheDocument()
    expect(screen.getByText('posthog-mcp')).toBeInTheDocument()
    expect(screen.getByText('aweber @ e7c67c3')).toBeInTheDocument()
    expect(await screen.findByText('MCP: posthog')).toBeInTheDocument()
    expect(screen.queryByText('No tools enabled.')).not.toBeInTheDocument()
  })

  it('shows the subagents on the detail page', async () => {
    vi.mocked(endpoints.listAgents).mockResolvedValue([
      agent({
        subagents: [
          {
            agent_id: 'agt-2',
            icon: null,
            instructions: '',
            name: 'Herald',
            slug: 'herald',
            tool_count: 1,
            version: 5,
          },
        ],
      }),
    ])
    renderAt('/agents/manage/mender')
    expect(await screen.findByText('Herald')).toBeInTheDocument()
    expect(screen.getByText('v5 · 1 tool')).toBeInTheDocument()
  })

  it('shows the empty subagents text on the detail page', async () => {
    renderAt('/agents/manage/mender')
    expect(
      await screen.findByText(
        'No subagents. This agent does all of its own work.',
      ),
    ).toBeInTheDocument()
  })

  it('saves a subagent change from the Subagents tab', async () => {
    vi.mocked(endpoints.listAgents).mockResolvedValue([
      agent(),
      agent({ id: 'agt-2', name: 'Herald', prompt_ref: null, slug: 'herald' }),
    ])
    vi.mocked(endpoints.updateAgent).mockResolvedValue(agent())
    renderAt('/agents/manage/mender/edit')
    await screen.findByText('Edit Mender')
    const tab = screen.getByRole('tab', { name: /Subagents/ })
    expect(tab).toHaveTextContent('Subagents0')
    fireEvent.click(tab)
    fireEvent.click(
      await screen.findByRole('checkbox', { name: 'Delegate to Herald' }),
    )
    expect(tab).toHaveTextContent('Subagents1')
    fireEvent.click(screen.getByRole('button', { name: /Save Changes/ }))
    await waitFor(() => expect(endpoints.updateAgent).toHaveBeenCalled())
    expect(vi.mocked(endpoints.updateAgent).mock.calls[0][2]).toEqual(
      expect.objectContaining({
        subagents: [{ agent_id: 'agt-2', instructions: '' }],
        version_summary: 'Changed subagents',
      }),
    )
  })

  it('locks delete while other agents delegate to the agent', async () => {
    vi.mocked(endpoints.listAgents).mockResolvedValue([
      agent(),
      agent({
        id: 'agt-2',
        name: 'Herald',
        slug: 'herald',
        subagents: [
          {
            agent_id: 'agt-1',
            icon: null,
            instructions: '',
            name: 'Mender',
            slug: 'mender',
            tool_count: 0,
            version: 3,
          },
        ],
      }),
    ])
    renderAt('/agents/manage/mender/edit')
    await screen.findByText('Edit Mender')
    fireEvent.click(screen.getByRole('tab', { name: 'Version history' }))
    expect(
      await screen.findByText(/Mender is a subagent of 1 agent\. Remove it/),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete agent' })).toBeDisabled()
    expect(screen.getByRole('link', { name: 'Herald' })).toHaveAttribute(
      'href',
      '/agents/manage/herald',
    )
  })

  it('allows delete when no agent delegates to the agent', async () => {
    renderAt('/agents/manage/mender/edit')
    await screen.findByText('Edit Mender')
    fireEvent.click(screen.getByRole('tab', { name: 'Version history' }))
    expect(
      await screen.findByText(/Deletes the agent and its version history/),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete agent' })).toBeEnabled()
  })

  it('counts the plugins on the Tools and plugins tab', async () => {
    vi.mocked(endpoints.listAgents).mockResolvedValue([
      agent({
        settings: {
          ...agent().settings!,
          plugins: [{ marketplace: 'aweber', plugin: 'posthog-mcp' }],
        },
      }),
    ])
    renderAt('/agents/manage/mender/edit')
    await screen.findByText('Edit Mender')
    expect(
      screen.getByRole('tab', { name: /Tools and plugins/ }),
    ).toHaveTextContent('Tools and plugins1')
  })

  it('saves a tool change from the Tools and plugins tab', async () => {
    vi.mocked(endpoints.updateAgent).mockResolvedValue(agent())
    vi.mocked(endpoints.getAgentPlatformConfig).mockResolvedValue({
      config: { allowed_marketplaces: [], default_plugins: [] },
      version: 1,
    } as never)
    vi.mocked(endpoints.listAgentMarketplaces).mockResolvedValue([])
    renderAt('/agents/manage/mender/edit')
    await screen.findByText('Edit Mender')
    const tab = screen.getByRole('tab', { name: /Tools and plugins/ })
    expect(tab).toHaveTextContent('Tools and plugins0')
    fireEvent.click(tab)
    await screen.findAllByText('0 of 4 enabled')
    fireEvent.click(screen.getByRole('switch', { name: 'Enable imbi.get_me' }))
    expect(tab).toHaveTextContent('Tools and plugins1')
    fireEvent.click(screen.getByRole('button', { name: /Save Changes/ }))
    await waitFor(() => expect(endpoints.updateAgent).toHaveBeenCalled())
    expect(vi.mocked(endpoints.updateAgent).mock.calls[0][2]).toEqual(
      expect.objectContaining({
        tools: {
          'imbi.get_me': {
            approval: false,
            environments: null,
            rate_limit: null,
          },
        },
        version_summary: 'Changed tools',
      }),
    )
    expect(endpoints.createPromptVersion).not.toHaveBeenCalled()
  })
})
