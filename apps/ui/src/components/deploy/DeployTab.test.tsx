import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { render } from '@/test/utils'
import type {
  CurrentReleaseEnvironment,
  DeploymentCommit,
  DeploymentCompareResult,
  DeploymentRef,
  Environment,
} from '@/types'

import { DeployTab } from './DeployTab'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/endpoints')>('@/api/endpoints')
  return {
    ...actual,
    compareDeploymentRefs: vi.fn(),
    listCurrentReleases: vi.fn(),
    listDeploymentRefs: vi.fn(),
    listRefCommits: vi.fn(),
    triggerDeployment: vi.fn(),
  }
})

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), loading: vi.fn(), success: vi.fn() },
}))

// Minimal environment fixtures — sort_order drives isFirstEnv ordering.
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

const ENVIRONMENTS = [ENV_TESTING, ENV_STAGING]

const TAG_A: DeploymentRef = {
  is_default: false,
  kind: 'tag',
  name: 'v2.7.0',
  sha: 'aaaaaaa1111111',
}

const TAG_B: DeploymentRef = {
  is_default: false,
  kind: 'tag',
  name: 'v2.6.0',
  sha: 'bbbbbbb2222222',
}

const COMMIT_A: DeploymentCommit = {
  author: 'alice',
  ci_status: 'pass',
  is_head: true,
  message: 'feat: add thing',
  sha: 'cccccccddddddd',
  short_sha: 'ccccccc',
}

const COMMIT_B: DeploymentCommit = {
  author: 'bob',
  ci_status: 'pass',
  is_head: false,
  message: 'fix: broken thing',
  sha: 'eeeeeeeffffffff',
  short_sha: 'eeeeeee',
}

const CURRENT_RELEASE: CurrentReleaseEnvironment = {
  ci_status: null,
  current_status: null,
  environment: { name: 'Staging', slug: 'staging' },
  external_run_url: null,
  last_event_at: '2024-01-15T10:00:00Z',
  release: {
    committish: 'bbbbbbb2222222',
    tag: 'v2.6.0',
  },
}

function renderDeployTab(envSlug = 'staging', envs = ENVIRONMENTS) {
  return render(
    <DeployTab
      environments={envs}
      initialEnvSlug={envSlug}
      onClose={vi.fn()}
      open={true}
      orgSlug="acme"
      projectId="p1"
    />,
  )
}

describe('DeployTab — environment card', () => {
  beforeEach(() => {
    vi.mocked(endpoints.listDeploymentRefs).mockResolvedValue([])
    vi.mocked(endpoints.listRefCommits).mockResolvedValue([])
    vi.mocked(endpoints.compareDeploymentRefs).mockResolvedValue({
      additions: 0,
      ahead: 0,
      base_sha: '',
      behind: 0,
      commits: [],
      deletions: 0,
      files_changed: 0,
      head_sha: '',
      pr_numbers: [],
    } satisfies DeploymentCompareResult)
  })

  it('shows skeletons while current releases are loading', () => {
    vi.mocked(endpoints.listCurrentReleases).mockReturnValue(
      new Promise(() => {}),
    )
    renderDeployTab()
    expect(screen.getByLabelText('Loading current release')).toBeInTheDocument()
  })

  it('shows current release tag and relative time when loaded', async () => {
    vi.mocked(endpoints.listCurrentReleases).mockResolvedValue([
      CURRENT_RELEASE,
    ])
    renderDeployTab()
    await waitFor(() => {
      expect(screen.getByText('v2.6.0')).toBeInTheDocument()
    })
  })

  it('shows "not deployed" when loaded but no release', async () => {
    vi.mocked(endpoints.listCurrentReleases).mockResolvedValue([
      { ...CURRENT_RELEASE, release: null },
    ])
    renderDeployTab()
    await waitFor(() => {
      expect(screen.getByText('not deployed')).toBeInTheDocument()
    })
  })

  it('shows error message when current releases query fails', async () => {
    vi.mocked(endpoints.listCurrentReleases).mockRejectedValue(new Error('500'))
    renderDeployTab()
    await waitFor(() => {
      expect(
        screen.getByText('Unable to load current release.'),
      ).toBeInTheDocument()
    })
  })
})

