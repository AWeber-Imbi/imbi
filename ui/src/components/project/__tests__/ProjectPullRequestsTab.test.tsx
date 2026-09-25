import React from 'react'

import { MemoryRouter, useLocation } from 'react-router-dom'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getProjectPullRequests } from '@/api/endpoints'
import type { PullRequest } from '@/types'

import { ProjectPullRequestsTab } from '../ProjectPullRequestsTab'

vi.mock('@/api/endpoints', () => ({
  getProjectPullRequests: vi.fn(),
}))

const githubLogin = vi.hoisted(() => ({
  isLoading: false,
  login: 'gmr' as string | undefined,
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useGithubLogin', () => ({
  useGithubLogin: () => githubLogin,
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useLoginToEmail', () => ({
  useLoginToEmail: () => ({ displayNames: new Map(), loginToEmail: new Map() }),
}))

function makePr(overrides: Partial<PullRequest>): PullRequest {
  return {
    additions: 1,
    author: 'gmr',
    changed_files: 1,
    deletions: 1,
    draft: false,
    merged: false,
    pr_id: 'PR_1',
    pr_number: 1,
    state: 'open',
    title: 'Open PR',
    updated_at: '2026-09-01T10:00:00Z',
    url: 'https://github.example/org/repo/pull/1',
    ...overrides,
  } as PullRequest
}

const OPEN = makePr({})
const OTHERS_OPEN = makePr({
  author: 'someone-else',
  pr_id: 'PR_3',
  pr_number: 3,
  title: 'Their open PR',
})
const MERGED = makePr({
  merged: true,
  pr_id: 'PR_2',
  pr_number: 2,
  state: 'closed',
  title: 'Merged PR',
})

function LocationProbe() {
  const { search } = useLocation()
  return <div data-testid="search">{search}</div>
}

function renderAt(url: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <ProjectPullRequestsTab orgSlug="acme" projectId="p1" />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  githubLogin.login = 'gmr'
  vi.mocked(getProjectPullRequests).mockImplementation(
    async (_org, _project, params) =>
      ({
        data: params?.state === 'open' ? [OPEN, OTHERS_OPEN] : [MERGED],
      }) as Awaited<ReturnType<typeof getProjectPullRequests>>,
  )
})

describe('ProjectPullRequestsTab', () => {
  it('defaults to showing every state', async () => {
    renderAt('/projects/p1/pull-requests')
    expect(await screen.findByText('Open PR')).toBeInTheDocument()
    expect(await screen.findByText('Merged PR')).toBeInTheDocument()
  })

  it('honours a ?state= deep link', async () => {
    renderAt('/projects/p1/pull-requests?state=open')
    expect(await screen.findByText('Open PR')).toBeInTheDocument()
    expect(screen.queryByText('Merged PR')).not.toBeInTheDocument()
  })

  it('falls back to all for an unknown ?state=', async () => {
    renderAt('/projects/p1/pull-requests?state=bogus')
    expect(await screen.findByText('Merged PR')).toBeInTheDocument()
  })

  it('writes the selected filter to the URL', async () => {
    const user = userEvent.setup()
    renderAt('/projects/p1/pull-requests')
    await screen.findByText('Merged PR')

    await user.click(screen.getByRole('button', { name: /^Merged/ }))
    expect(screen.getByTestId('search')).toHaveTextContent('?state=merged')
    expect(screen.queryByText('Open PR')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /^All/ }))
    expect(screen.getByTestId('search')).toBeEmptyDOMElement()
  })

  it('narrows to the viewer and rescopes counts with ?author=me', async () => {
    renderAt('/projects/p1/pull-requests?state=open&author=me')
    expect(await screen.findByText('Open PR')).toBeInTheDocument()
    expect(screen.queryByText('Their open PR')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open 1' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Mine/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('filters by author server-side under ?author=me', async () => {
    renderAt('/projects/p1/pull-requests?author=me')
    await screen.findByText('Open PR')
    for (const state of ['open', 'closed'] as const) {
      expect(getProjectPullRequests).toHaveBeenCalledWith(
        'acme',
        'p1',
        { author: 'gmr', limit: 100, state },
        expect.anything(),
      )
    }
  })

  it('omits the author filter without ?author=me', async () => {
    renderAt('/projects/p1/pull-requests')
    await screen.findByText('Open PR')
    expect(getProjectPullRequests).toHaveBeenCalledWith(
      'acme',
      'p1',
      { author: undefined, limit: 100, state: 'open' },
      expect.anything(),
    )
  })

  it('toggles Mine in the URL', async () => {
    const user = userEvent.setup()
    renderAt('/projects/p1/pull-requests?state=open')
    expect(await screen.findByText('Their open PR')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open 2' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Mine/ }))
    expect(screen.getByTestId('search')).toHaveTextContent(
      '?state=open&author=me',
    )
    expect(screen.queryByText('Their open PR')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Mine/ }))
    expect(screen.getByTestId('search')).toHaveTextContent('?state=open')
    expect(screen.getByText('Their open PR')).toBeInTheDocument()
  })

  it('ignores ?author=me without a linked GitHub identity', async () => {
    githubLogin.login = undefined
    renderAt('/projects/p1/pull-requests?state=open&author=me')
    expect(await screen.findByText('Their open PR')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Mine/ })).toBeNull()
  })

  it('labels the text filter for assistive tech', async () => {
    const user = userEvent.setup()
    renderAt('/projects/p1/pull-requests')
    await screen.findByText('Merged PR')

    await user.type(
      screen.getByRole('textbox', { name: 'Filter pull requests' }),
      'merged',
    )
    expect(screen.queryByText('Open PR')).not.toBeInTheDocument()
    expect(screen.getByText('Merged PR')).toBeInTheDocument()
  })

  it('honours a ?q= deep link', async () => {
    renderAt('/projects/p1/pull-requests?q=merged')
    expect(await screen.findByText('Merged PR')).toBeInTheDocument()
    expect(screen.queryByText('Open PR')).not.toBeInTheDocument()
    expect(
      screen.getByRole('textbox', { name: 'Filter pull requests' }),
    ).toHaveValue('merged')
  })

  it('writes the text filter to the URL and keeps it across toggles', async () => {
    const user = userEvent.setup()
    renderAt('/projects/p1/pull-requests')
    await screen.findByText('Merged PR')

    await user.type(
      screen.getByRole('textbox', { name: 'Filter pull requests' }),
      'pr',
    )
    await waitFor(() =>
      expect(screen.getByTestId('search')).toHaveTextContent('?q=pr'),
    )

    await user.click(screen.getByRole('button', { name: /^Open/ }))
    await user.click(screen.getByRole('button', { name: /Mine/ }))
    const params = new URLSearchParams(
      screen.getByTestId('search').textContent ?? '',
    )
    expect(Object.fromEntries(params)).toEqual({
      author: 'me',
      q: 'pr',
      state: 'open',
    })
  })
})
