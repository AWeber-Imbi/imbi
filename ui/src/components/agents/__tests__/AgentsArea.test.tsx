import { Route, Routes } from 'react-router-dom'

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import * as endpoints from '@/api/endpoints'
import { fireEvent, render, screen, waitFor } from '@/test/utils'

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
  getAgentToolCatalog: vi.fn(),
  getAgentUsage: vi.fn(),
  getUploadThumbnailUrl: vi.fn(),
  listAgents: vi.fn(),
  listAgentVersions: vi.fn(),
  listAIModels: vi.fn(),
  listEnvironments: vi.fn(),
  listTags: vi.fn(),
  listTeams: vi.fn(),
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
  user: { is_admin: true, permissions: [] as string[] },
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
    auth.user = { is_admin: true, permissions: [] }
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

  it('shows an honest empty state and the agent count', async () => {
    renderAt('/agents/workflows')
    expect(screen.getByText('Coming soon')).toBeInTheDocument()
    expect(screen.getByText(/Workflows are not built yet/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('2')).toBeInTheDocument())
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
    auth.user = { is_admin: false, permissions: ['agent:read'] }
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
    expect(screen.getByText('You fix bugs.')).toBeInTheDocument()
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

  it('shows totals, the agent table, and cap warnings on Usage', async () => {
    renderAt('/agents/usage')
    expect(await screen.findByText('Usage by agent')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(
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

  it('says on Usage only how many reports had no price', async () => {
    vi.mocked(endpoints.getAgentUsage).mockResolvedValue(
      usage({ unpriced_reports: 2 }),
    )
    renderAt('/agents/usage')
    expect(
      await screen.findByText('2 usage reports had no price and count as $0.'),
    ).toBeInTheDocument()
  })

  it('hides the unpriced line when every report had a price', async () => {
    renderAt('/agents/usage')
    await screen.findByText('Usage by agent')
    expect(screen.queryByText(/had no price/)).not.toBeInTheDocument()
  })

  it('says so when the user may not read agent tasks', () => {
    auth.user = { is_admin: false, permissions: ['agent:read'] }
    renderAt('/agents/usage')
    expect(screen.getByText(/agent_task:read/)).toBeInTheDocument()
    expect(endpoints.getAgentUsage).not.toHaveBeenCalled()
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

  it('shows the enabled tools by server on the detail page', async () => {
    vi.mocked(endpoints.listAgents).mockResolvedValue([
      agent({
        tools: {
          'github.read_file': { approval: false },
          'imbi.delete_project': { approval: true },
          'imbi.list_projects': { approval: false },
        },
      }),
    ])
    renderAt('/agents/manage/mender')
    expect(await screen.findByText('3 of 4 enabled')).toBeInTheDocument()
    expect(screen.getByText('Tools and MCP access')).toBeInTheDocument()
    expect(
      screen.getByText('delete_project, list_projects'),
    ).toBeInTheDocument()
    expect(screen.getByText('GitHub')).toBeInTheDocument()
    expect(screen.getByText('read_file')).toBeInTheDocument()
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

  it('saves a tool change from the Tools and MCPs tab', async () => {
    vi.mocked(endpoints.updateAgent).mockResolvedValue(agent())
    renderAt('/agents/manage/mender/edit')
    await screen.findByText('Edit Mender')
    const tab = screen.getByRole('tab', { name: /Tools and MCPs/ })
    expect(tab).toHaveTextContent('Tools and MCPs0')
    fireEvent.click(tab)
    await screen.findByText('0 of 4 enabled')
    fireEvent.click(screen.getByRole('button', { name: /GitHub/ }))
    fireEvent.click(
      screen.getByRole('switch', { name: 'Enable github.read_file' }),
    )
    expect(tab).toHaveTextContent('Tools and MCPs1')
    fireEvent.click(screen.getByRole('button', { name: /Save Changes/ }))
    await waitFor(() => expect(endpoints.updateAgent).toHaveBeenCalled())
    expect(vi.mocked(endpoints.updateAgent).mock.calls[0][2]).toEqual(
      expect.objectContaining({
        tools: {
          'github.read_file': {
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
