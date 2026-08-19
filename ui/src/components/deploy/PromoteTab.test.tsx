import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import * as endpoints from '@/api/endpoints'
import {
  RELEASE_IDLE,
  type ReleaseInFlightState,
} from '@/components/releases/releaseInFlight'
import { render } from '@/test/utils'
import type {
  CurrentReleaseEnvironment,
  DeploymentCompareResult,
  Environment,
} from '@/types'

import { PromoteTab } from './PromoteTab'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/endpoints')>('@/api/endpoints')
  return {
    ...actual,
    compareDeploymentRefs: vi.fn(),
    draftReleaseNotes: vi.fn(),
    getCommitCheckStatus: vi.fn(),
    listCurrentReleases: vi.fn(),
    promoteDeployment: vi.fn(),
  }
})

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    loading: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}))

const ENV_TESTING: Environment = {
  description: null,
  icon: null,
  label_color: null,
  name: 'Testing',
  organization: { name: 'Acme', slug: 'acme' },
  relationships: null,
  slug: 'testing',
  sort_order: 0,
  updated_at: null,
}

const ENV_STAGING: Environment = {
  ...ENV_TESTING,
  name: 'Staging',
  slug: 'staging',
  sort_order: 1,
}

// The commit list this tab shows comes from `compare()`, which carries no
// check status at all — every `ci_status` here is `unknown`, which is
// precisely why the tab needs its own live lookup.
const COMPARE: DeploymentCompareResult = {
  additions: 1,
  ahead: 2,
  base_sha: 'v2.6.0',
  behind: 0,
  commits: [
    {
      author: 'bob',
      authored_at: '2026-06-01T00:00:00Z',
      ci_status: 'unknown',
      is_head: false,
      message: 'fix: broken thing',
      sha: 'bbb2222',
      short_sha: 'bbb2222',
    },
    {
      author: 'alice',
      authored_at: '2026-06-02T00:00:00Z',
      ci_status: 'unknown',
      is_head: true,
      message: 'feat: add thing',
      sha: 'aaa1111',
      short_sha: 'aaa1111',
    },
  ],
  deletions: 0,
  files_changed: 1,
  head_sha: 'aaa1111',
  pr_numbers: [],
}

const CURRENT: CurrentReleaseEnvironment[] = [
  {
    ci_status: null,
    current_status: null,
    environment: { name: 'Testing', slug: 'testing' },
    external_run_url: null,
    last_event_at: '2026-01-02T00:00:00Z',
    release: { committish: 'aaa1111', tag: 'v2.7.0' },
  },
  {
    ci_status: null,
    current_status: null,
    environment: { name: 'Staging', slug: 'staging' },
    external_run_url: null,
    last_event_at: '2026-01-01T00:00:00Z',
    release: { committish: 'bbb2222', tag: 'v2.6.0' },
  },
]

function renderPromoteTab(inFlight: ReleaseInFlightState = RELEASE_IDLE) {
  return render(
    <PromoteTab
      environments={[ENV_TESTING, ENV_STAGING]}
      fromEnvironment="testing"
      onClose={vi.fn()}
      open={true}
      orgSlug="acme"
      projectId="p1"
      releaseInFlight={inFlight}
      toEnvironment="staging"
    />,
  )
}

/** The tip commit is what the tab preselects. */
const promoteButton = () =>
  screen.getByRole('button', { name: /& deploy to staging/i })

