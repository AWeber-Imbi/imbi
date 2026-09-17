import React from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import type { PendingDeployPullRequest } from '@/types'

import { AgentPullRequestsToDeployWidget } from '../AgentPullRequestsToDeployWidget'

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useProjectsSlimMap', () => ({
  useProjectsSlimMap: () => ({
    projectsById: new Map([
      ['p1', { id: 'p1', slug: 'imbi-api', team: { slug: 'platform' } }],
    ]),
  }),
}))

function makePr(
  overrides: Partial<PendingDeployPullRequest> = {},
): PendingDeployPullRequest {
  return {
    additions: 10,
    author: 'dependabot[bot]',
    deletions: 2,
    last_deployed_at: '2026-09-01T10:00:00Z',
    merged_at: '2026-09-10T12:00:00Z',
    pr_id: 'PR_1',
    pr_number: 42,
    project_id: 'p1',
    title: 'Bump lodash',
    url: 'https://github.example/org/repo/pull/42',
    ...overrides,
  }
}

function wrapper(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

let qc: QueryClient

beforeEach(() => {
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.restoreAllMocks()
})

describe('AgentPullRequestsToDeployWidget', () => {
  it('requests bot-authored PRs org-wide and shows the author', async () => {
    const spy = vi
      .spyOn(endpoints, 'getOrgPendingDeployPullRequests')
      .mockResolvedValue({
        data: [makePr()],
        environments: ['production'],
        since: '2026-06-18T00:00:00Z',
      })

    render(<AgentPullRequestsToDeployWidget />, { wrapper: wrapper(qc) })

    await waitFor(() =>
      expect(screen.getByText('Bump lodash')).toBeInTheDocument(),
    )
    expect(spy).toHaveBeenCalledWith('acme', { bots: true }, expect.anything())
    expect(screen.getByText('dependabot[bot]')).toBeInTheDocument()
    expect(screen.getByText('platform/imbi-api')).toBeInTheDocument()
  })

  it('shows an all-clear message when nothing is pending', async () => {
    vi.spyOn(endpoints, 'getOrgPendingDeployPullRequests').mockResolvedValue({
      data: [],
      environments: ['production'],
      since: '2026-06-18T00:00:00Z',
    })

    render(<AgentPullRequestsToDeployWidget />, { wrapper: wrapper(qc) })

    await waitFor(() =>
      expect(
        screen.getByText('Every agent PR has reached a terminal environment.'),
      ).toBeInTheDocument(),
    )
  })
})
