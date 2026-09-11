import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { render } from '@/test/utils'
import type {
  CurrentReleaseEnvironment,
  DeploymentCommit,
  DeploymentCompareResult,
  Environment,
  RecentCommit,
  ReleaseHistoryEntry,
} from '@/types'

import { PendingReleasesCard } from './PendingReleasesCard'
import type { PipelineStage } from './pipeline'
import type { DeploymentActions } from './useDeploymentActions'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/endpoints')>('@/api/endpoints')
  return {
    ...actual,
    compareDeploymentRefs: vi.fn(),
    getCommitCheckStatus: vi.fn(),
  }
})

const ENV = {
  can_deploy: true,
  can_promote: false,
  id: 'production',
  label_color: '#C86B5E',
  name: 'Production',
  slug: 'production',
  sort_order: 3,
} as unknown as Environment

const UPSTREAM = {
  id: 'staging',
  label_color: '#5A89C9',
  name: 'Staging',
  slug: 'staging',
  sort_order: 2,
} as unknown as Environment

const entry = (
  tag: string,
  sha: string,
  title: string,
): ReleaseHistoryEntry => ({
  ci_status: 'pass',
  notes_markdown: `### Fixed\n- notes for ${tag}`,
  published_at: '2026-06-01T00:00:00Z',
  sha,
  short_sha: sha.slice(0, 7),
  tag,
  title,
})

const current = (
  slug: string,
  tag: string,
  committish: string,
): CurrentReleaseEnvironment => ({
  ci_status: 'pass',
  current_status: 'success',
  environment: { name: slug, slug },
  external_run_url: null,
  last_event_at: '2026-05-20T00:00:00Z',
  release: {
    committish,
    created_at: '2026-05-20T00:00:00Z',
    created_by: 'gavin',
    id: `${slug}-rel`,
    links: [],
    project_id: 'p1',
    tag,
    title: tag,
  },
})

const RECENT_COMMITS: RecentCommit[] = [
  {
    authored_at: '2026-06-01T00:00:00Z',
    ci_status: 'pass',
    message: 'the pending change',
    sha: 'bbb222bbb222',
    short_sha: 'bbb222b',
  },
  {
    authored_at: '2026-05-20T00:00:00Z',
    ci_status: 'pass',
    message: 'the released change',
    sha: 'aaa111aaa111',
    short_sha: 'aaa111a',
  },
]

const makeActions = (): DeploymentActions => ({
  deploy: vi.fn(),
  deployPending: false,
  deployPendingSha: null,
  promote: vi.fn(),
  promotePending: false,
})

const makeStage = (
  pending: ReleaseHistoryEntry[],
  envTag = 'v6.5.0',
): PipelineStage => ({
  current: current('production', envTag, 'aaa111aaa111'),
  currentHistoryEntry: null,
  env: ENV,
  kind: 'release',
  latestTag: null,
  pendingCommits: [],
  pendingReleases: pending,
  promotableCommits: [],
  recentReleases: [],
  upstream: UPSTREAM,
  upstreamCurrent: current('staging', 'v6.5.2', 'ccc333ccc333'),
})

const renderCard = (
  pending: ReleaseHistoryEntry[],
  actions = makeActions(),
  envTag = 'v6.5.0',
  recentCommits = RECENT_COMMITS,
) =>
  render(
    <PendingReleasesCard
      accent={null}
      actions={actions}
      canTrigger
      orgSlug="acme"
      projectId="p1"
      recentCommits={recentCommits}
      stage={makeStage(pending, envTag)}
    />,
  )

// What the source host says ``current..pending`` contains, oldest-first
// as the compare API answers it.
const compareCommit = (
  sha: string,
  message: string,
  extra: Partial<DeploymentCommit> = {},
): DeploymentCommit => ({
  ci_status: 'pass',
  is_head: false,
  message,
  sha,
  short_sha: sha.slice(0, 7),
  ...extra,
})

const compareResult = (
  commits: DeploymentCommit[],
): DeploymentCompareResult => ({
  additions: 0,
  ahead: commits.length,
  base_sha: 'aaa111aaa111',
  behind: 0,
  commits,
  deletions: 0,
  files_changed: 0,
  head_sha: commits[commits.length - 1]?.sha ?? 'aaa111aaa111',
  pr_numbers: [],
})