describe('PromoteTab — failing CI on the build being promoted', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.listCurrentReleases).mockResolvedValue(CURRENT)
    vi.mocked(endpoints.compareDeploymentRefs).mockResolvedValue(COMPARE)
    vi.mocked(endpoints.draftReleaseNotes).mockResolvedValue({
      bump: 'minor',
      commits_considered: 2,
      degraded: false,
      notes_markdown: '## Notes',
      reasoning: 'a feature landed',
      version: 'v2.8.0',
    })
    vi.mocked(endpoints.promoteDeployment).mockResolvedValue({
      plugin_id: 'p-1',
      plugin_slug: 'github-deployment',
      recorded: true,
      run: { run_id: '', status: 'queued' },
      tag: 'v2.8.0',
    })
  })

  it('asks the API about the selected commit, not the tag', async () => {
    // The design note that drives the whole ticket: a tag-triggered run
    // skips the tests, so the tag has no CI status worth reading.
    vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
      ci_status: 'pass',
      committish: 'aaa1111',
    })
    renderPromoteTab()
    await waitFor(() => {
      expect(endpoints.getCommitCheckStatus).toHaveBeenCalledWith(
        'acme',
        'p1',
        'aaa1111',
        undefined,
        expect.anything(),
      )
    })
  })

  it('warns and holds the promote until it is acknowledged', async () => {
    vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
      ci_status: 'fail',
      committish: 'aaa1111',
    })
    renderPromoteTab()
    await waitFor(() => {
      expect(screen.getByText(/CI failed for aaa1111/)).toBeInTheDocument()
    })
    expect(promoteButton()).toBeDisabled()
  })

  it('promotes once acknowledged, and tells the API it was', async () => {
    const user = userEvent.setup()
    vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
      ci_status: 'fail',
      committish: 'aaa1111',
    })
    renderPromoteTab()
    await waitFor(() => {
      expect(screen.getByText(/CI failed for aaa1111/)).toBeInTheDocument()
    })
    await user.click(screen.getByRole('checkbox', { name: /Promote anyway/i }))
    await waitFor(() => {
      expect(promoteButton()).not.toBeDisabled()
    })
    await user.click(promoteButton())
    await waitFor(() => {
      expect(endpoints.promoteDeployment).toHaveBeenCalledWith(
        'acme',
        'p1',
        expect.objectContaining({
          acknowledge_ci_failure: true,
          from_committish: 'aaa1111',
        }),
      )
    })
  })

  it('does not warn on a green commit', async () => {
    vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
      ci_status: 'pass',
      committish: 'aaa1111',
    })
    renderPromoteTab()
    await waitFor(() => {
      expect(endpoints.getCommitCheckStatus).toHaveBeenCalled()
    })
    expect(screen.queryByText(/CI failed/)).not.toBeInTheDocument()
  })

  it('does not warn when the CI status is unknown', async () => {
    // Never-ran, no-CI, and no-scope all land here. Treating it as a
    // failure would put a confirmation in front of most promotes.
    vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
      ci_status: 'unknown',
      committish: 'aaa1111',
    })
    renderPromoteTab()
    await waitFor(() => {
      expect(endpoints.getCommitCheckStatus).toHaveBeenCalled()
    })
    expect(screen.queryByText(/CI failed/)).not.toBeInTheDocument()
  })

  it('sends acknowledge_ci_failure=false when nothing was overridden', async () => {
    const user = userEvent.setup()
    vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
      ci_status: 'pass',
      committish: 'aaa1111',
    })
    renderPromoteTab()
    await waitFor(() => {
      expect(screen.getByDisplayValue('v2.8.0')).toBeInTheDocument()
    })
    await user.click(promoteButton())
    await waitFor(() => {
      expect(endpoints.promoteDeployment).toHaveBeenCalledWith(
        'acme',
        'p1',
        expect.objectContaining({ acknowledge_ci_failure: false }),
      )
    })
  })

  it('drops the acknowledgement when another commit is selected', async () => {
    const user = userEvent.setup()
    vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
      ci_status: 'fail',
      committish: 'aaa1111',
    })
    renderPromoteTab()
    await waitFor(() => {
      expect(screen.getByText(/CI failed for aaa1111/)).toBeInTheDocument()
    })
    await user.click(screen.getByRole('checkbox', { name: /Promote anyway/i }))
    await user.click(screen.getByText('fix: broken thing'))
    await waitFor(() => {
      expect(
        screen.getByRole('checkbox', { name: /Promote anyway/i }),
      ).not.toBeChecked()
    })
    expect(promoteButton()).toBeDisabled()
  })
})

