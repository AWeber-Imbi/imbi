import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { render } from '@/test/utils'
import type {
  CurrentReleaseEnvironment,
  Environment,
  RecentCommit,
  ReleaseHistoryEntry,
} from '@/types'

import { PendingReleasesCard } from './PendingReleasesCard'
import type { PipelineStage } from './pipeline'
import type { DeploymentActions } from './useDeploymentActions'

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
      recentCommits={recentCommits}
      stage={makeStage(pending, envTag)}
    />,
  )

describe('PendingReleasesCard', () => {
  it('shows the up-to-date state when nothing is pending', () => {
    renderCard([])
    expect(screen.getByText('Up to date with Staging')).toBeInTheDocument()
  })

  it('renders the single-release confirm with notes and synced changes', () => {
    renderCard([entry('v6.5.1', 'bbb222bbb222', 'Cache TTL fix')])
    expect(screen.getByText(/is waiting to go live/)).toBeInTheDocument()
    expect(screen.getByText('notes for v6.5.1')).toBeInTheDocument()
    // Changes section sliced from the synced commit history.
    expect(screen.getByText('the pending change')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Deploy v6\.5\.1 to production/ }),
    ).toBeInTheDocument()
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

  it('marks blocked releases in the selectable stack', () => {
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
    expect(
      screen.getByRole('button', { name: /Deploy v6\.5\.2 to production/ }),
    ).toBeEnabled()
  })

  it('links the PR references in the changes list', () => {
    renderCard(
      [entry('v6.5.1', 'bbb222bbb222', 'Cache TTL fix')],
      makeActions(),
      'v6.5.0',
      [
        {
          ...RECENT_COMMITS[0],
          message: 'Fix the cache TTL (#82)',
          url: 'https://github.com/aweber-imbi/imbi/commit/bbb222bbb222',
        },
        RECENT_COMMITS[1],
      ],
    )
    expect(screen.getByRole('link', { name: '#82' })).toHaveAttribute(
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
