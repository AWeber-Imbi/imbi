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

import { CommitDeployCard } from './CommitDeployCard'
import type { PipelineStage } from './pipeline'
import type { DeploymentActions } from './useDeploymentActions'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/endpoints')>('@/api/endpoints')
  return { ...actual, getCommitCheckStatus: vi.fn() }
})

const ENV = {
  id: 'testing',
  label_color: '#6B9A3F',
  name: 'Testing',
  slug: 'testing',
  sort_order: 1,
} as unknown as Environment

const commit = (sha: string, message: string): RecentCommit => ({
  author: 'kevin',
  authored_at: '2026-06-01T00:00:00Z',
  ci_status: 'pass',
  message,
  sha,
  short_sha: sha.slice(0, 7),
})

const currentFor = (committish: string): CurrentReleaseEnvironment => ({
  ci_status: 'pass',
  current_status: 'success',
  environment: { name: 'testing', slug: 'testing' },
  external_run_url: null,
  last_event_at: '2026-06-01T00:00:00Z',
  performed_by: 'Imbi Automations',
  performed_by_email: null,
  release: {
    committish,
    created_at: '2026-06-01T00:00:00Z',
    created_by: 'gavin',
    id: 'rel-1',
    links: [],
    project_id: 'p1',
    tag: null,
    title: committish,
  },
})

const makeStage = (
  committish: string,
  current: Partial<CurrentReleaseEnvironment> = {},
): PipelineStage => ({
  current: { ...currentFor(committish), ...current },
  currentHistoryEntry: null,
  env: ENV,
  kind: 'commit',
  latestTag: null,
  pendingCommits: [],
  pendingReleases: [],
  promotableCommits: [],
  recentReleases: [],
  upstream: null,
  upstreamCurrent: null,
})

const makeActions = (): DeploymentActions => ({
  deploy: vi.fn(),
  deployPending: false,
  deployPendingSha: null,
  promote: vi.fn(),
  promotePending: false,
})

const RECENT = [
  commit('aaa1111aaa1111', 'newest change'),
  commit('bbb2222bbb2222', 'middle change'),
  commit('ccc3333ccc3333', 'older change'),
]

const setup = (
  committish: string,
  recentCommits: RecentCommit[] = RECENT,
  current: Partial<CurrentReleaseEnvironment> = {},
  actions: DeploymentActions = makeActions(),
) => {
  render(
    <CommitDeployCard
      accent={null}
      actions={actions}
      canTrigger
      orgSlug="acme"
      projectId="p1"
      recentCommits={recentCommits}
      stage={makeStage(committish, current)}
    />,
  )
  return actions
}

describe('CommitDeployCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
      ci_status: 'pass',
      committish: 'aaa1111',
    })
  })

  it('marks the deployed commit and splits Deploy/Roll back around it', () => {
    setup('bbb2222bbb2222')
    expect(screen.getByText('deployed')).toBeInTheDocument()
    expect(screen.getByText('HEAD')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Deploy/ })).toHaveLength(1)
    expect(screen.getAllByRole('button', { name: /Roll back/ })).toHaveLength(1)
  })

  it('attributes the running deployment to who deployed it and when', () => {
    setup('bbb2222bbb2222')
    const deployedAt = screen.getByText(/^Deployed/).querySelector('time')
    expect(deployedAt).toHaveAttribute('datetime', '2026-06-01T00:00:00Z')
    expect(screen.getByText('Imbi Automations')).toBeInTheDocument()
  })

  it('omits the deploy metadata the stage did not record', () => {
    const undated = RECENT.map(({ authored_at: _unused, ...rest }) => rest)
    setup('bbb2222bbb2222', undated, {
      last_event_at: null,
      performed_by: null,
    })
    expect(screen.queryByText(/^Deployed/)).toBeNull()
    expect(screen.queryByText('Imbi Automations')).toBeNull()
    expect(document.querySelectorAll('time')).toHaveLength(0)
  })

  it('pulls the deployed commit forward when it is outside the display window', () => {
    // 30 commits in the synced history; the deployed one is the 28th —
    // beyond the 25-row display window, so it pins below a gap row.
    const many = Array.from({ length: 30 }, (_, i) =>
      commit(`sha${String(i).padStart(4, '0')}aaaa`, `commit ${i}`),
    )
    setup('sha0027aaaa', many)
    expect(screen.getByText('deployed')).toBeInTheDocument()
    expect(screen.getByText('commit 27')).toBeInTheDocument()
    expect(screen.getByText('… older commits not shown')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Roll back/ })).toBeNull()
  })

  it('pins a bare-SHA row when the deployed commit is not synced at all', () => {
    setup('fff9999fff9999')
    expect(screen.getByText('deployed')).toBeInTheDocument()
    expect(
      screen.getByText('Not in the synced commit history — try a sync'),
    ).toBeInTheDocument()
  })

  it('links the PR references in a commit subject', () => {
    setup('bbb2222bbb2222', [
      {
        ...commit('aaa1111aaa1111', 'Key identity connections (#172)'),
        url: 'https://github.com/aweber-imbi/imbi/commit/aaa1111aaa1111',
      },
    ])
    expect(screen.getByRole('link', { name: '#172' })).toHaveAttribute(
      'href',
      'https://github.com/aweber-imbi/imbi/pull/172',
    )
  })

  it('leaves the subject plain when the commit has no URL', () => {
    setup('bbb2222bbb2222', [commit('aaa1111aaa1111', 'Key identities (#172)')])
    expect(screen.queryByRole('link', { name: '#172' })).toBeNull()
    expect(screen.getByText('Key identities (#172)')).toBeInTheDocument()
  })

  it('prompts for a sync when no commits are synced', () => {
    setup('bbb2222bbb2222', [])
    expect(
      screen.getByText(
        'No synced commits yet — run a sync from the pipeline sidebar.',
      ),
    ).toBeInTheDocument()
  })
})

