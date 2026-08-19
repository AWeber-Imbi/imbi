import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import * as endpoints from '@/api/endpoints'
import * as releases from '@/api/releases'
import { render } from '@/test/utils'
import type { ReleaseDrift } from '@/types'

import { RELEASE_IDLE, type ReleaseInFlightState } from './releaseInFlight'
import { ReleaseReadyCard } from './ReleaseReadyCard'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/endpoints')>('@/api/endpoints')
  return {
    ...actual,
    draftReleaseNotes: vi.fn(),
    getCommitCheckStatus: vi.fn(),
    listAdminUsers: vi.fn().mockResolvedValue([]),
  }
})

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/releases', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/releases')>('@/api/releases')
  return { ...actual, cutRelease: vi.fn() }
})

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    loading: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}))

const COMMITS = [
  {
    author: 'Alice',
    authored_at: '2026-01-02T00:00:00Z',
    ci_status: 'pass' as const,
    message: 'feat: a new thing',
    sha: 'aaa1111',
    short_sha: 'aaa1111',
    url: null,
  },
  {
    author: 'Bob',
    authored_at: '2026-01-01T00:00:00Z',
    ci_status: 'pass' as const,
    message: 'fix: a bug',
    sha: 'bbb2222',
    short_sha: 'bbb2222',
    url: null,
  },
]

// First-release drift (no prior tag) -> no AI auto-draft to interfere.
const FIRST_RELEASE: ReleaseDrift = {
  commits: COMMITS,
  commits_since_tag: 2,
  head_sha: 'aaa1111',
  latest_tag: null,
  latest_tag_at: null,
  latest_tag_sha: null,
  suggested_bump: 'minor',
  suggested_tag: 'v0.1.0',
}

const inFlight = (
  over: Partial<ReleaseInFlightState> = {},
): ReleaseInFlightState => ({ ...RELEASE_IDLE, ...over })

function renderCard(
  drift: ReleaseDrift,
  state: ReleaseInFlightState = inFlight(),
) {
  render(
    <ReleaseReadyCard
      drift={drift}
      onCut={() => {}}
      orgSlug="acme"
      projectId="p1"
      releaseInFlight={state}
    />,
  )
}

