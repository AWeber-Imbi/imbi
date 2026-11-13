import { Route, Routes } from 'react-router-dom'

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import * as endpoints from '@/api/endpoints'
import { fireEvent, render, screen, waitFor, within } from '@/test/utils'

import { agent } from '../../agents/__tests__/fixtures'
import { WorkflowsManagement } from '../WorkflowsManagement'
import { node, RUN, STEP_TYPES, workflow } from './fixtures'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  activateWorkflow: vi.fn(),
  cancelWorkflowRun: vi.fn(),
  createWorkflow: vi.fn(),
  findSideEffectDeployments: vi.fn(),
  getWorkflow: vi.fn(),
  getWorkflowRun: vi.fn(),
  getWorkflowVersion: vi.fn(),
  listAgents: vi.fn(),
  listStaleSideEffects: vi.fn(),
  listTeams: vi.fn(),
  listWorkflowAttention: vi.fn(),
  listWorkflowRuns: vi.fn(),
  listWorkflows: vi.fn(),
  listWorkflowStepTypes: vi.fn(),
  pauseWorkflow: vi.fn(),
  resolveSideEffect: vi.fn(),
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
  user: {
    is_admin: true,
    organizations: [{ organization_slug: 'acme', permissions: [] }],
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
        element={<WorkflowsManagement />}
        path="/agents/:section?/:slug?/:action?"
      />
    </Routes>,
  )
}