describe('CommitDeployCard — failing CI on the commit being deployed', () => {
  const confirmButton = () =>
    screen.getByRole('button', { name: /^Deploy aaa1111$/ })

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
      ci_status: 'fail',
      committish: 'aaa1111',
    })
  })

  it('warns and holds the confirm until it is acknowledged', async () => {
    const user = userEvent.setup()
    setup('bbb2222bbb2222')
    await user.click(screen.getByRole('button', { name: /Deploy/ }))
    await waitFor(() => {
      expect(screen.getByText(/CI failed for aaa1111/)).toBeInTheDocument()
    })
    expect(confirmButton()).toBeDisabled()
  })

  it('carries the acknowledgement into the deploy request', async () => {
    // Regression guard: the card dispatches through
    // ``useDeploymentActions``, and a request that omits the flag is one
    // the API rightly answers 409 — after the operator ticked the box.
    const user = userEvent.setup()
    const actions = setup('bbb2222bbb2222')
    await user.click(screen.getByRole('button', { name: /Deploy/ }))
    await waitFor(() => {
      expect(screen.getByText(/CI failed for aaa1111/)).toBeInTheDocument()
    })
    await user.click(screen.getByRole('checkbox', { name: /Deploy anyway/i }))
    await waitFor(() => {
      expect(confirmButton()).not.toBeDisabled()
    })
    await user.click(confirmButton())
    expect(actions.deploy).toHaveBeenCalledWith(
      expect.objectContaining({
        acknowledgeCiFailure: true,
        sha: 'aaa1111aaa1111',
      }),
    )
  })

  it('reports no acknowledgement when the commit is green', async () => {
    const user = userEvent.setup()
    vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
      ci_status: 'pass',
      committish: 'aaa1111',
    })
    const actions = setup('bbb2222bbb2222')
    await user.click(screen.getByRole('button', { name: /Deploy/ }))
    await waitFor(() => {
      expect(confirmButton()).not.toBeDisabled()
    })
    expect(screen.queryByText(/CI failed/)).not.toBeInTheDocument()
    await user.click(confirmButton())
    expect(actions.deploy).toHaveBeenCalledWith(
      expect.objectContaining({ acknowledgeCiFailure: false }),
    )
  })

  it('asks about a rollback in its own words and still gates it', async () => {
    const user = userEvent.setup()
    vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
      ci_status: 'fail',
      committish: 'ccc3333',
    })
    setup('bbb2222bbb2222')
    await user.click(screen.getByRole('button', { name: /Roll back/ }))
    await waitFor(() => {
      expect(screen.getByText(/CI failed for ccc3333/)).toBeInTheDocument()
    })
    expect(
      screen.getByRole('checkbox', { name: /Roll back anyway/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /^Roll back to ccc3333$/ }),
    ).toBeDisabled()
  })
})
