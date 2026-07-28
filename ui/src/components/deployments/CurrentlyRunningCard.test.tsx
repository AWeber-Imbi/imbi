import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as releases from '@/api/releases'
import { render } from '@/test/utils'
import type {
  CurrentReleaseEnvironment,
  Environment,
  ReleaseHistoryEntry,
} from '@/types'

import { CurrentlyRunningCard } from './CurrentlyRunningCard'
import type { PipelineStage, RecentRelease } from './pipeline'
import type { DeploymentActions } from './useDeploymentActions'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/releases', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/releases')>('@/api/releases')
  return { ...actual, blockRelease: vi.fn(), unblockRelease: vi.fn() }
})

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}))

const blockRelease = vi.mocked(releases.blockRelease)
const unblockRelease = vi.mocked(releases.unblockRelease)

const ENV = {
  id: 'production',
  label_color: '#C86B5E',
  name: 'Production',
  slug: 'production',
  sort_order: 3,
  url: 'https://service.example.com',
} as unknown as Environment

const CURRENT: CurrentReleaseEnvironment = {
  ci_status: 'pass',
  current_status: 'success',
  environment: { name: 'production', slug: 'production' },
  external_run_url: null,
  last_event_at: '2026-06-01T00:00:00Z',
  performed_by: 'gavin',
  release: {
    committish: 'aaa111aaa111',
    created_at: '2026-06-01T00:00:00Z',
    created_by: 'gavin',
    id: 'rel-1',
    links: [],
    project_id: 'p1',
    tag: 'v6.5.0',
    title: 'v6.5.0',
  },
}

const ROLLBACK: ReleaseHistoryEntry = {
  author: 'gavin',
  ci_status: 'pass',
  notes_markdown: '### Fixed\n- old fix',
  published_at: '2026-05-01T00:00:00Z',
  sha: '000999000999',
  short_sha: '0009990',
  tag: 'v6.4.0',
}

/** The running release as it appears in the synced history. */
const RUNNING_ENTRY: ReleaseHistoryEntry = {
  ci_status: 'pass',
  notes_markdown: '### Added\n- current feature',
  published_at: '2026-06-01T00:00:00Z',
  sha: 'aaa111aaa111',
  short_sha: 'aaa111a',
  tag: 'v6.5.0',
}

/** A release ranking above the running one — where a rollback leaves it. */
const AHEAD: ReleaseHistoryEntry = {
  ci_status: 'pass',
  notes_markdown: '### Fixed\n- newer fix',
  published_at: '2026-06-15T00:00:00Z',
  sha: 'bbb222bbb222',
  short_sha: 'bbb222b',
  tag: 'v6.5.1',
}

const behind = (entry: ReleaseHistoryEntry): RecentRelease => ({
  deployable: true,
  entry,
  relation: 'behind',
})

const STAGE: PipelineStage = {
  current: CURRENT,
  currentHistoryEntry: null,
  env: ENV,
  kind: 'release',
  pendingCommits: [],
  pendingReleases: [],
  recentReleases: [behind(ROLLBACK)],
  upstream: { name: 'Staging', slug: 'staging' } as unknown as Environment,
  // A tagged upstream — so an unreachable ahead row can say why.
  upstreamCurrent: {
    ...CURRENT,
    environment: { name: 'staging', slug: 'staging' },
  },
}

const makeActions = (): DeploymentActions => ({
  deploy: vi.fn(),
  deployPending: false,
  deployPendingSha: null,
  promote: vi.fn(),
  promotePending: false,
})

const renderCard = (stage: PipelineStage = STAGE, actions = makeActions()) =>
  render(
    <CurrentlyRunningCard
      accent={null}
      actions={actions}
      canTrigger
      orgSlug="acme"
      projectId="p1"
      stage={stage}
    />,
  )

/** The row toggle; anchored so the "Block <tag>" action doesn't match. */
const rowToggle = (tag: string) =>
  screen.getByRole('button', {
    name: new RegExp(`^${tag.replace('.', '\\.')}`),
  })

const stageWith = (rel: ReleaseHistoryEntry): PipelineStage => ({
  ...STAGE,
  recentReleases: [behind(rel)],
})

