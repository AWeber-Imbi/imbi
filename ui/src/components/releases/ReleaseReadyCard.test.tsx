import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import * as releases from '@/api/releases'
import { render } from '@/test/utils'
import type { ReleaseDrift } from '@/types'

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

function renderCard(drift: ReleaseDrift) {
  render(
    <ReleaseReadyCard
      drift={drift}
      onCut={() => {}}
      orgSlug="acme"
      projectId="p1"
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
