import { Route, Routes } from 'react-router-dom'

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import * as endpoints from '@/api/endpoints'
import { fireEvent, render, screen, waitFor } from '@/test/utils'

import { AgentsArea } from '../AgentsArea'
import { agent, promptVersion } from './fixtures'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createAgent: vi.fn(),
  createPrompt: vi.fn(),
  createPromptVersion: vi.fn(),
  createTag: vi.fn(),
  deleteAgent: vi.fn(),
  deleteUpload: vi.fn(),
  getUploadThumbnailUrl: vi.fn(),
  listAgents: vi.fn(),
  listAgentVersions: vi.fn(),
  listAIModels: vi.fn(),
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
  })

  it('shows an honest empty state and the agent count', async () => {
    renderAt('/agents/dashboard')
    expect(screen.getByText('Coming soon')).toBeInTheDocument()
    expect(screen.getByText(/dashboard is not built yet/)).toBeInTheDocument()
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
    expect(screen.getByText('$400.00')).toBeInTheDocument()
    expect(screen.getByText('30m')).toBeInTheDocument()
    expect(screen.getByText('You fix bugs.')).toBeInTheDocument()
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
      'mender',
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
})