describe('CurrentlyRunningCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    blockRelease.mockResolvedValue({ blocked: true, tag: 'v6.4.0' })
    unblockRelease.mockResolvedValue({ blocked: false, tag: 'v6.4.0' })
  })

  it('shows the running version, deployer, and environment URL', () => {
    renderCard()
    expect(screen.getByText('v6.5.0')).toBeInTheDocument()
    expect(screen.getByText('gavin')).toBeInTheDocument()
    expect(screen.getByText('service.example.com')).toBeInTheDocument()
  })

  it('expands a recent release into its notes', async () => {
    const user = userEvent.setup()
    renderCard()
    await user.click(rowToggle('v6.4.0'))
    expect(screen.getByText('old fix')).toBeInTheDocument()
  })

  it('rolls back through the confirm dialog', async () => {
    const actions = makeActions()
    const user = userEvent.setup()
    renderCard(STAGE, actions)
    await user.click(screen.getByRole('button', { name: 'Roll back v6.4.0' }))
    await user.click(
      screen.getByRole('button', { name: 'Roll back to v6.4.0' }),
    )
    expect(actions.deploy).toHaveBeenCalledWith({
      action: 'deploy',
      envName: 'Production',
      envSlug: 'production',
      refLabel: 'v6.4.0',
      rollback: true,
      sha: '000999000999',
    })
  })

  it('blocks a recent release with a reason', async () => {
    const user = userEvent.setup()
    renderCard()
    await user.click(screen.getByRole('button', { name: 'Block v6.4.0' }))
    const submit = screen.getByRole('button', { name: 'Block v6.4.0' })
    expect(submit).toBeDisabled()
    await user.type(screen.getByRole('textbox'), 'Regression in checkout')
    await user.click(submit)
    await waitFor(() =>
      expect(blockRelease).toHaveBeenCalledWith('acme', 'p1', 'v6.4.0', {
        reason: 'Regression in checkout',
      }),
    )
  })

  it('marks the running release rather than offering it as a target', () => {
    renderCard({
      ...STAGE,
      recentReleases: [
        { deployable: false, entry: RUNNING_ENTRY, relation: 'current' },
        behind(ROLLBACK),
      ],
    })
    expect(screen.getByText('Running')).toBeInTheDocument()
    // One action button — the roll back on v6.4.0, not on the running row.
    expect(screen.getAllByRole('button', { name: /^Roll back / })).toHaveLength(
      1,
    )
  })

  it('offers a forward deploy for a release above the running one', async () => {
    // Production was rolled back v6.5.1 -> v6.5.0; v6.5.1 is still live in
    // staging, so it stays deployable rather than vanishing from the list.
    const actions = makeActions()
    const user = userEvent.setup()
    renderCard(
      {
        ...STAGE,
        recentReleases: [
          { deployable: true, entry: AHEAD, relation: 'ahead' },
          { deployable: false, entry: RUNNING_ENTRY, relation: 'current' },
          behind(ROLLBACK),
        ],
      },
      actions,
    )
    expect(screen.getByText('v6.5.1')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Deploy v6.5.1' }))
    await user.click(
      screen.getByRole('button', { name: 'Deploy v6.5.1 to production' }),
    )
    expect(actions.deploy).toHaveBeenCalledWith({
      action: 'deploy',
      envName: 'Production',
      envSlug: 'production',
      refLabel: 'v6.5.1',
      rollback: false,
      sha: 'bbb222bbb222',
    })
  })

  it('lists a release the upstream has not reached without a control', () => {
    renderCard({
      ...STAGE,
      recentReleases: [{ deployable: false, entry: AHEAD, relation: 'ahead' }],
    })
    expect(screen.getByText('v6.5.1')).toBeInTheDocument()
    expect(screen.getByText('Not in staging')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Deploy v6.5.1' })).toBeNull()
  })

  it('claims nothing about an untagged upstream', () => {
    // Promote stage: the upstream runs a raw commit, so there is no tag to
    // compare against and "Not in staging" would assert something
    // unevaluable. The row still lists, just without a control.
    renderCard({
      ...STAGE,
      kind: 'promote',
      recentReleases: [{ deployable: false, entry: AHEAD, relation: 'ahead' }],
      upstreamCurrent: {
        ...CURRENT,
        environment: { name: 'staging', slug: 'staging' },
        release: { ...CURRENT.release!, tag: null },
      },
    })
    expect(screen.getByText('v6.5.1')).toBeInTheDocument()
    expect(screen.queryByText(/^Not in/)).toBeNull()
    expect(screen.queryByRole('button', { name: 'Deploy v6.5.1' })).toBeNull()
  })

  it('will not roll back to a blocked release, and can unblock it', async () => {
    const user = userEvent.setup()
    renderCard(
      stageWith({
        ...ROLLBACK,
        blocked: true,
        blocked_by: 'gavinr@aweber.com',
        blocked_reason: 'Regression in checkout',
      }),
    )
    // The Blocked badge replaces the Roll back button outright.
    expect(screen.getByText('Blocked')).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Roll back v6.4.0' }),
    ).toBeNull()
    // Unblock sits with the reason, not in the collapsed row.
    expect(screen.queryByRole('button', { name: 'Unblock' })).toBeNull()
    await user.click(rowToggle('v6.4.0'))
    expect(screen.getByText(/Regression in checkout/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Unblock' }))
    expect(unblockRelease).toHaveBeenCalledWith('acme', 'p1', 'v6.4.0')
  })
})
