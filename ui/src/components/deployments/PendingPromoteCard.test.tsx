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
    getTagFormats: vi.fn().mockResolvedValue([]),
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
  clearPromoteRefusal: vi.fn(),
  deploy: vi.fn(),
  deployPending: false,
  deployPendingSha: null,
  promote: vi.fn(),
  promotePending: false,
  promoteRefusal: null,
})

function renderCard(actions = makeActions(), stage: PipelineStage = STAGE) {
  render(
    <PendingPromoteCard
      accent={null}
      actions={actions}
      canTrigger
      orgSlug="acme"
      projectId="p1"
      stage={stage}
    />,
  )
  return actions
}

const promoteButton = () =>
  screen.getByRole('button', { name: /& deploy to staging/i })

describe('PendingPromoteCard — failing CI on the commit being tagged', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.getTagFormats).mockResolvedValue([])
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

describe('PendingPromoteCard — a breaking-change refusal from the API', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.getTagFormats).mockResolvedValue([])
    // The draft saw nothing breaking, so only the refusal can say so.
    vi.mocked(endpoints.draftReleaseNotes).mockResolvedValue({
      bump: 'patch',
      commits_considered: 2,
      degraded: false,
      notes_markdown: '### Fixed\n- Corrected test behavior',
      reasoning: 'a fix landed',
      version: '0.1.14',
    })
    vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
      ci_status: 'pass',
      committish: TIP.short_sha,
    })
  })

  it('puts the acknowledgement on screen and sends it', async () => {
    const user = userEvent.setup()
    const actions = renderCard({
      ...makeActions(),
      promoteRefusal: {
        breaking_changes: [
          {
            commit: 'aab005f',
            declared: true,
            description: 'fix!: drop the legacy field',
          },
        ],
        bump: 'minor',
        last_tag: '0.1.13',
        message: '0.1.14 is not a breaking-change release after 0.1.13, …',
        tag: '0.1.14',
      },
    })
    await waitFor(() => {
      expect(
        screen.getByText('0.1.14 is not a breaking-change release'),
      ).toBeInTheDocument()
    })
    expect(screen.getByText('fix!: drop the legacy field')).toBeInTheDocument()
    expect(promoteButton()).toBeDisabled()
    await user.click(
      screen.getByRole('checkbox', { name: /Promote 0.1.14 anyway/i }),
    )
    await user.click(promoteButton())
    expect(actions.promote).toHaveBeenCalledWith(
      expect.objectContaining({ acknowledgeBreakingChanges: true }),
    )
  })

  it('forgets the refusal when another commit is selected', async () => {
    const user = userEvent.setup()
    const actions = renderCard()
    await waitFor(() => {
      expect(screen.getByDisplayValue('0.1.14')).toBeInTheDocument()
    })
    const before = vi.mocked(actions.clearPromoteRefusal).mock.calls.length
    await user.click(screen.getByText('feat: an earlier change'))
    await waitFor(() => {
      expect(
        vi.mocked(actions.clearPromoteRefusal).mock.calls.length,
      ).toBeGreaterThan(before)
    })
  })

  it('drops a held-back commit from the draft evidence', async () => {
    const user = userEvent.setup()
    vi.mocked(endpoints.draftReleaseNotes).mockResolvedValue({
      breaking_changes: [
        { commit: 'aab005f', description: 'Drop the legacy field' },
      ],
      bump: 'patch',
      commits_considered: 2,
      degraded: false,
      notes_markdown: '### Fixed\n- Corrected test behavior',
      reasoning: 'a fix landed',
      version: '0.1.14',
    })
    renderCard()
    await waitFor(() => {
      expect(
        screen.getByText('0.1.14 is not a breaking-change release'),
      ).toBeInTheDocument()
    })
    await user.click(screen.getByText('feat: an earlier change'))
    await waitFor(() => {
      expect(
        screen.queryByText('Drop the legacy field'),
      ).not.toBeInTheDocument()
    })
    expect(promoteButton()).not.toBeDisabled()
  })
})

describe('PendingPromoteCard — tag formats and first promotes', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.getTagFormats).mockResolvedValue([])
    vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
      ci_status: 'pass',
      committish: TIP.short_sha,
    })
  })

  it('drafts from the synced history when the project has no tag yet', async () => {
    vi.mocked(endpoints.draftReleaseNotes).mockResolvedValue({
      bump: 'minor',
      commits_considered: 2,
      degraded: false,
      notes_markdown: '## First',
      reasoning: 'initial',
      version: '2026.09.17',
    })
    renderCard(makeActions(), { ...STAGE, latestTag: null })
    await waitFor(() => {
      expect(endpoints.draftReleaseNotes).toHaveBeenCalledWith('acme', 'p1', {
        base_sha: '',
        head_sha: TIP.sha,
        last_tag: null,
      })
    })
    await waitFor(() => {
      expect(screen.getByDisplayValue('2026.09.17')).toBeInTheDocument()
    })
  })

  it('accepts a calver tag when the project type allows it', async () => {
    vi.mocked(endpoints.getTagFormats).mockResolvedValue([
      {
        label: 'Calendar versioning',
        pattern: '^\\d{4}([.-])\\d{1,2}\\1\\d{1,2}(?:[.-]\\w+)?$',
      },
    ])
    vi.mocked(endpoints.draftReleaseNotes).mockResolvedValue({
      bump: 'patch',
      commits_considered: 2,
      degraded: false,
      notes_markdown: '## Notes',
      reasoning: 'a fix landed',
      version: '0.1.14',
    })
    const user = userEvent.setup()
    const actions = renderCard()
    // The semver draft does not fit the policy, so the form says so.
    await waitFor(() => {
      expect(
        screen.getByText('Use a Calendar versioning tag, e.g. 2026.09.17-0'),
      ).toBeInTheDocument()
    })
    expect(promoteButton()).toBeDisabled()
    const tagInput = screen.getByPlaceholderText('vX.Y.Z')
    await user.clear(tagInput)
    await user.type(tagInput, '2026.09.17-0')
    expect(screen.queryByText(/Use a /)).not.toBeInTheDocument()
    await waitFor(() => {
      expect(promoteButton()).toBeEnabled()
    })
    await user.click(promoteButton())
    expect(actions.promote).toHaveBeenCalledWith(
      expect.objectContaining({ tag: '2026.09.17-0' }),
    )
  })
})