describe('PendingReleasesCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
      ci_status: 'pass',
      committish: 'ccc333c',
    })
    vi.mocked(endpoints.compareDeploymentRefs).mockResolvedValue(
      compareResult([compareCommit('bbb222bbb222', 'the pending change')]),
    )
  })

  it('shows the up-to-date state when nothing is pending', () => {
    renderCard([])
    expect(screen.getByText('Up to date with Staging')).toBeInTheDocument()
  })

  it('renders the single-release confirm with notes and changes', async () => {
    renderCard([entry('v6.5.1', 'bbb222bbb222', 'Cache TTL fix')])
    expect(screen.getByText(/is waiting to go live/)).toBeInTheDocument()
    expect(screen.getByText('notes for v6.5.1')).toBeInTheDocument()
    expect(await screen.findByText('the pending change')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Deploy v6\.5\.1 to production/ }),
    ).toBeInTheDocument()
  })

  it('lists the compared current..pending range, newest first', async () => {
    // The synced window has these in the wrong order (a re-synced old
    // commit sorted into the range, #308); the compare is what counts.
    vi.mocked(endpoints.compareDeploymentRefs).mockResolvedValue(
      compareResult([
        compareCommit('ccc333ccc333', 'the earlier change'),
        compareCommit('bbb222bbb222', 'the pending change', {
          is_head: true,
        }),
      ]),
    )
    renderCard(
      [entry('v6.5.1', 'bbb222bbb222', 'Cache TTL fix')],
      makeActions(),
      'v6.5.0',
      [
        RECENT_COMMITS[0],
        {
          authored_at: '2026-05-01T00:00:00Z',
          ci_status: 'pass',
          message: 'the re-synced old change',
          sha: '26de0ec26de0',
          short_sha: '26de0ec',
        },
        RECENT_COMMITS[1],
      ],
    )
    await screen.findByText('the pending change')
    expect(endpoints.compareDeploymentRefs).toHaveBeenCalledWith(
      'acme',
      'p1',
      'aaa111aaa111',
      'bbb222bbb222',
      undefined,
      expect.anything(),
    )
    const rows = screen.getAllByRole('listitem').map((li) => li.textContent)
    expect(rows[0]).toContain('the pending change')
    expect(rows[1]).toContain('the earlier change')
    expect(screen.getByText('2 commits')).toBeInTheDocument()
    // Sorted inside the synced window's slice, but not in the range.
    expect(
      screen.queryByText('the re-synced old change'),
    ).not.toBeInTheDocument()
  })

  it('labels a compare the host could not list in full', async () => {
    vi.mocked(endpoints.compareDeploymentRefs).mockResolvedValue({
      ...compareResult([compareCommit('bbb222bbb222', 'the pending change')]),
      ahead: 5001,
    })
    renderCard([entry('v6.5.1', 'bbb222bbb222', 'Cache TTL fix')])
    expect(await screen.findByText('the pending change')).toBeInTheDocument()
    expect(screen.getByText('1 of 5001 commits')).toBeInTheDocument()
  })

  it('falls back to the synced slice when the compare fails', async () => {
    vi.mocked(endpoints.compareDeploymentRefs).mockRejectedValue(
      new Error('source host unavailable'),
    )
    renderCard([entry('v6.5.1', 'bbb222bbb222', 'Cache TTL fix')])
    expect(await screen.findByText('the pending change')).toBeInTheDocument()
    expect(screen.getByText('1 commits')).toBeInTheDocument()
  })

  it('dispatches a deploy for the selected release', async () => {
    const actions = makeActions()
    const user = userEvent.setup()
    renderCard(
      [
        entry('v6.5.2', 'ccc333ccc333', 'Net-zero patch'),
        entry('v6.5.1', 'bbb222bbb222', 'Cache TTL fix'),
      ],
      actions,
    )
    expect(
      screen.getByText('2 releases waiting to go live'),
    ).toBeInTheDocument()
    // Defaults to the newest release; the older one rolls up.
    expect(screen.getByText(/v6\.5\.1 is rolled up/)).toBeInTheDocument()
    await user.click(
      screen.getByRole('button', { name: /Deploy v6\.5\.2 to production/ }),
    )
    expect(actions.deploy).toHaveBeenCalledWith({
      acknowledgeCiFailure: false,
      action: 'deploy',
      envName: 'Production',
      envSlug: 'production',
      refLabel: 'v6.5.2',
      sha: 'ccc333ccc333',
    })
  })

  it('selecting an older release updates the button, note, and notes accordion', async () => {
    const user = userEvent.setup()
    renderCard([
      entry('v6.5.2', 'ccc333ccc333', 'Net-zero patch'),
      entry('v6.5.1', 'bbb222bbb222', 'Cache TTL fix'),
    ])
    await user.click(screen.getByRole('button', { name: /v6\.5\.1/ }))
    expect(
      screen.getByRole('button', { name: /Deploy v6\.5\.1 to production/ }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/v6\.5\.2 stays pending above it/),
    ).toBeInTheDocument()
    // Row click also expands the release notes accordion.
    expect(screen.getByText('notes for v6.5.1')).toBeInTheDocument()
  })

  it('refuses to deploy a blocked release and names the reason', () => {
    renderCard([
      {
        ...entry('v6.5.1', 'bbb222bbb222', 'Cache TTL fix'),
        blocked: true,
        blocked_reason: 'Regression in the checkout flow',
      },
    ])
    expect(
      screen.getByText(/Regression in the checkout flow/),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Deploy v6\.5\.1 to production/ }),
    ).toBeDisabled()
  })

  it('marks blocked releases in the selectable stack', async () => {
    renderCard([
      entry('v6.5.2', 'ccc333ccc333', 'Net-zero patch'),
      {
        ...entry('v6.5.1', 'bbb222bbb222', 'Cache TTL fix'),
        blocked: true,
        blocked_reason: 'Rolled back',
      },
    ])
    // The newest is selected and deployable; the blocked one is labelled.
    expect(screen.getByText('Blocked')).toBeInTheDocument()
    // Enabled only once CI has answered for the selected release -- until
    // then the button is held rather than guessing green.
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Deploy v6\.5\.2 to production/ }),
      ).toBeEnabled()
    })
  })

  it('links the PR references in the changes list', async () => {
    vi.mocked(endpoints.compareDeploymentRefs).mockResolvedValue(
      compareResult([
        compareCommit('bbb222bbb222', 'Fix the cache TTL (#82)', {
          url: 'https://github.com/aweber-imbi/imbi/commit/bbb222bbb222',
        }),
      ]),
    )
    renderCard([entry('v6.5.1', 'bbb222bbb222', 'Cache TTL fix')])
    expect(await screen.findByRole('link', { name: '#82' })).toHaveAttribute(
      'href',
      'https://github.com/aweber-imbi/imbi/pull/82',
    )
  })

  it('warns when the pending release ranks below the running one', () => {
    // Production runs 2.101.0; staging's 1.102.3 is still deployable but
    // flagged as a roll back to the older line.
    renderCard(
      [entry('1.102.3', 'bbb222bbb222', 'Older line hotfix')],
      makeActions(),
      '2.101.0',
    )
    expect(
      screen.getByText(/rolls this environment to the older release line/),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Deploy 1\.102\.3 to production/ }),
    ).toBeInTheDocument()
  })
})

