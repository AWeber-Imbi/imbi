import React from 'react'

import { MemoryRouter } from 'react-router-dom'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import type { PendingDeployPullRequest } from '@/types'

import { MyPullRequestsToDeployWidget } from '../MyPullRequestsToDeployWidget'

const githubLogin = vi.hoisted(() => ({
  hasIdentity: true,
  isError: false,
  isLoading: false,
  login: 'gmr' as string | undefined,
  notConnected: false,
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useGithubLogin', () => ({
  useGithubLogin: () => githubLogin,
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
    author: 'gmr',
    deletions: 2,
    last_deployed_at: '2026-09-01T10:00:00Z',
    merged_at: '2026-09-10T12:00:00Z',
    pr_id: 'PR_1',
    pr_number: 42,
    project_id: 'p1',
    title: 'Add the widget',
    url: 'https://github.example/org/repo/pull/42',
    ...overrides,
  }
}

function wrapper(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

let qc: QueryClient

beforeEach(() => {
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  githubLogin.hasIdentity = true
  githubLogin.login = 'gmr'
  githubLogin.notConnected = false
  vi.restoreAllMocks()
})

describe('MyPullRequestsToDeployWidget', () => {
  it('requests the pending PRs for the connected GitHub login', async () => {
    const spy = vi
      .spyOn(endpoints, 'getOrgPendingDeployPullRequests')
      .mockResolvedValue({
        data: [makePr()],
        environments: ['production'],
        since: '2026-06-18T00:00:00Z',
      })

    render(<MyPullRequestsToDeployWidget />, { wrapper: wrapper(qc) })

    await waitFor(() =>
      expect(screen.getByText('Add the widget')).toBeInTheDocument(),
    )
    expect(spy).toHaveBeenCalledWith(
      'acme',
      { author: 'gmr' },
      expect.anything(),
    )
    expect(screen.getByText('#42')).toBeInTheDocument()
    expect(screen.getByText('platform/imbi-api')).toBeInTheDocument()
    expect(screen.getByText(/^Waiting \d+ days?$/)).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: /Add the widget/ }),
    ).toHaveAttribute('href', '/projects/p1/deployments')
  })

  it('shows an all-clear message when nothing is pending', async () => {
    vi.spyOn(endpoints, 'getOrgPendingDeployPullRequests').mockResolvedValue({
      data: [],
      environments: ['production'],
      since: '2026-06-18T00:00:00Z',
    })

    render(<MyPullRequestsToDeployWidget />, { wrapper: wrapper(qc) })

    await waitFor(() =>
      expect(
        screen.getByText(
          'Everything you merged has reached a terminal environment.',
        ),
      ).toBeInTheDocument(),
    )
  })

  it('prompts to connect GitHub instead of querying', () => {
    githubLogin.hasIdentity = false
    githubLogin.login = undefined
    githubLogin.notConnected = true
    const spy = vi.spyOn(endpoints, 'getOrgPendingDeployPullRequests')

    render(<MyPullRequestsToDeployWidget />, { wrapper: wrapper(qc) })

    expect(
      screen.getByText('No GitHub identity connected.'),
    ).toBeInTheDocument()
    expect(spy).not.toHaveBeenCalled()
  })
})
