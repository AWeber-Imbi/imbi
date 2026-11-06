import { MemoryRouter } from 'react-router-dom'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getOrgPullRequests, type ProjectListItem } from '@/api/endpoints'
import type { PullRequest } from '@/types'

import { OpenPullRequestsReport } from '../OpenPullRequestsReport'

vi.mock('@/api/endpoints', () => ({
  getOrgPullRequests: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useLoginToEmail', () => ({
  useLoginToEmail: () => ({ displayNames: new Map(), loginToEmail: new Map() }),
}))

const PROJECT = {
  archived: false,
  id: 'p1',
  name: 'Demo',
  project_types: [{ name: 'API', slug: 'api' }],
  slug: 'demo',
  team: { name: 'Platform', slug: 'platform' },
} as unknown as ProjectListItem

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useProjectsSlimMap', () => ({
  useProjectsSlimMap: () => ({
    isError: false,
    isFetching: false,
    projectsById: new Map([['p1', PROJECT]]),
    refetch: vi.fn(),
  }),
}))

function makePr(overrides: Partial<PullRequest>): PullRequest {
  return {
    additions: 1,
    author: 'gmr',
    changed_files: 1,
    created_at: '2026-01-01T10:00:00Z',
    deletions: 1,
    draft: false,
    merged: false,
    merged_at: null,
    pr_id: 'PR_1',
    pr_number: 1,
    project_id: 'p1',
    state: 'open',
    title: 'Open PR',
    updated_at: '2026-01-02T10:00:00Z',
    url: 'https://github.example/org/repo/pull/1',
    ...overrides,
  }
}

function renderReport() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <OpenPullRequestsReport />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(getOrgPullRequests).mockResolvedValue({
    data: [
      makePr({
        reviewers: [
          { login: 'alice', state: 'approved' },
          { login: 'bob', state: 'changes_requested' },
          { login: 'carol', state: 'requested' },
          { login: 'web', state: 'requested', team: true },
        ],
      }),
      makePr({ pr_id: 'PR_2', pr_number: 2, title: 'No reviewers' }),
    ],
    project_count: 1,
    total: 2,
  })
})

describe('OpenPullRequestsReport', () => {
  it('shows opened and updated columns', async () => {
    renderReport()
    await screen.findByText('Open PR')
    const headers = screen
      .getAllByRole('columnheader')
      .map((h) => h.textContent)
    expect(headers).toContain('Opened')
    expect(headers).toContain('Updated')
    expect(headers).toContain('Reviewers')
  })

  it('shows each reviewer with their review state', async () => {
    renderReport()
    const row = (await screen.findByText('Open PR')).closest('tr')!
    expect(within(row).getByLabelText('alice: approved')).toBeTruthy()
    expect(within(row).getByLabelText('bob: requested changes')).toBeTruthy()
    expect(within(row).getByLabelText('carol: review requested')).toBeTruthy()
    expect(within(row).getByText('web')).toBeTruthy()
  })

  it('shows a dash when a PR has no reviewers', async () => {
    renderReport()
    const row = (await screen.findByText('No reviewers')).closest('tr')!
    expect(within(row).getByText('—')).toBeTruthy()
  })
})