describe('ReleaseReadyCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(releases.cutRelease).mockResolvedValue({
      committish: 'aaa1111',
      recorded: true,
      release_url: 'https://gh/releases/v0.1.0',
      tag: 'v0.1.0',
    })
    vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
      ci_status: 'pass',
      committish: 'aaa1111',
    })
  })

  it('renders the up-to-date card when there is no drift', () => {
    renderCard({ ...FIRST_RELEASE, commits: [], commits_since_tag: 0 })
    expect(screen.getByText('Up to date')).toBeInTheDocument()
  })

  it('shows the author and age of each commit', () => {
    renderCard(FIRST_RELEASE)
    expect(screen.getByText('Alice')).toBeInTheDocument()
    expect(screen.getByText('Bob')).toBeInTheDocument()
    const ages = document.querySelectorAll('time')
    expect(Array.from(ages).map((el) => el.getAttribute('datetime'))).toContain(
      '2026-01-02T00:00:00Z',
    )
  })

  it('cuts a release with the tip commit and suggested tag', async () => {
    const user = userEvent.setup()
    renderCard(FIRST_RELEASE)
    await user.click(screen.getByRole('button', { name: /& release/i }))
    await waitFor(() => {
      expect(releases.cutRelease).toHaveBeenCalledWith('acme', 'p1', {
        acknowledge_ci_failure: false,
        committish: 'aaa1111',
        release_name: 'v0.1.0',
        release_notes_markdown: '',
        tag: 'v0.1.0',
      })
    })
  })

  it('blocks submission on an invalid semver tag', async () => {
    const user = userEvent.setup()
    renderCard(FIRST_RELEASE)
    const tagInput = screen.getByPlaceholderText('vX.Y.Z')
    await user.clear(tagInput)
    await user.type(tagInput, 'main')
    expect(screen.getByText(/Use a semver tag/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /& release/i })).toBeDisabled()
  })

  it('auto-drafts release notes when a prior tag exists', async () => {
    vi.mocked(endpoints.draftReleaseNotes).mockResolvedValue({
      bump: 'major',
      commits_considered: 2,
      degraded: false,
      notes_markdown: '## AI notes',
      reasoning: 'big change',
      version: 'v2.0.0',
    })
    renderCard({
      ...FIRST_RELEASE,
      latest_tag: 'v1.0.0',
      latest_tag_sha: 'tagsha',
      suggested_tag: 'v1.1.0',
    })
    await waitFor(() => {
      expect(endpoints.draftReleaseNotes).toHaveBeenCalled()
    })
    await waitFor(() => {
      expect(screen.getByDisplayValue('v2.0.0')).toBeInTheDocument()
    })
  })

  describe('failing CI on the selected commit', () => {
    beforeEach(() => {
      vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
        ci_status: 'fail',
        committish: 'aaa1111',
      })
    })

    it('warns and holds the release until it is acknowledged', async () => {
      renderCard(FIRST_RELEASE)
      await waitFor(() => {
        expect(screen.getByText(/CI failed for aaa1111/)).toBeInTheDocument()
      })
      expect(screen.getByRole('button', { name: /& release/i })).toBeDisabled()
    })

    it('releases anyway once acknowledged, and says so to the API', async () => {
      const user = userEvent.setup()
      renderCard(FIRST_RELEASE)
      await waitFor(() => {
        expect(screen.getByText(/CI failed for aaa1111/)).toBeInTheDocument()
      })
      await user.click(
        screen.getByRole('checkbox', { name: /Release anyway/i }),
      )
      await user.click(screen.getByRole('button', { name: /& release/i }))
      await waitFor(() => {
        expect(releases.cutRelease).toHaveBeenCalledWith(
          'acme',
          'p1',
          expect.objectContaining({ acknowledge_ci_failure: true }),
        )
      })
    })

    it('drops the acknowledgement when another commit is picked', async () => {
      const user = userEvent.setup()
      renderCard(FIRST_RELEASE)
      await waitFor(() => {
        expect(screen.getByText(/CI failed for aaa1111/)).toBeInTheDocument()
      })
      await user.click(
        screen.getByRole('checkbox', { name: /Release anyway/i }),
      )
      // A different commit is a different decision.
      await user.click(screen.getByText('fix: a bug'))
      await waitFor(() => {
        expect(
          screen.getByRole('checkbox', { name: /Release anyway/i }),
        ).not.toBeChecked()
      })
      expect(screen.getByRole('button', { name: /& release/i })).toBeDisabled()
    })
  })

  it('stays silent when the CI status cannot be resolved', async () => {
    // `unknown` covers a project with no CI and a token that cannot read
    // check-runs; the API does not gate on it, so neither does the form.
    vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
      ci_status: 'unknown',
      committish: 'aaa1111',
    })
    renderCard(FIRST_RELEASE)
    // Wait for the *resolved* status, not just the call: submission is
    // held while the query is in flight, so asserting on dispatch alone
    // would race the answer it is waiting for.
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /& release/i }),
      ).not.toBeDisabled()
    })
    expect(endpoints.getCommitCheckStatus).toHaveBeenCalled()
    expect(screen.queryByText(/CI failed/)).not.toBeInTheDocument()
  })

  it('holds submission until the CI status resolves', async () => {
    // An unresolved query has no status, and "no status" reads the same
    // as `unknown` — so without this the operator can submit a red
    // commit before the answer lands and take a bare 409 instead of the
    // acknowledgement flow.
    let resolve: (value: { ci_status: string; committish: string }) => void
    vi.mocked(endpoints.getCommitCheckStatus).mockReturnValue(
      new Promise((r) => {
        resolve = r as typeof resolve
      }) as ReturnType<typeof endpoints.getCommitCheckStatus>,
    )
    renderCard(FIRST_RELEASE)
    await waitFor(() => {
      expect(endpoints.getCommitCheckStatus).toHaveBeenCalled()
    })
    expect(screen.getByRole('button', { name: /& release/i })).toBeDisabled()

    resolve!({ ci_status: 'pass', committish: 'aaa1111' })
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /& release/i }),
      ).not.toBeDisabled()
    })
  })
})

