import { MemoryRouter } from 'react-router-dom'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import type {
  ArchiveProjectResponse,
  PluginAssignmentResponse,
  Project,
} from '@/types'

import { ProjectSettingsTab } from '../ProjectSettingsTab'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/endpoints')>('@/api/endpoints')
  return {
    ...actual,
    archiveProject: vi.fn(),
    deleteProject: vi.fn(),
    listEnvironments: vi.fn(),
    listLinkDefinitions: vi.fn(),
    listProjectPlugins: vi.fn(),
    unarchiveProject: vi.fn(),
  }
})

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn() },
}))

// Isolate the archive card: the surrounding editor cards do their own
// data fetching and are irrelevant to the lifecycle-result behaviour.
// fallow-ignore-next-line unresolved-import
vi.mock('@/components/EditLinksCard', () => ({ EditLinksCard: () => null }))
// fallow-ignore-next-line unresolved-import
vi.mock('@/components/EditEnvironmentsCard', () => ({
  EditEnvironmentsCard: () => null,
}))
// fallow-ignore-next-line unresolved-import
vi.mock('@/components/EditIdentifiersCard', () => ({
  EditIdentifiersCard: () => null,
}))
// fallow-ignore-next-line unresolved-import
vi.mock('@/components/project/ProjectPluginsSection', () => ({
  ProjectPluginsSection: () => null,
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))
// Mutable so individual tests can vary admin status / permissions.
let mockAuthUser: { is_admin: boolean; permissions: string[] } = {
  is_admin: false,
  permissions: [],
}
// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ user: mockAuthUser }),
}))
// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useProjectPatch', () => ({
  useProjectPatch: () => ({ patch: vi.fn(), scheduleScoreRefresh: vi.fn() }),
}))
// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useDeploymentResync', () => ({
  useProjectDeploymentResync: () => ({ isPending: false, mutate: vi.fn() }),
}))

const ARCHIVED_PROJECT = {
  archived: true,
  id: 'p1',
  name: 'Demo',
  slug: 'demo',
  team: { name: 'Team', organization: { name: 'Acme', slug: 'acme' } },
} as Project

const DEPLOYMENT_PLUGIN = {
  default: true,
  label: 'Deploy',
  options: {},
  plugin_id: 'dep-1',
  plugin_slug: 'github-deploy',
  plugin_type: 'deployment',
  source: 'project',
  supports_deployment_sync: true,
} as PluginAssignmentResponse

function renderTab() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ProjectSettingsTab project={ARCHIVED_PROJECT} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ProjectSettingsTab archive lifecycle results', () => {
  let toast: {
    error: ReturnType<typeof vi.fn>
    success: ReturnType<typeof vi.fn>
  }

  beforeEach(async () => {
    vi.clearAllMocks()
    mockAuthUser = { is_admin: false, permissions: [] }
    vi.mocked(endpoints.listEnvironments).mockResolvedValue([])
    vi.mocked(endpoints.listLinkDefinitions).mockResolvedValue([])
    vi.mocked(endpoints.listProjectPlugins).mockResolvedValue([])
    toast = (await import('sonner')).toast as unknown as typeof toast
  })

  it('surfaces a failed lifecycle result as an error toast', async () => {
    vi.mocked(endpoints.unarchiveProject).mockResolvedValue({
      ...ARCHIVED_PROJECT,
      lifecycle_results: [
        {
          artifacts: {},
          message: "404 Not Found for '/repos/archives/demo'",
          plugin_id: 'pi-1',
          plugin_slug: 'github-lifecycle-ec',
          status: 'failed',
        },
      ],
    } as ArchiveProjectResponse)

    const { getByRole } = renderTab()
    fireEvent.click(getByRole('button', { name: 'Restore project' }))

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledTimes(1)
    })
    expect(toast.error.mock.calls[0][0]).toContain('1 integration failed')
    expect(toast.success).not.toHaveBeenCalled()
  })

  it('shows a plain success toast when no lifecycle plugin fails', async () => {
    vi.mocked(endpoints.unarchiveProject).mockResolvedValue({
      ...ARCHIVED_PROJECT,
      lifecycle_results: [
        {
          artifacts: {},
          message: 'Unarchived archives/demo',
          plugin_id: 'pi-1',
          plugin_slug: 'github-lifecycle-ec',
          status: 'ok',
        },
      ],
    } as ArchiveProjectResponse)

    const { getByRole } = renderTab()
    fireEvent.click(getByRole('button', { name: 'Restore project' }))

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith('Project restored')
    })
    expect(toast.error).not.toHaveBeenCalled()
  })
})

