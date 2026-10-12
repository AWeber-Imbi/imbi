import { Route, Routes } from 'react-router-dom'

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import * as endpoints from '@/api/endpoints'
import { fireEvent, render, screen, waitFor } from '@/test/utils'

import { WorkflowsManagement } from '../WorkflowsManagement'
import { node, RUN, STEP_TYPES, workflow } from './fixtures'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  activateWorkflow: vi.fn(),
  cancelWorkflowRun: vi.fn(),
  createWorkflow: vi.fn(),
  getWorkflow: vi.fn(),
  getWorkflowRun: vi.fn(),
  getWorkflowVersion: vi.fn(),
  listTeams: vi.fn(),
  listWorkflowAttention: vi.fn(),
  listWorkflowRuns: vi.fn(),
  listWorkflows: vi.fn(),
  listWorkflowStepTypes: vi.fn(),
  pauseWorkflow: vi.fn(),
  startWorkflowRun: vi.fn(),
  testRunWorkflow: vi.fn(),
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
    vi.mocked(endpoints.listWorkflowAttention).mockResolvedValue([])
    vi.mocked(endpoints.listWorkflowRuns).mockResolvedValue([])
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

  it('shows runs in 30 days, the last outcome, and runs to look at', async () => {
    const { version: _version, ...summary } = workflow()
    vi.mocked(endpoints.listWorkflows).mockResolvedValue([
      {
        ...summary,
        last_run_at: new Date().toISOString(),
        last_run_status: 'failed',
        runs_30d: 12,
      },
    ])
    vi.mocked(endpoints.listWorkflowAttention).mockResolvedValue([
      {
        ...RUN,
        error: 'activator_lacks_permission',
        lease_expires_at: null,
        reason: 'failed',
        status: 'failed',
        worker_id: null,
        workflow_name: 'Deploy guard',
        workflow_slug: 'deploy-guard',
      },
    ])
    renderAt('/agents/workflows')
    const row = (await screen.findByText('Ships and checks a deploy.')).closest(
      'tr',
    )!
    await waitFor(() => expect(row).toHaveTextContent('12'))
    expect(row).toHaveTextContent('Failed')
    expect(
      await screen.findByText('activator_lacks_permission'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('activator_lacks_permission').closest('a'),
    ).toHaveAttribute('href', `/agents/workflows/deploy-guard?run=${RUN.id}`)
  })

  it('test runs the workflow and shows a step output', async () => {
    vi.mocked(endpoints.testRunWorkflow).mockResolvedValue({
      skipped: [],
      steps: [
        {
          key: 'settle',
          node_id: 'b',
          output: { waited: '10m' },
          port: 0,
          port_name: '',
          title: 'Let traffic settle',
          type: 'wait',
        },
      ],
    })
    renderAt('/agents/workflows/deploy-guard')
    fireEvent.click(await screen.findByRole('button', { name: 'Test run' }))
    expect(
      await screen.findByText('Test run finished · 1 steps ran · 0 skipped'),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByText('sample').closest('button')!)
    expect(screen.getByRole('button', { name: 'Output' })).toBeInTheDocument()
    expect(screen.getByText(/"waited": "10m"/)).toBeInTheDocument()
  })

  it('starts a run, shows its steps, and cancels it', async () => {
    vi.mocked(endpoints.getWorkflow).mockResolvedValue(
      workflow({ active_version: 2, status: 'active' }),
    )
    vi.mocked(endpoints.startWorkflowRun).mockResolvedValue(RUN)
    vi.mocked(endpoints.getWorkflowRun).mockResolvedValue({
      ...RUN,
      status: 'running',
      steps: [
        {
          attempt: 1,
          error: null,
          finished_at: null,
          input: { duration: '10m' },
          node_id: 'b',
          node_key: 'settle',
          node_type: 'wait',
          output: null,
          port: null,
          started_at: '2026-10-12T00:00:01Z',
          status: 'running',
          title: 'Let traffic settle',
        },
      ],
    })
    vi.mocked(endpoints.cancelWorkflowRun).mockResolvedValue({
      ...RUN,
      cancel_requested: true,
    })
    renderAt('/agents/workflows/deploy-guard')
    fireEvent.click(await screen.findByRole('button', { name: 'Run' }))
    await waitFor(() =>
      expect(endpoints.startWorkflowRun).toHaveBeenCalledWith(
        'acme',
        'deploy-guard',
        {},
      ),
    )
    expect(await screen.findByText('Running')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel run' }))
    await waitFor(() =>
      expect(endpoints.cancelWorkflowRun).toHaveBeenCalledWith(
        'acme',
        'deploy-guard',
        RUN.id,
      ),
    )
  })

  it('asks for the inputs of the active version, not the latest', async () => {
    const latest = workflow({
      active_version: 1,
      latest_version: 2,
      status: 'active',
    })
    vi.mocked(endpoints.getWorkflow).mockResolvedValue(latest)
    vi.mocked(endpoints.getWorkflowVersion).mockResolvedValue({
      ...latest.version,
      graph: {
        edges: [],
        nodes: [
          node({
            id: 'a',
            key: 'start',
            params: { inputs: [{ name: 'release', type: 'string' }] },
            title: 'Start',
            type: 'manual',
          }),
        ],
      },
      version: 1,
    })
    vi.mocked(endpoints.startWorkflowRun).mockResolvedValue(RUN)
    vi.mocked(endpoints.getWorkflowRun).mockResolvedValue({
      ...RUN,
      steps: [],
    })
    renderAt('/agents/workflows/deploy-guard')
    const run = await screen.findByRole('button', { name: 'Run' })
    await waitFor(() => expect(run).toBeEnabled())
    fireEvent.click(run)
    const start = await screen.findByRole('button', { name: 'Start run' })
    // The input is required: an empty value cannot start the run.
    expect(start).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/release/), {
      target: { value: '1.2.3' },
    })
    fireEvent.click(start)
    await waitFor(() =>
      expect(endpoints.startWorkflowRun).toHaveBeenCalledWith(
        'acme',
        'deploy-guard',
        { release: '1.2.3' },
      ),
    )
    expect(endpoints.getWorkflowVersion).toHaveBeenCalledWith(
      'acme',
      'deploy-guard',
      1,
      expect.anything(),
    )
  })

  it('hides Cancel run after the API refuses it with 403', async () => {
    vi.mocked(endpoints.getWorkflow).mockResolvedValue(
      workflow({ active_version: 2, status: 'active' }),
    )
    vi.mocked(endpoints.startWorkflowRun).mockResolvedValue(RUN)
    vi.mocked(endpoints.getWorkflowRun).mockResolvedValue({
      ...RUN,
      status: 'running',
      steps: [],
    })
    vi.mocked(endpoints.cancelWorkflowRun).mockRejectedValue(
      new ApiError(403, 'Forbidden', {
        detail: 'Only owner team can cancel this workflow',
      }),
    )
    renderAt('/agents/workflows/deploy-guard')
    fireEvent.click(await screen.findByRole('button', { name: 'Run' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel run' }))
    await waitFor(() =>
      expect(
        screen.queryByRole('button', { name: 'Cancel run' }),
      ).not.toBeInTheDocument(),
    )
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
          message: 'duration is required',
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
