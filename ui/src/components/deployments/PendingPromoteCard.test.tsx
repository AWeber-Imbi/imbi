import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { render } from '@/test/utils'
import type {
  CurrentReleaseEnvironment,
  Environment,
  RecentCommit,
} from '@/types'

import { PendingPromoteCard } from './PendingPromoteCard'
import type { PipelineStage } from './pipeline'
import type { DeploymentActions } from './useDeploymentActions'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/endpoints')>('@/api/endpoints')
  return {
    ...actual,
    draftReleaseNotes: vi.fn(),
    getCommitCheckStatus: vi.fn(),
  }
})

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), loading: vi.fn(), success: vi.fn() },
}))

const ENV = {
  label_color: '#C86B5E',
  name: 'Staging',
  slug: 'staging',
  sort_order: 2,
} as unknown as Environment

const UPSTREAM = {
  name: 'Testing',
  slug: 'testing',
  sort_order: 1,
} as unknown as Environment

const TIP: RecentCommit = {
  author: 'gavin',
  authored_at: '2026-06-02T00:00:00Z',
  ci_status: 'unknown',
  message: 'fix: corrected test behavior',
  sha: 'aab005fceed23f3a29acdf8ad89119b0b940c5c7',
  short_sha: 'aab005f',
  url: null,
}

const OLDER: RecentCommit = {
  author: 'gavin',
  authored_at: '2026-06-01T00:00:00Z',
  ci_status: 'unknown',
  message: 'feat: an earlier change',
  sha: 'bbb222bbb222bbb222bbb222bbb222bbb222bbb2',
  short_sha: 'bbb222b',
  url: null,
}

const UPSTREAM_CURRENT: CurrentReleaseEnvironment = {
  ci_status: null,
  current_status: 'success',
  environment: { name: 'testing', slug: 'testing' },
  external_run_url: null,
  last_event_at: '2026-06-02T00:00:00Z',
  release: { committish: TIP.sha, tag: null },
}

const STAGE: PipelineStage = {
  current: null,
  currentHistoryEntry: null,
  env: ENV,
  kind: 'promote',
  latestTag: '0.1.13',
  pendingCommits: [TIP, OLDER],
  pendingReleases: [],
  promotableCommits: [TIP, OLDER],
  recentReleases: [],
  upstream: UPSTREAM,
  upstreamCurrent: UPSTREAM_CURRENT,
}

const makeActions = (): DeploymentActions => ({
  deploy: vi.fn(),
  deployPending: false,
  deployPendingSha: null,
  promote: vi.fn(),
  promotePending: false,
})

function renderCard(actions = makeActions()) {
  render(
    <PendingPromoteCard
      accent={null}
      actions={actions}
      canTrigger
      orgSlug="acme"
      projectId="p1"
      stage={STAGE}
    />,
  )
  return actions
}

const promoteButton = () =>
  screen.getByRole('button', { name: /& deploy to staging/i })

describe('PendingPromoteCard — failing CI on the commit being tagged', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.draftReleaseNotes).mockResolvedValue({
      bump: 'patch',
      commits_considered: 2,
      degraded: false,
      notes_markdown: '### Fixed\n- Corrected test behavior',
      reasoning: 'a fix landed',
      version: '0.1.14',
    })
    vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
      ci_status: 'fail',
      committish: TIP.short_sha,
    })
  })

  it('warns and holds the promote until it is acknowledged', async () => {
    renderCard()
    await waitFor(() => {
      expect(screen.getByText(/CI failed for aab005f/)).toBeInTheDocument()
    })
    expect(promoteButton()).toBeDisabled()
  })

  it('carries the acknowledgement into the promote request', async () => {
    // Regression guard: this card dispatches through
    // ``useDeploymentActions``, whose ``acknowledgeCiFailure`` defaults to
    // false. Forgetting it here enables the button off local state while
    // the request still says the failure was never acknowledged, and the
    // API rightly answers 409.
    const user = userEvent.setup()
    const actions = renderCard()
    await waitFor(() => {
      expect(screen.getByText(/CI failed for aab005f/)).toBeInTheDocument()
    })
    await user.click(screen.getByRole('checkbox', { name: /Promote anyway/i }))
    await waitFor(() => {
      expect(promoteButton()).not.toBeDisabled()
    })
    await user.click(promoteButton())
    expect(actions.promote).toHaveBeenCalledWith(
      expect.objectContaining({
        acknowledgeCiFailure: true,
        sha: TIP.sha,
        toEnvironment: 'staging',
      }),
    )
  })

  it('reports no acknowledgement when the commit is green', async () => {
    const user = userEvent.setup()
    vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
      ci_status: 'pass',
      committish: TIP.short_sha,
    })
    const actions = renderCard()
    await waitFor(() => {
      expect(screen.getByDisplayValue('0.1.14')).toBeInTheDocument()
    })
    expect(screen.queryByText(/CI failed/)).not.toBeInTheDocument()
    await user.click(promoteButton())
    expect(actions.promote).toHaveBeenCalledWith(
      expect.objectContaining({ acknowledgeCiFailure: false }),
    )
  })

  it('drops the acknowledgement when another commit is selected', async () => {
    const user = userEvent.setup()
    renderCard()
    await waitFor(() => {
      expect(screen.getByText(/CI failed for aab005f/)).toBeInTheDocument()
    })
    await user.click(screen.getByRole('checkbox', { name: /Promote anyway/i }))
    await user.click(screen.getByText('feat: an earlier change'))
    await waitFor(() => {
      expect(
        screen.getByRole('checkbox', { name: /Promote anyway/i }),
      ).not.toBeChecked()
    })
    expect(promoteButton()).toBeDisabled()
  })
})
