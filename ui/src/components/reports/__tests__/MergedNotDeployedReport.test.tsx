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
      { author: '@me', limit: 200, offset: 0 },
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
      { author: undefined, limit: 200, offset: 0 },
      expect.anything(),
    )
    expect(screen.getByText('gmr')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Mine' }))
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        'acme',
        { author: '@me', limit: 200, offset: 0 },
        expect.anything(),
      ),
    )
  })

  it('loads the next page and hides the button when all rows load', async () => {
    const row = (i: number) => ({
      additions: 1,
      author: 'gmr',
      deletions: 0,
      last_deployed_at: '2026-09-01T10:00:00Z',
      merged_at: '2026-09-10T12:00:00Z',
      pr_id: `PR_${i}`,
      pr_number: i,
      project_id: 'p1',
      title: `Pull request ${i}`,
      url: `https://github.example/org/repo/pull/${i}`,
    })
    const page = (rows: number[]) => ({
      data: rows.map(row),
      environments: ['production'],
      since: '2026-06-18T00:00:00Z',
      total: 3,
    })
    spy.mockResolvedValueOnce(page([1, 2])).mockResolvedValueOnce(page([3]))
    renderAt('/reports/merged-not-deployed')

    await screen.findByText('Pull request 2')
    expect(spy).toHaveBeenCalledWith(
      'acme',
      { author: undefined, limit: 200, offset: 0 },
      expect.anything(),
    )
    expect(screen.getByText('3')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Load more' }))

    await screen.findByText('Pull request 3')
    expect(spy).toHaveBeenLastCalledWith(
      'acme',
      { author: undefined, limit: 200, offset: 2 },
      expect.anything(),
    )
    expect(screen.getByText('Pull request 1')).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Load more' }),
    ).not.toBeInTheDocument()
  })

  it('keeps loaded rows when the next page fails and retries', async () => {
    const page = (n: number) => ({
      data: [
        {
          additions: 1,
          author: 'gmr',
          deletions: 0,
          last_deployed_at: '2026-09-01T10:00:00Z',
          merged_at: '2026-09-10T12:00:00Z',
          pr_id: `PR_${n}`,
          pr_number: n,
          project_id: 'p1',
          title: `Pull request ${n}`,
          url: `https://github.example/org/repo/pull/${n}`,
        },
      ],
      environments: ['production'],
      since: '2026-06-18T00:00:00Z',
      total: 2,
    })
    spy
      .mockResolvedValueOnce(page(1))
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce(page(2))
    renderAt('/reports/merged-not-deployed')

    await screen.findByText('Pull request 1')
    fireEvent.click(screen.getByRole('button', { name: 'Load more' }))

    await screen.findByText('Could not load more pull requests.')
    expect(screen.getByText('Pull request 1')).toBeInTheDocument()
    expect(screen.queryByText('Unavailable')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
    await screen.findByText('Pull request 2')
    expect(screen.getByText('Pull request 1')).toBeInTheDocument()
    expect(
      screen.queryByText('Could not load more pull requests.'),
    ).not.toBeInTheDocument()
  })
})