describe('PromoteTab — commit list columns', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.listCurrentReleases).mockResolvedValue(CURRENT)
    vi.mocked(endpoints.compareDeploymentRefs).mockResolvedValue(COMPARE)
    vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
      ci_status: 'pass',
      committish: 'aaa1111',
    })
    vi.mocked(endpoints.draftReleaseNotes).mockResolvedValue({
      bump: 'minor',
      commits_considered: 2,
      degraded: false,
      notes_markdown: '## Notes',
      reasoning: 'a feature landed',
      version: 'v2.8.0',
    })
  })

  it('shows each commit its age and author', async () => {
    renderPromoteTab()
    await waitFor(() => {
      expect(screen.getByText('feat: add thing')).toBeInTheDocument()
    })
    const ages = Array.from(document.querySelectorAll('time')).map((el) =>
      el.getAttribute('datetime'),
    )
    expect(ages).toEqual(['2026-06-02T00:00:00Z', '2026-06-01T00:00:00Z'])
    expect(screen.getByText('alice')).toBeInTheDocument()
    expect(screen.getByText('bob')).toBeInTheDocument()
  })

  it('leaves the age column empty for an undated commit', async () => {
    vi.mocked(endpoints.compareDeploymentRefs).mockResolvedValue({
      ...COMPARE,
      commits: COMPARE.commits.map(({ authored_at: _unused, ...rest }) => rest),
    })
    renderPromoteTab()
    await waitFor(() => {
      expect(screen.getByText('feat: add thing')).toBeInTheDocument()
    })
    expect(document.querySelectorAll('time')).toHaveLength(0)
  })
})

describe('PromoteTab — a release already in flight', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.listCurrentReleases).mockResolvedValue(CURRENT)
    vi.mocked(endpoints.compareDeploymentRefs).mockResolvedValue(COMPARE)
    vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
      ci_status: 'pass',
      committish: 'aaa1111',
    })
  })

  it('goes inert and says which release is holding it', async () => {
    // A promote cuts a tag and dispatches a build, so it is the same move
    // the release form makes and has the same duplicate-dispatch window.
    renderPromoteTab({
      ...RELEASE_IDLE,
      blocked: true,
      phase: 'building',
      tag: 'v2.7.0',
    })
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Release in flight/ }),
      ).toBeDisabled()
    })
    expect(
      screen.getByText('Blocked until v2.7.0 finishes releasing'),
    ).toBeInTheDocument()
  })
})

describe('PromoteTab — a refused dispatch', () => {
  const DETAIL =
    "The remote refused to run 'release.yml' as configured. That is what " +
    'it reports when the workflow declares no workflow_dispatch trigger.'

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.listCurrentReleases).mockResolvedValue(CURRENT)
    vi.mocked(endpoints.compareDeploymentRefs).mockResolvedValue(COMPARE)
    vi.mocked(endpoints.getCommitCheckStatus).mockResolvedValue({
      ci_status: 'pass',
      committish: 'aaa1111',
    })
    vi.mocked(endpoints.promoteDeployment).mockRejectedValue(
      new ApiError(400, 'Bad Request', { detail: DETAIL }),
    )
  })

  it('renders the server detail inline and re-enables the form', async () => {
    const user = userEvent.setup()
    renderPromoteTab()
    await waitFor(() => expect(promoteButton()).not.toBeDisabled())
    await user.click(promoteButton())
    await waitFor(() => {
      expect(screen.getByText(DETAIL)).toBeInTheDocument()
    })
    expect(screen.getByText('Promote refused')).toBeInTheDocument()
    // Nothing was dispatched, so nothing is in flight and the button
    // must come back rather than sitting spent.
    await waitFor(() => expect(promoteButton()).not.toBeDisabled())
  })

  it('leaves a failure it cannot explain to the toast', async () => {
    const user = userEvent.setup()
    vi.mocked(endpoints.promoteDeployment).mockRejectedValue(
      new ApiError(500, 'Internal Server Error', { detail: 'boom' }),
    )
    renderPromoteTab()
    await waitFor(() => expect(promoteButton()).not.toBeDisabled())
    await user.click(promoteButton())
    await waitFor(() => expect(endpoints.promoteDeployment).toHaveBeenCalled())
    expect(screen.queryByText('Promote refused')).toBeNull()
    // "Left to the toast" means the toast actually fires — without this a
    // regression that swallows the failure entirely would still pass.
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('boom'))
  })
})