describe('WorkflowsManagement', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    auth.user = {
      is_admin: true,
      organizations: [{ organization_slug: 'acme', permissions: [] }],
      permissions: [],
    }
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
    vi.mocked(endpoints.listAgents).mockResolvedValue([])
    vi.mocked(endpoints.listTeams).mockResolvedValue([])
    vi.mocked(endpoints.validateWorkflow).mockResolvedValue({ issues: [] })
    vi.mocked(endpoints.listWorkflowAttention).mockResolvedValue([])
    vi.mocked(endpoints.listWorkflowRuns).mockResolvedValue([])
    vi.mocked(endpoints.listStaleSideEffects).mockResolvedValue([])
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

  it('resolves a call with an unknown outcome and retries the step', async () => {
    const effect = {
      action: 'step-email',
      created_at: new Date(Date.now() - 3_600_000).toISOString(),
      key: '["imbi-workflows", "step-email", "r1:tell"]',
      node_key: 'tell',
      retryable: true,
      run_error: 'outcome_unknown',
      run_id: RUN.id,
      run_status: 'failed' as const,
      step_input: { subject: 'Shipped 1', to: [] },
      workflow_name: 'Deploy guard',
      workflow_slug: 'deploy-guard',
    }
    vi.mocked(endpoints.listStaleSideEffects).mockResolvedValue([effect])
    vi.mocked(endpoints.resolveSideEffect).mockResolvedValue(undefined)
    renderAt('/agents/workflows')
    expect(
      await screen.findByText('Calls with an unknown outcome'),
    ).toBeInTheDocument()
    expect(screen.getByText('Step email')).toBeInTheDocument()
    expect(screen.getByText('subject: Shipped 1')).toBeInTheDocument()
    expect(screen.getByRole('checkbox')).toBeChecked()

    fireEvent.click(screen.getByRole('button', { name: 'Mark done' }))
    expect(
      await screen.findByText(/does not make it again\. The run opens again/),
    ).toBeInTheDocument()
    fireEvent.click(
      within(screen.getByRole('alertdialog')).getByRole('button', {
        name: 'Mark done',
      }),
    )
    await waitFor(() =>
      expect(endpoints.resolveSideEffect).toHaveBeenCalledWith('acme', {
        deployment_run_id: null,
        key: effect.key,
        resolution: 'mark_done',
        retry: true,
      }),
    )
  })

  it('confirms a deployment found in the provider and retries', async () => {
    const effect = {
      action: 'deployment',
      created_at: new Date(Date.now() - 3_600_000).toISOString(),
      key: '["imbi-workflows", "deployment", "r1:ship"]',
      node_key: 'ship',
      retryable: true,
      run_error: 'outcome_unknown',
      run_id: RUN.id,
      run_status: 'failed' as const,
      step_input: { environment: 'staging', project_id: 'p1', version: '1.2' },
      workflow_name: 'Deploy guard',
      workflow_slug: 'deploy-guard',
    }
    vi.mocked(endpoints.listStaleSideEffects).mockResolvedValue([effect])
    vi.mocked(endpoints.findSideEffectDeployments).mockResolvedValue([
      { run_id: '42', status: 'success' },
    ])
    vi.mocked(endpoints.resolveSideEffect).mockResolvedValue(undefined)
    renderAt('/agents/workflows')
    fireEvent.click(
      await screen.findByRole('button', { name: 'Find deployment' }),
    )
    fireEvent.click(
      await screen.findByRole('button', { name: 'Use this deployment' }),
    )
    expect(
      await screen.findByText(/records deployment 42 as the result/),
    ).toBeInTheDocument()
    fireEvent.click(
      within(screen.getByRole('alertdialog')).getByRole('button', {
        name: 'Use deployment',
      }),
    )
    await waitFor(() =>
      expect(endpoints.resolveSideEffect).toHaveBeenCalledWith('acme', {
        deployment_run_id: '42',
        key: effect.key,
        resolution: 'mark_done',
        retry: true,
      }),
    )
    expect(endpoints.findSideEffectDeployments).toHaveBeenCalledWith(
      'acme',
      effect.key,
      expect.anything(),
    )
  })

  it('says when the provider has no deployment of the call', async () => {
    vi.mocked(endpoints.listStaleSideEffects).mockResolvedValue([
      {
        action: 'deployment',
        created_at: new Date(Date.now() - 3_600_000).toISOString(),
        key: '["imbi-workflows", "deployment", "r1:ship"]',
        node_key: 'ship',
        retryable: false,
        run_error: 'outcome_unknown',
        run_id: RUN.id,
        run_status: 'failed' as const,
        step_input: null,
        workflow_name: 'Deploy guard',
        workflow_slug: 'deploy-guard',
      },
    ])
    vi.mocked(endpoints.findSideEffectDeployments).mockResolvedValue([])
    renderAt('/agents/workflows')
    fireEvent.click(
      await screen.findByRole('button', { name: 'Find deployment' }),
    )
    expect(
      await screen.findByText(/has no deployment of this version/),
    ).toBeInTheDocument()
  })

  it('hides calls with an unknown outcome without workflow:recover', async () => {
    auth.user = {
      is_admin: false,
      organizations: [
        { organization_slug: 'acme', permissions: ['workflow:read'] },
      ],
      permissions: [],
    }
    renderAt('/agents/workflows')
    expect(await screen.findByText('Deploy guard')).toBeInTheDocument()
    expect(endpoints.listStaleSideEffects).not.toHaveBeenCalled()
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

  it('shows a skipped run as a duplicate and links to the first', async () => {
    const first = { ...RUN, id: '9d8e7f6a-0000-4000-8000-000000000002' }
    const skipped = {
      ...RUN,
      closed_at: RUN.created_at,
      dedupe_key: 'octo/imbi:abc123',
      duplicate_of: first.id,
      origin_id: 'hook',
      origin_kind: 'webhook',
      status: 'skipped' as const,
    }
    vi.mocked(endpoints.listWorkflowRuns).mockResolvedValue([skipped, first])
    vi.mocked(endpoints.getWorkflowRun).mockImplementation(
      async (_o, _s, id) => ({
        ...(id === first.id ? first : skipped),
        steps: [],
      }),
    )
    renderAt(`/agents/workflows/deploy-guard?run=${skipped.id}`)
    const note = await screen.findByText(/^Skipped: duplicate of/)
    expect(note).toHaveTextContent('octo/imbi:abc123')
    expect(screen.queryByText('This run has no steps.')).not.toBeInTheDocument()
    fireEvent.click(within(note).getByRole('button', { name: 'run 9d8e7f6a' }))
    await waitFor(() =>
      expect(
        vi.mocked(endpoints.getWorkflowRun).mock.calls.map((c) => c[2]),
      ).toContain(first.id),
    )
    expect(
      await screen.findByText(`Run ${first.id.slice(0, 8)} · v2 · Queued`),
    ).toBeInTheDocument()
  })

  it('saves a dedupe key and window from the settings', async () => {
    vi.mocked(endpoints.updateWorkflow).mockResolvedValue(workflow())
    renderAt('/agents/workflows/deploy-guard')
    const key = await screen.findByLabelText('Dedupe key')
    expect(screen.queryByLabelText('Dedupe window (days)')).toBeNull()
    fireEvent.change(key, {
      target: { value: '{{ trigger.payload.repository.full_name }}' },
    })
    fireEvent.change(screen.getByLabelText('Dedupe window (days)'), {
      target: { value: '14' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(endpoints.updateWorkflow).toHaveBeenCalled())
    const body = vi.mocked(endpoints.updateWorkflow).mock.calls[0][2]
    expect(body.settings).toMatchObject({
      dedupe_key: '{{ trigger.payload.repository.full_name }}',
      dedupe_window_seconds: 1_209_600,
    })
  })

  it('keeps a partial dedupe window while it is typed', async () => {
    vi.mocked(endpoints.updateWorkflow).mockResolvedValue(workflow())
    renderAt('/agents/workflows/deploy-guard')
    fireEvent.change(await screen.findByLabelText('Dedupe key'), {
      target: { value: '{{ trigger.service }}' },
    })
    const field = screen.getByLabelText('Dedupe window (days)')
    fireEvent.change(field, { target: { value: '0' } })
    expect(field).toHaveValue(0)
    fireEvent.change(field, { target: { value: '0.5' } })
    expect(field).toHaveValue(0.5)
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(endpoints.updateWorkflow).toHaveBeenCalled())
    const body = vi.mocked(endpoints.updateWorkflow).mock.calls[0][2]
    expect(body.settings).toMatchObject({ dedupe_window_seconds: 43_200 })
  })

  it('resets an invalid dedupe window to the saved value on blur', async () => {
    vi.mocked(endpoints.updateWorkflow).mockResolvedValue(workflow())
    renderAt('/agents/workflows/deploy-guard')
    fireEvent.change(await screen.findByLabelText('Dedupe key'), {
      target: { value: '{{ trigger.service }}' },
    })
    const field = screen.getByLabelText('Dedupe window (days)')
    fireEvent.change(field, { target: { value: '14' } })
    fireEvent.change(field, { target: { value: '-1' } })
    expect(field).toHaveValue(-1)
    fireEvent.blur(field)
    expect(field).toHaveValue(14)
  })

  it('keeps the saved dedupe window for unparsable input', async () => {
    vi.mocked(endpoints.updateWorkflow).mockResolvedValue(workflow())
    renderAt('/agents/workflows/deploy-guard')
    fireEvent.change(await screen.findByLabelText('Dedupe key'), {
      target: { value: '{{ trigger.service }}' },
    })
    const field = screen.getByLabelText('Dedupe window (days)')
    fireEvent.change(field, { target: { value: '14' } })
    // A browser reports text such as `14e` as an empty value with
    // validity.badInput set; jsdom does not, so stub it.
    Object.defineProperty(field, 'validity', {
      configurable: true,
      value: { badInput: true },
    })
    fireEvent.change(field, { target: { value: '' } })
    fireEvent.blur(field)
    expect(field).toHaveValue(14)
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(endpoints.updateWorkflow).toHaveBeenCalled())
    const body = vi.mocked(endpoints.updateWorkflow).mock.calls[0][2]
    expect(body.settings).toMatchObject({ dedupe_window_seconds: 1_209_600 })
  })

  it('shows a dedupe validation error in the settings', async () => {
    vi.mocked(endpoints.validateWorkflow).mockResolvedValue({
      issues: [
        {
          code: 'dedupe_window_without_key',
          edge_index: null,
          message: 'A dedupe window needs a dedupe key',
          node_id: null,
          severity: 'error',
        },
      ],
    })
    renderAt('/agents/workflows/deploy-guard')
    fireEvent.change(await screen.findByLabelText('Dedupe key'), {
      target: { value: '{{ trigger.sha }}' },
    })
    expect(
      await screen.findByText('A dedupe window needs a dedupe key'),
    ).toBeInTheDocument()
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
    auth.user = {
      is_admin: false,
      organizations: [
        { organization_slug: 'acme', permissions: ['workflow:read'] },
      ],
      permissions: ['workflow:read'],
    }
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

  it('shows each step key, and the type when the title differs', async () => {
    renderAt('/agents/workflows/deploy-guard')
    expect(await screen.findByText('settle')).toBeInTheDocument()
    expect(screen.getByText('settle').parentElement).toHaveTextContent(
      'settle · Wait',
    )
    expect(screen.getByText('start').parentElement).toHaveTextContent(
      'start · Manual run',
    )
  })

  it('shows the agent that an agent step runs', async () => {
    vi.mocked(endpoints.listAgents).mockResolvedValue([agent()])
    const base = workflow()
    vi.mocked(endpoints.getWorkflow).mockResolvedValue({
      ...base,
      version: {
        ...base.version,
        graph: {
          edges: [],
          nodes: [
            node({
              id: 'c',
              key: 'triage',
              params: { agent_id: 'agt-1', instruction: 'Triage the issue' },
              title: 'Agent task',
              type: 'agent',
            }),
            node({
              id: 'd',
              key: 'follow_up',
              params: { agent_id: 'gone', instruction: 'Follow up' },
              position: { x: 320, y: 0 },
              title: 'Agent task',
              type: 'agent',
            }),
          ],
        },
      },
    })
    renderAt('/agents/workflows/deploy-guard')
    expect(await screen.findByText('Mender')).toBeInTheDocument()
    expect(screen.getAllByText('Mender')).toHaveLength(1)
    expect(screen.getByText('triage').parentElement).toHaveTextContent(
      /^triage$/,
    )
    expect(screen.getByText('Triage the issue')).toBeInTheDocument()
    expect(screen.getByText('Follow up')).toBeInTheDocument()
    expect(screen.getByText('Agent')).toBeInTheDocument()
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

  it('removes drag listeners when the canvas unmounts mid-drag', async () => {
    const { unmount } = renderAt('/agents/workflows/deploy-guard')
    await screen.findByText('Let traffic settle')
    // Start a connection drag from the first output port.
    fireEvent.pointerDown(screen.getAllByTitle('Drag to connect')[0], {
      button: 0,
    })
    const remove = vi.spyOn(window, 'removeEventListener')
    unmount()
    expect(remove).toHaveBeenCalledWith('pointermove', expect.any(Function))
    expect(remove).toHaveBeenCalledWith('pointerup', expect.any(Function))
    remove.mockRestore()
  })
})
