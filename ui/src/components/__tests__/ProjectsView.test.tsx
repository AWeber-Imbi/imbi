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
  const row = panel.getByText(label).closest('label') as HTMLElement
  const spans = row.querySelectorAll(':scope > span')
  return spans[spans.length - 1]?.textContent
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
})