describe('ProjectSettingsTab delete flow', () => {
  let toast: {
    error: ReturnType<typeof vi.fn>
    success: ReturnType<typeof vi.fn>
    warning: ReturnType<typeof vi.fn>
  }

  const LIFECYCLE_PLUGIN = {
    default: true,
    label: 'GitHub',
    options: {},
    plugin_id: 'lc-1',
    plugin_slug: 'github-lifecycle',
    plugin_type: 'lifecycle',
    source: 'project',
  } as PluginAssignmentResponse

  beforeEach(async () => {
    vi.clearAllMocks()
    mockAuthUser = { is_admin: false, permissions: [] }
    vi.mocked(endpoints.listEnvironments).mockResolvedValue([])
    vi.mocked(endpoints.listLinkDefinitions).mockResolvedValue([])
    vi.mocked(endpoints.listProjectPlugins).mockResolvedValue([])
    toast = (await import('sonner')).toast as unknown as typeof toast
  })

  it('omits the "Also delete repository" checkbox without a lifecycle plugin', async () => {
    // No lifecycle plugins → checkbox is suppressed because there is
    // no remote for the operator to keep behind.
    const { findByRole, queryByLabelText } = renderTab()
    fireEvent.click(await findByRole('button', { name: 'Delete Project' }))
    expect(queryByLabelText(/Also delete the associated repository/)).toBeNull()
  })

  it('passes deleteRepository=true by default when checkbox is present', async () => {
    vi.mocked(endpoints.listProjectPlugins).mockResolvedValue([
      LIFECYCLE_PLUGIN,
    ])
    vi.mocked(endpoints.deleteProject).mockResolvedValue({
      lifecycle_results: [],
    })

    const { findByPlaceholderText, findByRole } = renderTab()
    fireEvent.click(await findByRole('button', { name: 'Delete Project' }))
    fireEvent.change(await findByPlaceholderText('demo'), {
      target: { value: 'demo' },
    })
    fireEvent.click(await findByRole('button', { name: 'Confirm Delete' }))

    await waitFor(() => {
      expect(endpoints.deleteProject).toHaveBeenCalledWith('acme', 'p1', {
        deleteRepository: true,
      })
    })
  })

  it('sends deleteRepository=false when the operator unchecks the box', async () => {
    vi.mocked(endpoints.listProjectPlugins).mockResolvedValue([
      LIFECYCLE_PLUGIN,
    ])
    vi.mocked(endpoints.deleteProject).mockResolvedValue({
      lifecycle_results: [],
    })

    const { findAllByRole, findByPlaceholderText, findByRole } = renderTab()
    fireEvent.click(await findByRole('button', { name: 'Delete Project' }))
    // The Radix Checkbox renders as a button with role="checkbox".
    const checkboxes = await findAllByRole('checkbox')
    fireEvent.click(checkboxes[0])
    fireEvent.change(await findByPlaceholderText('demo'), {
      target: { value: 'demo' },
    })
    fireEvent.click(await findByRole('button', { name: 'Confirm Delete' }))

    await waitFor(() => {
      expect(endpoints.deleteProject).toHaveBeenCalledWith('acme', 'p1', {
        deleteRepository: false,
      })
    })
  })

  it('surfaces a failed lifecycle delete result as a warning toast', async () => {
    vi.mocked(endpoints.listProjectPlugins).mockResolvedValue([
      LIFECYCLE_PLUGIN,
    ])
    vi.mocked(endpoints.deleteProject).mockResolvedValue({
      lifecycle_results: [
        {
          artifacts: {},
          message: '401 from GitHub',
          plugin_id: 'lc-1',
          plugin_slug: 'github-lifecycle',
          status: 'failed',
        },
      ],
    })

    const { findByPlaceholderText, findByRole } = renderTab()
    fireEvent.click(await findByRole('button', { name: 'Delete Project' }))
    fireEvent.change(await findByPlaceholderText('demo'), {
      target: { value: 'demo' },
    })
    fireEvent.click(await findByRole('button', { name: 'Confirm Delete' }))

    await waitFor(() => {
      expect(toast.warning).toHaveBeenCalledTimes(1)
    })
    expect(toast.warning.mock.calls[0][0]).toContain('1 integration failed')
  })
})

describe('ProjectSettingsTab utility functions gating', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockAuthUser = { is_admin: false, permissions: [] }
    vi.mocked(endpoints.listEnvironments).mockResolvedValue([])
    vi.mocked(endpoints.listLinkDefinitions).mockResolvedValue([])
    vi.mocked(endpoints.listProjectPlugins).mockResolvedValue([])
  })

  it('hides the card when the user has neither permission', async () => {
    vi.mocked(endpoints.listProjectPlugins).mockResolvedValue([
      DEPLOYMENT_PLUGIN,
    ])
    const { queryByText } = renderTab()
    await waitFor(() => expect(endpoints.listProjectPlugins).toHaveBeenCalled())
    expect(queryByText('Utility Functions')).not.toBeInTheDocument()
  })

  it('shows the card with only Recompute Score for rescore permission', async () => {
    mockAuthUser = { is_admin: false, permissions: ['scoring_policy:rescore'] }
    const { queryByRole, queryByText } = renderTab()
    await waitFor(() =>
      expect(queryByText('Utility Functions')).toBeInTheDocument(),
    )
    expect(
      queryByRole('button', { name: 'Recompute Score' }),
    ).toBeInTheDocument()
    expect(
      queryByRole('button', { name: 'Sync Deployments' }),
    ).not.toBeInTheDocument()
  })

  it('shows Sync Deployments for project:deployment:write without admin', async () => {
    mockAuthUser = {
      is_admin: false,
      permissions: ['project:deployment:write'],
    }
    vi.mocked(endpoints.listProjectPlugins).mockResolvedValue([
      DEPLOYMENT_PLUGIN,
    ])
    const { queryByRole, queryByText } = renderTab()
    await waitFor(() =>
      expect(queryByText('Utility Functions')).toBeInTheDocument(),
    )
    expect(
      queryByRole('button', { name: 'Sync Deployments' }),
    ).toBeInTheDocument()
    expect(
      queryByRole('button', { name: 'Recompute Score' }),
    ).not.toBeInTheDocument()
  })
})