describe('ReleaseReadyCard — a release already in flight', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
      ci_status: 'pass',
      committish: 'aaa1111',
    })
  })

  it('goes inert while a build runs and names the release holding it', async () => {
    // The bug this closes: the cut mutation settles when the build is
    // dispatched, so the button re-enabled a second later over the same
    // drift and the same suggested tag.
    renderCard(
      FIRST_RELEASE,
      inFlight({ blocked: true, phase: 'building', tag: 'v0.1.0' }),
    )
    expect(
      screen.getByRole('button', { name: /Release in flight/ }),
    ).toBeDisabled()
    expect(
      screen.getByText('Blocked until v0.1.0 finishes releasing'),
    ).toBeInTheDocument()
  })

  it('stays inert before the first poll answers', () => {
    // Guessing "idle" for one tick after a reload is exactly the window
    // the double cut lands in.
    renderCard(FIRST_RELEASE, inFlight({ blocked: true, phase: 'adopting' }))
    expect(
      screen.getByRole('button', { name: /Release in flight/ }),
    ).toBeDisabled()
    expect(
      screen.getByText('Checking for a release in flight…'),
    ).toBeInTheDocument()
  })

  it('says the tag is blocked when the build failed', () => {
    renderCard(
      FIRST_RELEASE,
      inFlight({ blocked: true, phase: 'build_failed', tag: 'v0.1.0' }),
    )
    expect(
      screen.getByRole('button', { name: /Release blocked/ }),
    ).toBeDisabled()
    expect(
      screen.getByText(/v0\.1\.0 is blocked — unblock it/),
    ).toBeInTheDocument()
  })

  it('re-enables once the release settles', async () => {
    renderCard(FIRST_RELEASE, inFlight({ phase: 'success', tag: 'v0.1.0' }))
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /& release/ }),
      ).not.toBeDisabled()
    })
  })
})

describe('ReleaseReadyCard — a refused dispatch', () => {
  const WORKFLOW_DETAIL =
    "The configured Release workflow 'release.yml' does not exist in this " +
    "project's repository, so there is nothing to dispatch. Correct the " +
    'Release workflow option on the integration, or clear it to cut the ' +
    'tag directly. Workflows found: test.yml.'

  const releaseButton = () => screen.getByRole('button', { name: /& release/i })

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
      ci_status: 'pass',
      committish: 'aaa1111',
    })
    vi.mocked(releases.cutRelease).mockRejectedValue(
      new ApiError(400, 'Bad Request', { detail: WORKFLOW_DETAIL }),
    )
  })

  it('renders the server detail inline and re-enables the form', async () => {
    // Sentry IMBI-4T: the API explains exactly what is misconfigured and
    // how to fix it, and all of it used to go into a toast that dismissed
    // itself. Nothing was dispatched, so the form must come back too.
    const user = userEvent.setup()
    renderCard(FIRST_RELEASE)
    await user.click(releaseButton())
    await waitFor(() => {
      expect(screen.getByText(WORKFLOW_DETAIL)).toBeInTheDocument()
    })
    expect(screen.getByText('Release refused')).toBeInTheDocument()
    expect(screen.getByText(/Nothing was dispatched/)).toBeInTheDocument()
    await waitFor(() => expect(releaseButton()).not.toBeDisabled())
  })

  it('keeps the refusal on screen until something changes', async () => {
    // The fix is two sentences into the detail; it has to still be there
    // while the operator acts on it.
    const user = userEvent.setup()
    renderCard(FIRST_RELEASE)
    await user.click(releaseButton())
    await waitFor(() => {
      expect(screen.getByText(WORKFLOW_DETAIL)).toBeInTheDocument()
    })
    await user.click(screen.getByText('fix: a bug'))
    await waitFor(() => {
      expect(screen.queryByText(WORKFLOW_DETAIL)).toBeNull()
    })
  })

  it('clears the refusal when the tag is edited', async () => {
    // A 409 names the tag that was refused; typing a different one makes
    // the old refusal describe a request nobody is making any more.
    const user = userEvent.setup()
    renderCard(FIRST_RELEASE)
    await user.click(releaseButton())
    await waitFor(() => {
      expect(screen.getByText(WORKFLOW_DETAIL)).toBeInTheDocument()
    })
    await user.type(screen.getByLabelText('New tag'), '1')
    await waitFor(() => {
      expect(screen.queryByText(WORKFLOW_DETAIL)).toBeNull()
    })
  })

  it('leaves a failure it cannot explain to the toast', async () => {
    // A 500 carries no sentence worth pinning to the form; "something
    // broke" is what a toast is for.
    const user = userEvent.setup()
    vi.mocked(releases.cutRelease).mockRejectedValue(
      new ApiError(500, 'Internal Server Error', { detail: 'boom' }),
    )
    renderCard(FIRST_RELEASE)
    await user.click(releaseButton())
    await waitFor(() => expect(releases.cutRelease).toHaveBeenCalled())
    expect(screen.queryByText('Release refused')).toBeNull()
    // "Left to the toast" means the toast actually fires — without this a
    // regression that swallows the failure entirely would still pass.
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('boom'))
  })
})
