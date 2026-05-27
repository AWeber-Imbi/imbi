import { MemoryRouter } from 'react-router-dom'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import type { ArchiveProjectResponse, Project } from '@/types'

import { ProjectSettingsTab } from '../ProjectSettingsTab'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/endpoints')>('@/api/endpoints')
  return {
    ...actual,
    archiveProject: vi.fn(),
    listEnvironments: vi.fn(),
    listLinkDefinitions: vi.fn(),
    listProjectPlugins: vi.fn(),
    unarchiveProject: vi.fn(),
  }
})

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
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
// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ user: { is_admin: false, permissions: [] } }),
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
