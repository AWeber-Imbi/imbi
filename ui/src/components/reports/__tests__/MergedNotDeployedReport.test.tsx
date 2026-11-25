import { MemoryRouter } from 'react-router-dom'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'

import { MergedNotDeployedReport } from '../MergedNotDeployedReport'

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useProjectsSlimMap', () => ({
  useProjectsSlimMap: () => ({ projectsById: new Map() }),
}))

function renderAt(url: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <MergedNotDeployedReport />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

let spy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  vi.restoreAllMocks()
  spy = vi
    .spyOn(endpoints, 'getOrgPendingDeployPullRequests')
    .mockResolvedValue({
      data: [
        {
          additions: 1,
          author: 'gmr',
          deletions: 0,
          last_deployed_at: '2026-09-01T10:00:00Z',
          merged_at: '2026-09-10T12:00:00Z',
          pr_id: 'PR_1',
          pr_number: 42,
          project_id: 'p1',
          title: 'Add the widget',
          url: 'https://github.example/org/repo/pull/42',
        },
      ],
      environments: ['production'],
      since: '2026-06-18T00:00:00Z',
    })
})

describe('MergedNotDeployedReport', () => {
  it('passes author=@me from the URL to the API', async () => {
    renderAt('/reports/merged-not-deployed?author=@me')

    await waitFor(() =>
      expect(screen.getByText('Add the widget')).toBeInTheDocument(),
    )
    expect(spy).toHaveBeenCalledWith(
      'acme',
      { author: '@me' },
      expect.anything(),
    )
    expect(screen.getByRole('button', { name: 'Mine' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('lists every author without the param and toggles to mine', async () => {
    renderAt('/reports/merged-not-deployed')

    await waitFor(() =>
      expect(screen.getByText('Add the widget')).toBeInTheDocument(),
    )
    expect(spy).toHaveBeenCalledWith(
      'acme',
      { author: undefined },
      expect.anything(),
    )
    expect(screen.getByText('gmr')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Mine' }))
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        'acme',
        { author: '@me' },
        expect.anything(),
      ),
    )
  })
})
