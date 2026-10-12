import { Route, Routes } from 'react-router-dom'

import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { fireEvent, render, screen, waitFor } from '@/test/utils'

import { WorkflowsManagement } from '../WorkflowsManagement'
import { STEP_TYPES, workflow } from './fixtures'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  activateWorkflow: vi.fn(),
  createWorkflow: vi.fn(),
  getWorkflow: vi.fn(),
  listTeams: vi.fn(),
  listWorkflows: vi.fn(),
  listWorkflowStepTypes: vi.fn(),
  pauseWorkflow: vi.fn(),
  updateWorkflow: vi.fn(),
  validateWorkflow: vi.fn(),
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
        element={<WorkflowsManagement />}
        path="/agents/:section?/:slug?/:action?"
      />
    </Routes>,
  )
}

describe('WorkflowsManagement', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    auth.user = { is_admin: true, permissions: [] }
    const { version: _version, ...summary } = workflow()
    vi.mocked(endpoints.listWorkflows).mockResolvedValue([
      summary,
      {
        ...summary,
        description: 'Weekly sweep',
        name: 'Dependency sweep',
        slug: 'sweep',
        status: 'active',
      },
    ])
    vi.mocked(endpoints.listWorkflowStepTypes).mockResolvedValue(STEP_TYPES)
    vi.mocked(endpoints.getWorkflow).mockResolvedValue(workflow())
    vi.mocked(endpoints.listTeams).mockResolvedValue([])
    vi.mocked(endpoints.validateWorkflow).mockResolvedValue({ issues: [] })
  })

  it('lists workflows with trigger, status, and empty run columns', async () => {
    renderAt('/agents/workflows')
    const row = (await screen.findByText('Deploy guard')).closest('tr')!
    expect(row).toHaveTextContent('Ships and checks a deploy.')
    await waitFor(() => expect(row).toHaveTextContent('Manual run'))
    expect(row).toHaveTextContent('Draft')
    expect(row).toHaveTextContent('—')
    expect(screen.getByText('Active')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Search workflows'), {
      target: { value: 'weekly' },
    })
    expect(screen.queryByText('Deploy guard')).not.toBeInTheDocument()
    expect(screen.getByText('Dependency sweep')).toBeInTheDocument()
  })

  it('hides New workflow without workflow:create', async () => {
    auth.user = { is_admin: false, permissions: ['workflow:read'] }
    renderAt('/agents/workflows')
    await screen.findByText('Deploy guard')
    expect(screen.queryByText('New workflow')).not.toBeInTheDocument()
  })

  it('adds a step from the palette and saves a new version', async () => {
    vi.mocked(endpoints.updateWorkflow).mockImplementation(
      async (_o, _s, body) =>
        workflow({
          latest_version: 3,
          version: { ...workflow().version, graph: body.graph, version: 3 },
        }),
    )
    renderAt('/agents/workflows/deploy-guard')
    expect(await screen.findByText('Let traffic settle')).toBeInTheDocument()
    expect(screen.getByText('Saved · v2')).toBeInTheDocument()

    // Select the wait step; the palette then adds after its output.
    fireEvent.pointerDown(screen.getByText('Let traffic settle'), { button: 0 })
    fireEvent.click(
      screen.getByRole('button', { name: /^Deploy\s*Ship a release/ }),
    )
    expect(screen.getByText('Unsaved changes')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(endpoints.updateWorkflow).toHaveBeenCalled())
    const body = vi.mocked(endpoints.updateWorkflow).mock.calls[0][2]
    const added = body.graph.nodes.find((n) => n.type === 'deploy')!
    expect(added.key).toBe('deploy')
    expect(body.graph.edges).toContainEqual({
      port: 0,
      source: 'b',
      target: added.id,
    })
    expect(await screen.findByText('Saved · v3')).toBeInTheDocument()
  })

  it('marks steps that need configuration', async () => {
    vi.mocked(endpoints.validateWorkflow).mockResolvedValue({
      issues: [
        {
          code: 'missing_param',
          edge_index: null,
          message: 'duration_seconds is required',
          node_id: 'b',
          severity: 'warning',
        },
      ],
    })
    renderAt('/agents/workflows/deploy-guard')
    expect(
      await screen.findByText(
        '1 step needs configuration',
        {},
        { timeout: 2000 },
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('Needs configuration')).toBeInTheDocument()
  })

  it('deletes the selected step with the Delete key', async () => {
    renderAt('/agents/workflows/deploy-guard')
    fireEvent.pointerDown(await screen.findByText('Let traffic settle'), {
      button: 0,
    })
    fireEvent.keyDown(window, { key: 'Delete' })
    expect(screen.queryByText('Let traffic settle')).not.toBeInTheDocument()
    expect(screen.getByText('Workflow settings')).toBeInTheDocument()
  })
})
