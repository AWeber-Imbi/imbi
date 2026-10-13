import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { render, screen } from '@/test/utils'
import type { HarnessPool } from '@/types'

import { RunnersPage } from '../RunnersPage'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({ listHarnessPools: vi.fn() }))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

const auth = vi.hoisted(() => ({
  user: { is_admin: false, permissions: ['harness_pool:read'] },
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => auth }))

const NOW = new Date().toISOString()

function pool(): HarnessPool {
  return {
    created_at: NOW,
    description: null,
    labels: ['general'],
    name: 'general',
    organizations: [],
    runners: [
      {
        chain: {
          attempt: 2,
          fence_error: 'fencers failed: release',
          organization_slug: 'acme',
          root_task_id: 'c-1',
          short_id: 'T-7',
          state: 'stuck',
        },
        id: 'r-1',
        image_version: '1.2.0',
        instance: 'general-abc',
        labels: ['general'],
        last_heartbeat: NOW,
        lease_expires_at: NOW,
        registered_at: NOW,
        state: 'fenced',
      },
      {
        chain: null,
        id: 'r-2',
        image_version: null,
        instance: 'general-def',
        labels: ['general'],
        last_heartbeat: NOW,
        lease_expires_at: NOW,
        registered_at: NOW,
        state: 'busy',
      },
    ],
    service_account: 'pool-general',
    updated_at: NOW,
  }
}

describe('RunnersPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    auth.user = { is_admin: false, permissions: ['harness_pool:read'] }
  })

  it('lists the pools and runners of the organization', async () => {
    vi.mocked(endpoints.listHarnessPools).mockResolvedValue([pool()])
    render(<RunnersPage />)
    expect(await screen.findByText('general-abc')).toBeInTheDocument()
    expect(endpoints.listHarnessPools).toHaveBeenCalledWith(
      'acme',
      expect.anything(),
    )
    expect(screen.getByText('all organizations', { exact: false }))
    expect(screen.getByRole('link', { name: 'T-7' })).toHaveAttribute(
      'href',
      '/agents/tasks/acme/T-7',
    )
    expect(screen.getByText('stuck')).toBeInTheDocument()
    expect(screen.getByText('attempt 2')).toBeInTheDocument()
    // A busy runner with a chain of another organization.
    expect(screen.getByText('Another organization')).toBeInTheDocument()
  })

  it('keeps the last data when a refresh fails', async () => {
    vi.mocked(endpoints.listHarnessPools)
      .mockResolvedValueOnce([pool()])
      .mockRejectedValue(new Error('down'))
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <RunnersPage />
      </QueryClientProvider>,
    )
    expect(await screen.findByText('general-abc')).toBeInTheDocument()
    await queryClient.refetchQueries()
    expect(
      await screen.findByText(/Failed to refresh runners/),
    ).toBeInTheDocument()
    expect(screen.getByText('general-abc')).toBeInTheDocument()
  })

  it('needs the read permission', () => {
    auth.user = { is_admin: false, permissions: [] }
    render(<RunnersPage />)
    expect(screen.getByText(/harness_pool:read/)).toBeInTheDocument()
    expect(endpoints.listHarnessPools).not.toHaveBeenCalled()
  })
})