describe('PendingReleasesCard — failing CI on the release commit', () => {
  const deployButton = () =>
    screen.getByRole('button', { name: /Deploy v6\.5\.1 to production/ })

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
      ci_status: 'fail',
      committish: 'bbb222b',
    })
  })

  it('warns and holds the deploy until it is acknowledged', async () => {
    renderCard([entry('v6.5.1', 'bbb222bbb222', 'Cache TTL fix')])
    await waitFor(() => {
      expect(screen.getByText(/CI failed for bbb222b/)).toBeInTheDocument()
    })
    expect(deployButton()).toBeDisabled()
  })

  it('carries the acknowledgement into the deploy request', async () => {
    const user = userEvent.setup()
    const actions = makeActions()
    renderCard([entry('v6.5.1', 'bbb222bbb222', 'Cache TTL fix')], actions)
    await waitFor(() => {
      expect(screen.getByText(/CI failed for bbb222b/)).toBeInTheDocument()
    })
    await user.click(screen.getByRole('checkbox', { name: /Deploy anyway/i }))
    await waitFor(() => {
      expect(deployButton()).not.toBeDisabled()
    })
    await user.click(deployButton())
    expect(actions.deploy).toHaveBeenCalledWith(
      expect.objectContaining({ acknowledgeCiFailure: true }),
    )
  })
})