describe('DeployTab — tag list (staging/production)', () => {
  beforeEach(() => {
    vi.mocked(endpoints.listCurrentReleases).mockResolvedValue([])
    vi.mocked(endpoints.compareDeploymentRefs).mockResolvedValue({
      additions: 0,
      ahead: 0,
      base_sha: '',
      behind: 0,
      commits: [],
      deletions: 0,
      files_changed: 0,
      head_sha: '',
      pr_numbers: [],
    } satisfies DeploymentCompareResult)
  })

  it('shows skeletons while tags are loading', () => {
    vi.mocked(endpoints.listDeploymentRefs).mockReturnValue(
      new Promise(() => {}),
    )
    renderDeployTab('staging')
    expect(screen.getByLabelText('Loading tags')).toBeInTheDocument()
  })

  it('shows tags when loaded', async () => {
    vi.mocked(endpoints.listDeploymentRefs).mockResolvedValue([TAG_A, TAG_B])
    renderDeployTab('staging')
    await waitFor(() => {
      expect(screen.getByText('v2.7.0')).toBeInTheDocument()
      expect(screen.getByText('v2.6.0')).toBeInTheDocument()
    })
  })

  it('shows "No tags available" when loaded with empty list', async () => {
    vi.mocked(endpoints.listDeploymentRefs).mockResolvedValue([])
    renderDeployTab('staging')
    await waitFor(() => {
      expect(screen.getByText('No tags available.')).toBeInTheDocument()
    })
  })

  it('shows error banner when tag query fails', async () => {
    vi.mocked(endpoints.listDeploymentRefs).mockRejectedValue(new Error('502'))
    renderDeployTab('staging')
    await waitFor(() => {
      expect(screen.getByText(/Failed to load tags/)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    })
  })

  it('retries the tag query when Retry is clicked', async () => {
    const user = userEvent.setup()
    vi.mocked(endpoints.listDeploymentRefs)
      .mockRejectedValueOnce(new Error('502'))
      .mockResolvedValue([TAG_A])
    renderDeployTab('staging')
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => {
      expect(screen.getByText('v2.7.0')).toBeInTheDocument()
    })
  })

  it('tag buttons have cursor-pointer', async () => {
    vi.mocked(endpoints.listDeploymentRefs).mockResolvedValue([TAG_A])
    renderDeployTab('staging')
    await waitFor(() => {
      expect(screen.getByText('v2.7.0')).toBeInTheDocument()
    })
    const btn = screen.getByText('v2.7.0').closest('button')
    expect(btn).toHaveClass('cursor-pointer')
  })
})

describe('DeployTab — commit list (testing/first env)', () => {
  beforeEach(() => {
    vi.mocked(endpoints.listCurrentReleases).mockResolvedValue([])
    vi.mocked(endpoints.listDeploymentRefs).mockResolvedValue([
      { is_default: true, kind: 'default', name: 'main', sha: 'abc' },
    ])
  })

  it('shows skeletons while commits are loading', () => {
    vi.mocked(endpoints.listRefCommits).mockReturnValue(new Promise(() => {}))
    renderDeployTab('testing')
    expect(screen.getByLabelText('Loading commits')).toBeInTheDocument()
  })

  it('shows commits when loaded', async () => {
    vi.mocked(endpoints.listRefCommits).mockResolvedValue([COMMIT_A, COMMIT_B])
    renderDeployTab('testing')
    await waitFor(() => {
      expect(screen.getByText('feat: add thing')).toBeInTheDocument()
      expect(screen.getByText('fix: broken thing')).toBeInTheDocument()
    })
  })

  it('shows error banner when commits query fails', async () => {
    vi.mocked(endpoints.listRefCommits).mockRejectedValue(new Error('503'))
    renderDeployTab('testing')
    await waitFor(() => {
      expect(screen.getByText(/Failed to load commits/)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    })
  })

  it('retries the commit query when Retry is clicked', async () => {
    const user = userEvent.setup()
    vi.mocked(endpoints.listRefCommits)
      .mockRejectedValueOnce(new Error('503'))
      .mockResolvedValue([COMMIT_A])
    renderDeployTab('testing')
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => {
      expect(screen.getByText('feat: add thing')).toBeInTheDocument()
    })
  })

  it('commit buttons have cursor-pointer', async () => {
    vi.mocked(endpoints.listRefCommits).mockResolvedValue([COMMIT_A])
    renderDeployTab('testing')
    await waitFor(() => {
      expect(screen.getByText('feat: add thing')).toBeInTheDocument()
    })
    const btn = screen.getByText('feat: add thing').closest('button')
    expect(btn).toHaveClass('cursor-pointer')
  })
})

describe('DeployTab — diff summary', () => {
  beforeEach(() => {
    vi.mocked(endpoints.listCurrentReleases).mockResolvedValue([
      CURRENT_RELEASE,
    ])
    vi.mocked(endpoints.listDeploymentRefs).mockResolvedValue([TAG_A, TAG_B])
  })

  it('shows diff skeleton while compare is loading', async () => {
    const user = userEvent.setup()
    vi.mocked(endpoints.compareDeploymentRefs).mockReturnValue(
      new Promise(() => {}),
    )
    renderDeployTab('staging')
    await waitFor(() => {
      expect(screen.getByText('v2.7.0')).toBeInTheDocument()
    })
    await user.click(screen.getByText('v2.7.0').closest('button')!)
    await waitFor(() => {
      expect(screen.getByLabelText('Loading diff summary')).toBeInTheDocument()
    })
  })

  it('shows diff stats when compare resolves', async () => {
    const user = userEvent.setup()
    vi.mocked(endpoints.compareDeploymentRefs).mockResolvedValue({
      additions: 42,
      ahead: 3,
      base_sha: TAG_B.sha,
      behind: 0,
      commits: [COMMIT_A],
      deletions: 5,
      files_changed: 7,
      head_sha: TAG_A.sha,
      pr_numbers: [],
    } satisfies DeploymentCompareResult)
    renderDeployTab('staging')
    await waitFor(() => {
      expect(screen.getByText('v2.7.0')).toBeInTheDocument()
    })
    await user.click(screen.getByText('v2.7.0').closest('button')!)
    await waitFor(() => {
      expect(screen.getByText('1 commits')).toBeInTheDocument()
      expect(screen.getByText('7 files changed')).toBeInTheDocument()
    })
  })
})
