import { MemoryRouter } from 'react-router-dom'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { UserEvent } from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import type { ProjectListItem } from '@/api/endpoints'

import { ProjectsView } from '../ProjectsView'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/endpoints')>('@/api/endpoints')
  return { ...actual, getProjectsSlim: vi.fn() }
})

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))
// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ user: { teams: [] } }),
}))
// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useLoginToEmail', () => ({
  useLoginToEmail: () => ({ displayNames: {}, loginToEmail: {} }),
}))
// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/ThemeContext', () => ({
  useTheme: () => ({ isDarkMode: false }),
}))

// The count sits alongside its option label inside the same <label>.
function countFor(panel: ReturnType<typeof within>, label: RegExp | string) {
  const row = panel.getByText(label).closest('label')
  if (!row) throw new Error(`No filter option row for ${String(label)}`)
  return within(row).getByTestId('filter-option-count').textContent
}

// Opens the popover behind the given filter button. Scoping to the
// popover matters: team names also render in the rows behind it.
async function openFilter(user: UserEvent, buttonLabel: RegExp) {
  await user.click(screen.getByRole('button', { name: buttonLabel }))
  return within(await screen.findByRole('dialog'))
}

function project(overrides: Partial<ProjectListItem> = {}): ProjectListItem {
  return {
    archived: false,
    closed_pr_count: 0,
    current_releases: {},
    description: null,
    environments: [],
    id: 'p1',
    name: 'Project One',
    open_pr_count: 0,
    project_types: [
      { deployable: false, name: 'API', releasable: false, slug: 'api' },
    ],
    release_summary: null,
    score: 90,
    slug: 'project-one',
    team: { name: 'Platform', slug: 'platform' },
    viewer_closed_pr_count: 0,
    viewer_open_pr_count: 0,
    ...overrides,
  }
}

const PROJECTS: ProjectListItem[] = [
  project({ id: 'p1', name: 'Alpha', score: 90 }),
  project({ id: 'p2', name: 'Bravo', score: 60 }),
  project({
    id: 'p3',
    name: 'Charlie',
    score: 90,
    team: { name: 'Payments', slug: 'payments' },
  }),
  // Drifts on both axes (staging behind production, commits past the
  // latest tag) and carries no score, so it exercises the drift facet
  // and the unscored bucket. Both axes also need a CI verdict saying
  // the range matters, or the rule suppresses them.
  project({
    current_releases: {
      production: { committish: 'bbb', tag: 'v2' },
      staging: { committish: 'aaa', tag: 'v1' },
    },
    // Staging sorts first and so runs the newer code: production's
    // commit is the base of the range, staging's the head.
    drift_ranges: { 'bbb..aaa': true },
    environments: [
      { name: 'Staging', slug: 'staging', sort_order: 1 },
      { name: 'Production', slug: 'production', sort_order: 2 },
    ],
    id: 'p4',
    name: 'Delta',
    project_types: [
      { deployable: true, name: 'Service', releasable: true, slug: 'service' },
    ],
    release_summary: {
      commits_since_tag: 2,
      drift_detected: true,
      head_sha: 'ccc',
    },
    score: null,
    team: { name: 'Delivery', slug: 'delivery' },
  }),
]

// Same shape as Delta, but CI called every commit in both ranges
// ignorable -- a docs-only promotion step.
const QUIET_PROJECTS: ProjectListItem[] = [
  project({
    current_releases: {
      production: { committish: 'bbb', tag: 'v2' },
      staging: { committish: 'aaa', tag: 'v1' },
    },
    drift_ranges: { 'bbb..aaa': false },
    environments: [
      { name: 'Staging', slug: 'staging', sort_order: 1 },
      { name: 'Production', slug: 'production', sort_order: 2 },
    ],
    id: 'p9',
    name: 'Quiet',
    project_types: [
      { deployable: true, name: 'Service', releasable: true, slug: 'service' },
    ],
    release_summary: {
      commits_since_tag: 2,
      drift_detected: false,
      head_sha: 'ccc',
    },
    team: { name: 'Delivery', slug: 'delivery' },
  }),
]

function renderView() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ProjectsView />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ProjectsView filter counts', () => {
  beforeEach(() => {
    vi.mocked(endpoints.getProjectsSlim).mockResolvedValue(PROJECTS)
  })

  it('shows per-option match totals in the team filter', async () => {
    renderView()
    await waitFor(() => expect(screen.getByText('Alpha')).toBeInTheDocument())
    const panel = await openFilter(userEvent.setup(), /filter by team/i)
    expect(countFor(panel, 'Platform')).toBe('2')
    expect(countFor(panel, 'Payments')).toBe('1')
  })

  it('counts a facet against the other facets, not its own', async () => {
    renderView()
    await waitFor(() => expect(screen.getByText('Alpha')).toBeInTheDocument())
    const user = userEvent.setup()

    // Narrow to the Platform team...
    const teams = await openFilter(user, /filter by team/i)
    await user.click(teams.getByRole('checkbox', { name: /platform/i }))
    await user.keyboard('{Escape}')

    // ...the score counts now cover only the two Platform projects...
    const scores = await openFilter(user, /filter by health score/i)
    expect(countFor(scores, /Healthy/)).toBe('1')
    expect(countFor(scores, /At risk/)).toBe('1')
    await user.keyboard('{Escape}')

    // ...while the team counts stay whole, because a facet does not
    // count against its own selection.
    const teamsAgain = await openFilter(user, /filter by team/i)
    expect(countFor(teamsAgain, 'Platform')).toBe('2')
    expect(countFor(teamsAgain, 'Payments')).toBe('1')
  })

  it('counts drift pairs, including commit-to-release drift', async () => {
    renderView()
    await waitFor(() => expect(screen.getByText('Delta')).toBeInTheDocument())
    const panel = await openFilter(userEvent.setup(), /filter by drift/i)
    expect(countFor(panel, /S → P/)).toBe('1')
    expect(countFor(panel, /C → R/)).toBe('1')
  })

  it('ignores a version difference CI called ignorable', async () => {
    // Same commits differ as Delta's, but every commit in the range is
    // marked false, so nothing needs promoting or releasing and the
    // drift filter has no options to offer at all.
    vi.mocked(endpoints.getProjectsSlim).mockResolvedValue(QUIET_PROJECTS)
    renderView()
    await waitFor(() => expect(screen.getByText('Quiet')).toBeInTheDocument())
    const panel = await openFilter(userEvent.setup(), /filter by drift/i)
    expect(panel.queryByText(/S → P/)).not.toBeInTheDocument()
    expect(panel.queryByText(/C → R/)).not.toBeInTheDocument()
  })

  it('offers an unscored option for projects with no score', async () => {
    renderView()
    await waitFor(() => expect(screen.getByText('Delta')).toBeInTheDocument())
    const panel = await openFilter(userEvent.setup(), /filter by health score/i)
    expect(countFor(panel, 'Unscored')).toBe('1')
  })
})
